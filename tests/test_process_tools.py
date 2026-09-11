"""Harmless real subprocess tests for the optional execution boundary."""

import asyncio
import os
import sys

import pytest

from protolink import (
    ActionDeniedError,
    Agent,
    AgentCard,
    CapabilityPolicy,
    RunBudget,
    RunContext,
    RunHandle,
    Task,
    create_llm,
)
from protolink.core.budget import BudgetExceededError
from protolink.tools.builtins import process_tool


def agent(**kwargs):
    result = Agent(
        AgentCard(name="process-test", description="test", url="runtime://process-test"), verbosity=0, **kwargs
    )
    result.add_tool(process_tool())
    return result


def arguments(tmp_path, code="print('hello')", **kwargs):
    return {"argv": [sys.executable, "-c", code], "cwd": str(tmp_path), "env": {}, **kwargs}


@pytest.mark.asyncio
async def test_registration_and_denial_do_not_launch(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *a, **k: called.append(a))
    tool = process_tool()
    with pytest.raises(RuntimeError, match="authorization"):
        await tool(**arguments(tmp_path))
    a = agent(policy=CapabilityPolicy({"process.execute": "deny"}))
    with pytest.raises(ActionDeniedError):
        await a.call_tool("execute_command", **arguments(tmp_path))
    assert called == []


@pytest.mark.asyncio
async def test_exact_preview_explicit_environment_and_no_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTOLINK_TEST_SECRET", "must-not-inherit")
    requests = []

    async def approve(request, context):
        requests.append(request)
        return True

    a = agent(policy=CapabilityPolicy({"process.execute": "require_approval"}), approval_handler=approve)
    args = arguments(tmp_path, "import os,sys; print(os.getenv('PROTOLINK_TEST_SECRET')); print(sys.argv[1])")
    args["argv"].append("$HOME; *.py")
    result = await a.call_tool("execute_command", **args)
    assert result.stdout == "None\n$HOME; *.py\n"
    preview = requests[0].action.artifacts[0].parts[0].content
    assert preview["argv"][1:] == args["argv"][1:]
    assert preview["env"] == {}
    assert preview["cwd"] == str(tmp_path.resolve())
    assert "host" in preview["boundary"]
    assert preview["timeout_seconds"] == 60
    assert requests[0].action.artifacts[0].action_id == requests[0].action.action_id


@pytest.mark.asyncio
async def test_output_limit_nonzero_and_timeout(tmp_path):
    a = agent()
    result = await a.call_tool(
        "execute_command",
        **arguments(
            tmp_path,
            "import sys; print('x'*100000); print('error',file=sys.stderr); sys.exit(7)",
            max_output_bytes=101,
        ),
    )
    assert result.exit_code == 7 and result.truncated
    assert len(result.stdout.encode()) + len(result.stderr.encode()) <= 101
    assert not result.timed_out and result.duration_seconds > 0
    result = await a.call_tool(
        "execute_command", **arguments(tmp_path, "import time; time.sleep(30)", timeout_seconds=0.05)
    )
    assert result.timed_out and result.exit_code != 0


@pytest.mark.asyncio
async def test_stream_output_precedes_terminal_result(tmp_path):
    a = agent()
    task = Task.create_tool_call(tool_name="execute_command", args=arguments(tmp_path))
    handle = RunHandle.start(a, task)
    events = [event async for event in handle.events()]
    result = await asyncio.wait_for(handle.result(), 2)
    assert result.status == "completed"
    types = [event.type for event in events]
    assert types.index("process.output") < types.index("action.completed") < types.index("task.status", 1)
    assert result.report.final_task["id"] == task.id
    assert len(result.report.actions) == 1


@pytest.mark.asyncio
async def test_native_budgets_cover_direct_and_task_dispatch(tmp_path):
    a = agent()
    context = RunContext(budget=RunBudget(max_tool_calls=0))
    with pytest.raises(BudgetExceededError):
        await a.call_tool_in_context("execute_command", context, **arguments(tmp_path))
    task = Task.create_tool_call(tool_name="execute_command", args=arguments(tmp_path))
    context.attach_to_task(task)
    with pytest.raises(BudgetExceededError):
        await a.run_task(task)
    assert not any(event["type"] == "action.started" for event in task.metadata["run_events"])
    context = RunContext(budget=RunBudget(max_runtime_seconds=0.05))
    result = await a.call_tool_in_context(
        "execute_command", context, **arguments(tmp_path, "import time; time.sleep(30)")
    )
    assert result.timed_out and result.budget_exceeded


@pytest.mark.asyncio
async def test_explicit_context_budget_counts_repeated_direct_calls(tmp_path):
    a = agent()
    context = RunContext(budget=RunBudget(max_tool_calls=1))
    await a.call_tool_in_context("execute_command", context, **arguments(tmp_path))
    with pytest.raises(BudgetExceededError):
        await a.call_tool_in_context("execute_command", context, **arguments(tmp_path))


