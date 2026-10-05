"""Preset composition, scoped execution and deterministic echo contracts."""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from protolink import (
    ActionDeniedError,
    Agent,
    AgentCard,
    AgentGroup,
    ApprovalRequiredError,
    Assistant,
    CapabilityPolicy,
    CodeAssistant,
    DatabaseAgent,
    Document,
    EchoAgent,
    ExplorerAgent,
    KnowledgeAgent,
    Message,
    Part,
    ResearchAgent,
    RunContext,
    RunInterrupted,
    StorageCheckpointStore,
    Task,
    TaskState,
    create_knowledge,
)
from protolink.llms import MockLLM
from protolink.storage import SQLiteStorage
from protolink.tools import Tool
from protolink.tools.builtins import SQLiteDatabase


def preset(kind, tmp_path, **options):
    kwargs = {"verbosity": 0, **options}
    if kind is CodeAssistant:
        kwargs["cwd"] = tmp_path
    elif kind is ExplorerAgent:
        if os.name != "posix":
            pytest.skip("Scoped file tools require POSIX")
        kwargs["roots"] = [tmp_path]
    elif kind is DatabaseAgent:
        kwargs["database"] = SQLiteDatabase(tmp_path / "not-opened.db")
    elif kind is KnowledgeAgent:
        kwargs["sources"] = [Document(text="Test knowledge", source="test.md")]
    return kind(**kwargs)


PRESETS = [Assistant, CodeAssistant, DatabaseAgent, ExplorerAgent, KnowledgeAgent, ResearchAgent]


@pytest.mark.parametrize("kind", [*PRESETS, EchoAgent])
def test_identity_prompt_and_model_alias_are_standard_agent_options(kind, tmp_path):
    agent = preset(kind, tmp_path, name="custom", description="Caller description", llm="mock")
    assert agent.card.name == "custom"
    assert agent.card.description == "Caller description"
    assert agent.card.url == "runtime://custom"
    assert isinstance(agent.llm, MockLLM)
    card = AgentCard(name="card", description="Explicit card", url="runtime://card")
    assert preset(kind, tmp_path, card=card).card is card
    with pytest.raises(ValueError, match="either card"):
        preset(kind, tmp_path, card=card, name="conflict")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", PRESETS)
async def test_durable_questions_resume_on_reconstructed_preset(kind, tmp_path):
    def make():
        return preset(kind, tmp_path, durability=tmp_path / "runs.db")

    agent = make()
    assert "ask_user" in agent.tools
    with pytest.raises(RunInterrupted) as raised:
        await agent.call_tool("ask_user", question="Which scope?")
    pause = raised.value
    assert pause.interruption.kind == "input"
    restarted = make()
    result = await restarted.resume(pause.run_id, request_id=pause.interruption.request_id, answer="This workspace")
    assert result["answer"] == "This workspace"
    assert result["status"] == "answered"
    assert restarted.durability.get(pause.run_id).status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", PRESETS)
async def test_custom_policies_and_supplied_tools_take_precedence(kind, tmp_path):
    def custom_calculator(expression: str) -> str:
        return f"custom:{expression}"

    tool = Tool.from_callable(custom_calculator, name="calculator", capabilities=["application.read"])
    policy = CapabilityPolicy({"application.read": "deny"})
    agent = preset(kind, tmp_path, tools=[tool], policy=policy, system_prompt="Caller instructions")
    assert agent.tools["calculator"] is tool
    assert agent.action_authorizer.policy is policy
    assert agent._system_prompt == "Caller instructions"
    with pytest.raises(ActionDeniedError):
        await agent.call_tool("calculator", expression="1+1")


@pytest.mark.asyncio
async def test_research_engine_is_fixed_and_preserves_bounded_validation(monkeypatch):
    from protolink.tools.builtins import web

    calls = []

    async def search(query, max_results, freshness):
        calls.append((query, max_results, freshness))
        return [
            {"title": "Source", "url": "https://example.com/primary", "snippet": "Evidence", "sponsored": False}
        ], False

    monkeypatch.setattr(web, "_search_wikipedia", search)
    agent = ResearchAgent(search_engine="wikipedia", verbosity=0)
    result = await agent.call_tool("web_search", query="Evidence", max_results=2)
    assert result["provider"] == "wikipedia" and result["untrusted_content"]
    assert calls == [("Evidence", 2, "any")]
    with pytest.raises(ValueError):
        await agent.call_tool("web_search", query="Evidence", max_results=11)
    with pytest.raises(ValueError):
        await agent.call_tool("web_search", query="Evidence", engine="brave")
    assert len(calls) == 1
    with pytest.raises(ValueError, match="search_engine"):
        ResearchAgent(search_engine="unknown", verbosity=0)


