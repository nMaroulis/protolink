"""Recovery is tested across process boundaries, including uncertain effects."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from protolink import (
    Agent,
    CapabilityPolicy,
    CheckpointMismatchError,
    DurableExecutionError,
    RunBudget,
    RunBusyError,
    RunContext,
    RunInterrupted,
    SQLiteDurableStore,
    Task,
    TaskState,
    UncertainExecutionError,
)
from protolink.llms import MockLLM
from protolink.tools import Tool
from protolink.tools.builtins import ask_user_tool


def scripted(*actions):
    return MockLLM(sequential_responses=list(actions))


def approval_agent(path, calls, **kwargs):
    def write(value: str) -> str:
        """Commit a value to the test application."""
        calls.append(value)
        return value

    return Agent(
        name="writer",
        llm=scripted({"type": "tool_call", "tool": "write", "args": {"value": "saved"}}, "done"),
        tools=[Tool.from_callable(write, description="Write a value.", capabilities=["test.write"])],
        policy=CapabilityPolicy({"test.write": "require_approval"}),
        durability=path,
        verbosity=0,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_approval_restart_preserves_action_history_budget_and_completed_output(tmp_path):
    calls = []
    agent = approval_agent(tmp_path / "runs.db", calls)
    with pytest.raises(RunInterrupted) as raised:
        await agent.invoke("save")
    pause = raised.value
    record = agent.durability.get(pause.run_id)
    assert record.status == "input-required"
    assert calls == []
    assert record.data["usage"]["llm_calls"] == 1
    original_action = next(iter(record.data["actions"].values()))["action"]
    restarted = approval_agent(tmp_path / "runs.db", calls)
    assert await restarted.resume(pause.run_id, request_id=pause.interruption.request_id, approved=True) == "done"
    assert calls == ["saved"]
    completed = restarted.durability.get(pause.run_id)
    assert completed.status == "completed"
    assert completed.data["usage"]["tool_calls"] == 1
    assert next(iter(completed.data["actions"].values()))["action"] == original_action
    assert await approval_agent(tmp_path / "runs.db", calls).resume(pause.run_id) == "done"
    assert calls == ["saved"]


@pytest.mark.asyncio
async def test_denial_and_stale_response_do_not_dispatch(tmp_path):
    calls = []
    agent = approval_agent(tmp_path / "runs.db", calls)
    with pytest.raises(RunInterrupted) as raised:
        await agent.invoke("save")
    pause = raised.value
    with pytest.raises(DurableExecutionError, match="match"):
        await agent.resume(pause.run_id, request_id="stale", approved=True)
    with pytest.raises(DurableExecutionError, match="match"):
        await agent.resume(pause.run_id, request_id=pause.interruption.request_id, approved=True, fingerprint="stale")
    assert calls == []
    with pytest.raises(Exception, match="denied"):
        await agent.resume(pause.run_id, request_id=pause.interruption.request_id, approved=False)
    assert calls == []


@pytest.mark.asyncio
async def test_changed_execution_contract_fails_closed(tmp_path):
    agent = approval_agent(tmp_path / "runs.db", [])
    with pytest.raises(RunInterrupted) as raised:
        await agent.invoke("save")
    with pytest.raises(CheckpointMismatchError):
        await approval_agent(tmp_path / "runs.db", [], execution_version="2").resume(raised.value.run_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["CSV", None])
async def test_question_resume_has_one_tool_charge_with_one_call_budget(tmp_path, answer):
    def make():
        return Agent(
            name="question",
            llm=scripted({"type": "tool_call", "tool": "ask_user", "args": {"question": "Format?"}}, "done"),
            tools=[ask_user_tool()],
            durability=tmp_path / "runs.db",
            verbosity=0,
        )

    agent = make()
    task = Task.create_infer("choose")
    RunContext(budget=RunBudget(max_tool_calls=1)).attach_to_task(task)
    paused = await agent.run_task(task)
    assert paused.state is TaskState.INPUT_REQUIRED
    pending = paused.metadata["interruption"]
    run_id = RunContext.from_task(task).run_id
    restarted = make()
    assert await restarted.resume(run_id, request_id=pending["request_id"], answer=answer) == "done"
    record = restarted.durability.get(run_id)
    assert record.data["usage"]["tool_calls"] == 1
    observation = next(entry["result"] for entry in record.data["actions"].values())
    assert observation["answer"] == answer
    assert observation["status"] == ("declined" if answer is None else "answered")


@pytest.mark.asyncio
async def test_standalone_tool_can_pause_and_resume(tmp_path):
    calls = []
    agent = approval_agent(tmp_path / "runs.db", calls)
    with pytest.raises(RunInterrupted) as raised:
        await agent.call_tool("write", value="direct")
    pause = raised.value
    assert (
        await approval_agent(tmp_path / "runs.db", calls).resume(
            pause.run_id, request_id=pause.interruption.request_id, approved=True
        )
        == "direct"
    )
    assert calls == ["direct"]


@pytest.mark.asyncio
async def test_durable_stream_delivers_chunks_and_pending_state(tmp_path):
    agent = Agent(name="stream", llm=scripted("done"), durability=tmp_path / "runs.db", verbosity=0)
    handle = agent.start_run("hello")
    chunks = [chunk async for chunk in handle.chunks()]
    result = await handle.result()
    assert result.task.state is TaskState.COMPLETED
    assert "done" in "".join(chunks)
    assert agent.durability.get(handle.context.run_id).status == "completed"


def test_store_leases_fence_competing_writers(tmp_path, monkeypatch):
    import protolink.storage.durable as module

    now = [100.0]
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    store = SQLiteDurableStore(tmp_path / "runs.db", lease_seconds=2)
    first, _ = store.acquire("r", "a", {"value": 1})
    with pytest.raises(RunBusyError):
        store.acquire("r", "a", {})
    now[0] = 103.0
    second, _ = store.acquire("r", "a", {})
    with pytest.raises(RunBusyError):
        store.save("r", first, "completed", {})
    store.release("r", first)
    store.save("r", second, "completed", {"value": 2})
    assert store.get("r").data == {"value": 2}
    store.release("r", second)


PROCESS_PROGRAM = '''
import asyncio, json, os, sys
from pathlib import Path
from protolink import Agent, CapabilityPolicy, RunInterrupted, RunAction
from protolink.llms import MockLLM
from protolink.tools import Tool
from protolink.storage.durable import SQLiteDurableStore

base=Path(sys.argv[1]); mode=sys.argv[2]
def write(value: str) -> str:
    """Save once in the external system."""
    with (base / "effects.txt").open("a") as file: file.write(value + "\\n")
    if mode == "crash-in-tool": os._exit(71)
    return value
def prepare(arguments, context):
    effects=base / "effects.txt"
    revision=effects.read_text() if effects.exists() else "missing"
    return RunAction(kind="tool.call", name="write", payload={"arguments":arguments},
        description="Write a value.", metadata={"external_revision":revision})
class CrashStore(SQLiteDurableStore):
    def save(self, run_id, token, status, data):
        super().save(run_id, token, status, data)
        if mode == "crash-after-receipt" and any(e["state"] == "succeeded" for e in data["actions"].values()):
            os._exit(72)
def response(history, _):
    if any(str(m.get("content")).startswith('{"type": "tool_result"') for m in history.messages): return "done"
    return {"type":"tool_call","tool":"write","args":{"value":"saved"}}
agent=Agent(name="writer",llm=MockLLM(response_callback=response),
    tools=[Tool.from_callable(write,description="Write a value.",capabilities=["test.write"],action_builder=prepare)],
    policy=CapabilityPolicy({"test.write":"require_approval"}) if mode in {"pause", "approve"} else None,
    durability=CrashStore(base/"runs.db"),verbosity=0)
async def main():
    if mode in {"resume","approve"}:
        request=json.loads((base/"pause.json").read_text()) if mode=="approve" else None
        response = {"request_id":request["request_id"],"approved":True} if request else {}
        print(await agent.resume((base/"id.txt").read_text(), **response))
    else:
        from protolink import Task,RunContext
        task=Task.create_infer("save");RunContext.ensure_task_context(task,agent_name="writer")
        (base/"id.txt").write_text(RunContext.from_task(task).run_id)
        task=await agent.run_task(task)
        if "interruption" in task.metadata: (base/"pause.json").write_text(json.dumps(task.metadata["interruption"]))
asyncio.run(main())
'''


def process(tmp_path, mode):
    return subprocess.run(
        [sys.executable, "-c", PROCESS_PROGRAM, str(tmp_path), mode],
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "PYTHONPATH": str(Path.cwd())},
    )


def test_approval_survives_actual_process_restart(tmp_path):
    paused = process(tmp_path, "pause")
    assert paused.returncode == 0, paused.stderr
    assert not (tmp_path / "effects.txt").exists()
    resumed = process(tmp_path, "approve")
    assert resumed.returncode == 0, resumed.stderr
    assert resumed.stdout.strip() == "done"
    assert (tmp_path / "effects.txt").read_text() == "saved\n"


def test_crash_after_receipt_reuses_result_without_repeating_effect(tmp_path):
    assert process(tmp_path, "crash-after-receipt").returncode == 72
    resumed = process(tmp_path, "resume")
    assert resumed.returncode == 0, resumed.stderr
    assert resumed.stdout.strip() == "done"
    assert (tmp_path / "effects.txt").read_text() == "saved\n"


@pytest.mark.asyncio
async def test_crash_without_receipt_requires_verified_reconciliation(tmp_path):
    assert process(tmp_path, "crash-in-tool").returncode == 71
    run_id = (tmp_path / "id.txt").read_text()
    # Exactly the same declared contract; this process cannot infer whether the external effect committed.
    calls = []
    agent = approval_agent(tmp_path / "runs.db", calls)
    agent.action_authorizer.policy = CapabilityPolicy()
    with pytest.raises(Exception) as raised:
        await agent.resume(run_id)
    cause = raised.value
    while cause.__cause__ is not None:
        cause = cause.__cause__
    assert isinstance(cause, UncertainExecutionError)
    assert calls == []
    record = agent.durability.get(run_id)
    action = next(iter(record.data["actions"].values()))["action"]
    agent.reconcile(run_id, action["action_id"], result="saved")
    assert await agent.resume(run_id) == "done"
    assert calls == []
    assert (tmp_path / "effects.txt").read_text() == "saved\n"


@pytest.mark.asyncio
async def test_same_action_can_wait_for_approval_then_input(tmp_path):
    def make():
        return Agent(
            name="question",
            tools=[ask_user_tool()],
            durability=tmp_path / "runs.db",
            verbosity=0,
            llm=scripted({"type": "tool_call", "tool": "ask_user", "args": {"question": "Format?"}}, "done"),
            policy=CapabilityPolicy({"user.interact": "require_approval"}),
        )

    with pytest.raises(RunInterrupted) as raised:
        await make().invoke("choose")
    approval = raised.value
    with pytest.raises(RunInterrupted) as raised:
        await make().resume(approval.run_id, request_id=approval.interruption.request_id, approved=True)
    question = raised.value
    assert question.interruption.kind == "input"
    assert question.interruption.request_id != approval.interruption.request_id
    agent = make()
    assert await agent.resume(question.run_id, request_id=question.interruption.request_id, answer="CSV") == "done"
    assert agent.durability.get(question.run_id).data["usage"]["tool_calls"] == 1


@pytest.mark.asyncio
async def test_prepared_resource_change_rejects_stale_approval(tmp_path):
    from protolink import StorageCheckpointStore
    from protolink.storage import SQLiteStorage
    from protolink.tools.builtins import filesystem_tools

    root = tmp_path / "files"
    root.mkdir()
    file = root / "note"
    file.write_text("old")

    def make():
        return Agent(
            name="files",
            tools=filesystem_tools(
                roots=[root], checkpoints=StorageCheckpointStore(SQLiteStorage(str(tmp_path / "recovery.db")))
            ),
            durability=tmp_path / "runs.db",
            verbosity=0,
            policy=CapabilityPolicy({"filesystem.write": "require_approval"}),
        )

    with pytest.raises(RunInterrupted) as raised:
        await make().call_tool("replace_file", path=str(file), content="new")
    pause = raised.value
    file.write_text("changed outside")
    with pytest.raises(CheckpointMismatchError, match="preconditions"):
        await make().resume(pause.run_id, request_id=pause.interruption.request_id, approved=True)
    assert file.read_text() == "changed outside"


@pytest.mark.asyncio
async def test_multiple_parts_resume_at_saved_cursor_without_reexecuting_first_tool(tmp_path):
    from protolink import Message, Part

    calls = []

    def first() -> str:
        calls.append("first")
        return "first result"

    def second() -> str:
        calls.append("second")
        return "second result"

    def make():
        return Agent(
            name="parts",
            tools=[first, Tool.from_callable(second, capabilities=["test.write"])],
            policy=CapabilityPolicy({"test.write": "require_approval"}),
            durability=tmp_path / "runs.db",
            verbosity=0,
        )

    task = Task(
        messages=[
            Message(parts=[Part.tool_call(tool_name="first", args={}), Part.tool_call(tool_name="second", args={})])
        ]
    )
    task = await make().run_task(task)
    pause = RunInterrupted(task)
    assert calls == ["first"]
    assert await make().resume(pause.run_id, request_id=pause.interruption.request_id, approved=True) == "second result"
    assert calls == ["first", "second"]


@pytest.mark.asyncio
async def test_native_action_adapter_resumes_same_pending_action(tmp_path):
    from protolink.llms.actions import FinalAction, LLMActionResult, ToolCallAction, action_to_json

    calls = []

    def write() -> str:
        calls.append(1)
        return "saved"

    class Native(MockLLM):
        async def call_action(self, history, **kwargs):
            action = (
                FinalAction(type="final", content="done")
                if any(str(message.get("content")).startswith('{"type": "tool_result"') for message in history.messages)
                else ToolCallAction(type="tool_call", tool="write", args={})
            )
            return LLMActionResult(action=action, raw_response=action_to_json(action), native=True)

    def make():
        return Agent(
            name="native",
            llm=Native(),
            tools=[Tool.from_callable(write, capabilities=["test.write"])],
            policy=CapabilityPolicy({"test.write": "require_approval"}),
            durability=tmp_path / "runs.db",
            verbosity=0,
        )

    with pytest.raises(RunInterrupted) as raised:
        await make().invoke("go")
    pause = raised.value
    assert await make().resume(pause.run_id, request_id=pause.interruption.request_id, approved=True) == "done"
    assert calls == [1]


def test_sync_resume_matches_async_convenience(tmp_path):
    calls = []
    with pytest.raises(RunInterrupted) as raised:
        approval_agent(tmp_path / "runs.db", calls).sync.invoke("go")
    pause = raised.value
    assert (
        approval_agent(tmp_path / "runs.db", calls).sync.resume(
            pause.run_id, request_id=pause.interruption.request_id, approved=True
        )
        == "done"
    )
    assert calls == ["saved"]


@pytest.mark.asyncio
async def test_preview_content_ids_are_preconditions_not_ephemeral_artifact_ids(tmp_path):
    from protolink import Artifact, Part, RunAction

    revision = ["original"]
    calls = []

    def write() -> str:
        calls.append(1)
        return "saved"

    def preview(arguments, context):
        return RunAction(kind="tool.call", name="write", payload={"arguments": arguments}).with_artifacts(
            [Artifact(parts=[Part.json({"id": revision[0]})], kind="preview")]
        )

    agent = Agent(
        name="preview",
        tools=[Tool.from_callable(write, capabilities=["test.write"], action_builder=preview)],
        durability=tmp_path / "runs.db",
        policy=CapabilityPolicy({"test.write": "require_approval"}),
        verbosity=0,
    )
    with pytest.raises(RunInterrupted) as raised:
        await agent.call_tool("write")
    pause = raised.value
    revision[0] = "changed"
    with pytest.raises(CheckpointMismatchError):
        await agent.resume(pause.run_id, request_id=pause.interruption.request_id, approved=True)
    assert calls == []


@pytest.mark.asyncio
async def test_invalid_input_response_does_not_consume_pending_request(tmp_path):
    agent = Agent(
        name="question", tools=[ask_user_tool(max_answer_chars=3)], durability=tmp_path / "runs.db", verbosity=0
    )
    with pytest.raises(RunInterrupted) as raised:
        await agent.call_tool("ask_user", question="Format?")
    pause = raised.value
    with pytest.raises(ValueError, match="max_answer_chars"):
        await agent.resume(pause.run_id, request_id=pause.interruption.request_id, answer="too long")
    assert agent.durability.get(pause.run_id).status == "input-required"
    assert (await agent.resume(pause.run_id, request_id=pause.interruption.request_id, answer="CSV"))["answer"] == "CSV"


@pytest.mark.asyncio
async def test_committed_effect_does_not_need_new_approval_to_reuse_its_receipt(tmp_path):
    assert process(tmp_path, "crash-after-receipt").returncode == 72
    calls = []
    agent = approval_agent(tmp_path / "runs.db", calls)
    assert await agent.resume((tmp_path / "id.txt").read_text()) == "done"
    assert calls == []
    assert (tmp_path / "effects.txt").read_text() == "saved\n"


def test_reconcile_finds_matching_contract_when_separate_branches_reuse_a_worker_name(tmp_path):
    assert process(tmp_path, "crash-in-tool").returncode == 71
    target = approval_agent(tmp_path / "runs.db", [])
    other = approval_agent(tmp_path / "runs.db", [], execution_version="2")
    root = Agent(
        name="root",
        durability=tmp_path / "runs.db",
        verbosity=0,
        subagents=[
            Agent(name="left", subagents=[target], verbosity=0),
            Agent(name="right", subagents=[other], verbosity=0),
        ],
    )
    run_id = (tmp_path / "id.txt").read_text()
    record = root.durability.get(run_id)
    action_id = next(iter(record.data["actions"].values()))["action"]["action_id"]
    root.reconcile(run_id, action_id, result="saved")
    assert root.durability.get(run_id).status == "ready"
    assert (tmp_path / "effects.txt").read_text() == "saved\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["approval", "input"])
async def test_repeated_wait_attempts_keep_the_same_request_id_in_events(tmp_path, kind):
    agent = (
        approval_agent(tmp_path / "runs.db", [])
        if kind == "approval"
        else Agent(name="question", tools=[ask_user_tool()], durability=tmp_path / "runs.db", verbosity=0)
    )
    with pytest.raises(RunInterrupted) as raised:
        if kind == "approval":
            await agent.call_tool("write", value="save")
        else:
            await agent.call_tool("ask_user", question="Format?")
    pause = raised.value
    waiting = await agent.resume_task(pause.run_id)
    assert waiting.state is TaskState.INPUT_REQUIRED
    event_type = "approval.required" if kind == "approval" else "user_input.requested"
    requests = [event["payload"]["request"] for event in waiting.metadata["run_events"] if event["type"] == event_type]
    assert len(requests) == 2
    assert {request["request_id"] for request in requests} == {pause.interruption.request_id}