@pytest.mark.asyncio
async def test_approval_time_counts_towards_execution_budget(tmp_path, monkeypatch):
    launches = []
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *a, **k: launches.append(a))

    async def approve(request, context):
        await asyncio.sleep(0.02)
        return True

    a = agent(policy=CapabilityPolicy({"process.execute": "require_approval"}), approval_handler=approve)
    context = RunContext(budget=RunBudget(max_runtime_seconds=0.01))
    with pytest.raises(BudgetExceededError):
        await a.call_tool_in_context("execute_command", context, **arguments(tmp_path))
    assert launches == []


@pytest.mark.asyncio
async def test_process_inference_uses_prepared_executor(tmp_path):
    a = agent(
        llm=create_llm(
            "mock",
            sequential_responses=[
                {"type": "tool_call", "tool": "execute_command", "args": arguments(tmp_path)},
                {"type": "final", "content": "done"},
            ],
        )
    )
    handle = RunHandle.start(a, Task.create_infer(prompt="Run configured command"))
    result = await handle.result()
    assert result.status == "completed"
    assert any(event.type == "process.output" for event in result.report.events)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
async def test_cancellation_reaps_process_and_descendants(tmp_path):
    # The child would write a marker if it survived group cleanup.
    marker = tmp_path / "escaped"
    child = "import time,pathlib; time.sleep(.4); pathlib.Path('escaped').write_text('bad')"
    code = (
        f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); "
        "print('ready',flush=True); time.sleep(30)"
    )
    a = agent()
    handle = RunHandle.start(a, Task.create_tool_call(tool_name="execute_command", args=arguments(tmp_path, code)))
    async for event in handle.events():
        if event.type == "process.output":
            await handle.cancel()
            break
    result = await asyncio.wait_for(handle.result(), 3)
    assert result.status == "canceled"
    assert any(
        event.type == "process.finished" and event.payload["result"]["canceled"] for event in result.report.events
    )
    await asyncio.sleep(0.5)
    assert not marker.exists()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
async def test_normal_exit_cleans_descendants_without_waiting_for_timeout(tmp_path):
    child = "import time,pathlib; time.sleep(.4); pathlib.Path('leaked').write_text('bad')"
    code = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}]); print('parent finished')"
    result = await asyncio.wait_for(agent().call_tool("execute_command", **arguments(tmp_path, code)), 2)
    assert result.exit_code == 0 and not result.timed_out
    await asyncio.sleep(0.5)
    assert not (tmp_path / "leaked").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["run_task_streaming", "handle_task_streaming"])
async def test_closing_native_stream_cleans_running_process(tmp_path, method):
    from protolink.agents.engine import _current_task_budget

    a = agent()
    task = Task.create_tool_call(
        tool_name="execute_command",
        args=arguments(
            tmp_path,
            "import time,pathlib; print('ready',flush=True); time.sleep(.4); pathlib.Path('leaked').write_text('bad')",
        ),
    )
    stream = getattr(a, method)(task)
    async for event in stream:
        if getattr(event, "type", None) == "process.output":
            break
    assert _current_task_budget(None) is None
    await asyncio.wait_for(stream.aclose(), 2)
    await asyncio.sleep(0.5)
    assert not (tmp_path / "leaked").exists()
    assert a.get_cancellation_token(task.id) is None


@pytest.mark.asyncio
async def test_existing_redaction_applies_to_environment_and_output(tmp_path):
    from protolink import RedactionPolicy
    from protolink.core.redaction import DEFAULT_SENSITIVE_KEYS

    task = Task.create_tool_call(
        tool_name="execute_command",
        args=arguments(
            tmp_path,
            "import os; print(os.environ['TOKEN'])",
            env={"TOKEN": "private-test-value"},
        ),
    )
    policy = RedactionPolicy(sensitive_keys=DEFAULT_SENSITIVE_KEYS | {"stdout", "stderr", "text"})
    result = await RunHandle.start(agent(), task, redaction_policy=policy).result()
    assert "private-test-value" not in str(result.report.to_dict())


@pytest.mark.asyncio
async def test_cleanup_output_cannot_block_after_stream_consumer_closes():
    from protolink.core.execution import emit_runtime_event, stream_runtime_events

    task = Task.create_infer(prompt="stream cleanup")
    context = RunContext.ensure_task_context(task)
    cleaned = asyncio.Event()

    async def source():
        try:
            yield "ready"
            await asyncio.Event().wait()
        finally:
            # More events than the bounded queue can hold. Receipts remain on
            # the task, but cleanup must not wait for an abandoned consumer.
            for _ in range(100):
                await emit_runtime_event("cleanup.progress", context)
            cleaned.set()

    stream = stream_runtime_events(source(), task)
    assert await anext(stream) == "ready"
    await asyncio.wait_for(stream.aclose(), 1)
    assert cleaned.is_set()
    assert len(task.metadata["run_events"]) == 100