@pytest.mark.asyncio
async def test_research_custom_provider_and_fetch_are_normal_tools():
    def search(query: str) -> dict:
        return {"url": "https://example.com/source", "query": query}

    def fetch(url: str) -> dict:
        return {"url": url, "text": "Verified fixture"}

    agent = ResearchAgent(
        search_tool=Tool.from_callable(search, name="custom_search", capabilities=["network.read"]),
        fetch_tool=Tool.from_callable(fetch, name="custom_fetch", capabilities=["network.read"]),
        verbosity=0,
    )
    assert "web_search" not in agent.tools and "fetch_url" not in agent.tools
    source = await agent.call_tool("custom_search", query="fixture")
    assert (await agent.call_tool("custom_fetch", url=source["url"]))["text"] == "Verified fixture"


@pytest.mark.asyncio
async def test_knowledge_citations_empty_evidence_and_custom_retrieval():
    knowledge = create_knowledge(
        name="handbook", sources=[Document(text="Receipts are due in 30 days.", source="policy.md")]
    )

    def respond(history, _prompt):
        for message in reversed(history.messages):
            if message.get("role") != "system":
                continue
            try:
                value = json.loads(str(message.get("content", "")))
            except json.JSONDecodeError:
                continue
            if value.get("type") == "tool_result":
                hits = value["result"]["hits"]
                return {
                    "type": "final",
                    "content": f"{hits[0]['text']} {hits[0]['citation']}" if hits else "Insufficient evidence",
                }
        return {"type": "tool_call", "tool": "search_handbook", "args": {"query": "receipt deadline"}}

    agent = KnowledgeAgent(knowledge=knowledge, llm=MockLLM(response_callback=respond), verbosity=0)
    result = await agent.invoke("When are receipts due?")
    assert "30 days" in result and "[handbook:" in result
    assert "policy.md" in str(await agent.call_tool("search_handbook", query="receipts"))

    async def empty(query, *, k, where):
        return []

    empty_agent = KnowledgeAgent(
        knowledge=create_knowledge(empty, name="handbook"), llm=MockLLM(response_callback=respond), verbosity=0
    )
    assert await empty_agent.invoke("Missing policy?") == "Insufficient evidence"
    with pytest.raises(ValueError, match="either knowledge"):
        KnowledgeAgent(knowledge=knowledge, sources=["ignored"])
    with pytest.raises(ValueError, match="requires"):
        KnowledgeAgent()


@pytest.mark.asyncio
async def test_database_binds_values_bounds_rows_and_rejects_writes(tmp_path):
    path = tmp_path / "data.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sales(region TEXT, total INTEGER)")
        connection.executemany("INSERT INTO sales VALUES (?, ?)", [("EU", 4), ("EU", 8), ("US", 12)])
    agent = DatabaseAgent(database=SQLiteDatabase(path), verbosity=0)
    assert "sales" in str(await agent.call_tool("database_schema"))
    result = await agent.call_tool(
        "query_database", sql="SELECT total FROM sales WHERE region = ? ORDER BY total", parameters=["EU"], max_rows=1
    )
    assert result["rows"] == [[4]] and result["truncated"]
    with pytest.raises(Exception, match=r"read-only|not authorized"):
        await agent.call_tool("query_database", sql="DELETE FROM sales")
    assert (await agent.call_tool("query_database", sql="SELECT COUNT(*) FROM sales"))["rows"] == [[3]]


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="Scoped file tools require POSIX")
async def test_explorer_boundaries_documents_and_owned_delegation(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    path = root / "readme.txt"
    path.write_text("Evidence in the workspace.")
    outside = tmp_path / "outside.txt"
    outside.write_text("Private")
    (root / "link").symlink_to(outside)
    explorer = ExplorerAgent(roots=[root], documents=True, name="reader", verbosity=0)
    assert "read_document" in explorer.tools
    assert "run_shell" not in explorer.tools and "edit_file" not in explorer.tools
    assert (await explorer.call_tool("read_file", path=str(path)))["content"] == path.read_text()
    with pytest.raises(ValueError, match="outside"):
        await explorer.call_tool("read_file", path=str(outside))
    with pytest.raises((ValueError, OSError)):
        await explorer.call_tool("read_file", path=str(root / "link"))
    with pytest.raises(ValueError, match="inside"):
        ExplorerAgent(roots=[root], git_cwd=tmp_path, verbosity=0)
    explorer.llm = MockLLM(
        sequential_responses=[
            {"type": "tool_call", "tool": "read_file", "args": {"path": str(path)}},
            "Child evidence",
        ]
    )
    parent = Agent(
        name="parent",
        subagents=[explorer],
        verbosity=0,
        llm=MockLLM(
            sequential_responses=[
                {"type": "agent_call", "agent": "reader", "action": "infer", "prompt": "Read the workspace"},
                "Done",
            ]
        ),
    )
    task = await parent.run_task(Task.create_infer(prompt="Inspect"))
    assert task.get_output() == "Done"
    assert task.metadata["subagent_runs"][0]["agent"] == "reader"


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="Scoped file tools require POSIX")
async def test_code_edits_require_approval_and_recovery_survives_reconstruction(tmp_path):
    path = tmp_path / "code.py"
    path.write_text("before")
    checkpoint_path = tmp_path / "recovery.db"

    def make(**options):
        return CodeAssistant(
            cwd=tmp_path,
            checkpoints=StorageCheckpointStore(SQLiteStorage(str(checkpoint_path))),
            verbosity=0,
            **options,
        )

    coder = make()
    assert (await coder.call_tool("read_file", path=str(path)))["content"] == "before"
    with pytest.raises(ApprovalRequiredError):
        await coder.call_tool("replace_file", path=str(path), content="after")
    assert path.read_text() == "before"
    receipt = await make(approval_handler=lambda request, context: True).call_tool(
        "replace_file", path=str(path), content="after"
    )
    assert path.read_text() == "after"
    with pytest.raises(ApprovalRequiredError):
        await make().call_tool("restore_change", change_id=receipt["change_id"])
    await make(approval_handler=lambda request, context: True).call_tool(
        "restore_change", change_id=receipt["change_id"]
    )
    assert path.read_text() == "before"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["Hello", "", "  café\n\t世界  "])
async def test_echo_invoke_and_stream_return_exact_input(text):
    agent = EchoAgent(verbosity=0)
    assert agent.llm is None
    assert await agent.invoke(text) == text
    task = Task.create(text)
    events = [event async for event in agent.run_task_streaming(task)]
    assert task.state is TaskState.COMPLETED
    assert task.messages[-1].parts[0].content == text
    assert events[-1].final
    assert events[-1].metadata["task"]["messages"][-1]["parts"][0]["content"] == text
    assert len(task.messages) == 2
    await agent.run_task(task)
    assert len(task.messages) == 2


@pytest.mark.asyncio
async def test_echo_copies_structured_parts_without_executing_them():
    calls = []

    def dangerous() -> str:
        calls.append(True)
        return "executed"

    agent = EchoAgent(llm=MockLLM(default_response="not an echo"), tools=[dangerous], verbosity=0)
    message = Message(
        parts=[
            Part.text("one"),
            Part(type="data", content={"nested": [1]}),
            Part.tool_call(tool_name="dangerous", args={}),
        ]
    )
    task = await agent.run_task(Task.create(message))
    assert calls == []
    assert [part.to_dict() for part in task.messages[-1].parts] == [part.to_dict() for part in message.parts]
    task.messages[-1].parts[1].content["nested"].append(2)
    assert message.parts[1].content == {"nested": [1]}


def test_echo_sync_facade():
    assert EchoAgent(verbosity=0).sync.invoke("Exact") == "Exact"


@pytest.mark.asyncio
async def test_echo_runtime_transport_and_durable_result_are_model_free(tmp_path):
    echo = EchoAgent(name="echo-roundtrip", transport="runtime", verbosity=0)
    caller = Agent(name="echo-caller", transport="runtime", verbosity=0)
    async with AgentGroup([echo, caller]):
        task = await caller.call_agent(echo.card.url, Task.create_infer(prompt="  transported\n"))
        assert task.state is TaskState.COMPLETED
        assert task.get_output() == "  transported\n"
    durable = EchoAgent(durability=tmp_path / "echo.db", verbosity=0)
    task = await durable.run_task(Task.create_infer(prompt="saved"))
    restarted = EchoAgent(durability=tmp_path / "echo.db", verbosity=0)
    assert await restarted.resume(RunContext.from_task(task).run_id) == "saved"
    canceled = Task.create("do not echo", context=RunContext(canceled=True, cancel_reason="Stopped"))
    await echo.run_task(canceled)
    assert canceled.state is TaskState.CANCELED and len(canceled.messages) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", PRESETS)
async def test_default_policies_deny_unrelated_capabilities(kind, tmp_path):
    calls = []

    def unrelated() -> str:
        calls.append(True)
        return "effect"

    agent = preset(kind, tmp_path, tools=[Tool.from_callable(unrelated, capabilities=["unrelated.write"])])
    with pytest.raises(ActionDeniedError):
        await agent.call_tool("unrelated")
    assert calls == []
