"""Real host operations and live feedback through the native Agent boundary."""

import asyncio
import json
import os
import shutil
import subprocess

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
from protolink.tools import ask_user_tool, git_tool, shell_tool


def make_agent(*tools, **kwargs):
    agent = Agent(
        AgentCard(name="assistant-tools", description="test", url="runtime://assistant-tools"), verbosity=0, **kwargs
    )
    for tool in tools:
        agent.add_tool(tool)
    return agent


@pytest.fixture
def repository(tmp_path):
    if not shutil.which("git"):
        pytest.skip("Git executable is required")
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, env={"PATH": os.defpath})
    return tmp_path


GIT_ENV = {
    "PATH": os.defpath,
    "GIT_AUTHOR_NAME": "Example",
    "GIT_AUTHOR_EMAIL": "example@example.test",
    "GIT_COMMITTER_NAME": "Example",
    "GIT_COMMITTER_EMAIL": "example@example.test",
}


@pytest.mark.asyncio
async def test_shell_pipeline_environment_preview_and_nonpersistent_state(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_FROM_PARENT", "must-not-inherit")
    previews = []

    async def approve(request, context):
        previews.append(request.action)
        return True

    env = {"PATH": os.defpath, "EXPLICIT": "yes"}
    agent = make_agent(
        shell_tool(cwd=tmp_path, env=env),
        policy=CapabilityPolicy({"shell.execute": "require_approval"}),
        approval_handler=approve,
    )
    env["EXPLICIT"] = "mutated"
    command = 'printf \'%s:%s\\n\' "$EXPLICIT" "$SECRET_FROM_PARENT" | cat > note; cat note; export TRANSIENT=x'
    result = await agent.call_tool("run_shell", command=command)
    assert result.exit_code == 0 and result.stdout == "yes:\n"
    assert (tmp_path / "note").read_text() == "yes:\n"
    preview = previews[0].artifacts[0].parts[0].content
    assert preview["argv"][-1] == command and preview["implicit_shell"] is True
    assert previews[0].capabilities == {"process.execute", "shell.execute"}
    result = await agent.call_tool("run_shell", command="printf '%s' \"$TRANSIENT\"")
    assert result.stdout == ""


@pytest.mark.asyncio
async def test_shell_limits_denial_and_cancellation(tmp_path):
    agent = make_agent(shell_tool(cwd=tmp_path, timeout_seconds=0.05, max_output_bytes=7))
    result = await agent.call_tool("run_shell", command="printf '123456789'; printf 'error' >&2; exit 9")
    assert result.exit_code == 9 and result.truncated
    assert len(result.stdout) + len(result.stderr) == 7
    result = await agent.call_tool("run_shell", command="sleep 5")
    assert result.timed_out
    denied = make_agent(shell_tool(cwd=tmp_path), policy=CapabilityPolicy({"shell.execute": "deny"}))
    with pytest.raises(ActionDeniedError):
        await denied.call_tool("run_shell", command="touch forbidden")
    assert not (tmp_path / "forbidden").exists()
    tool = shell_tool(cwd=tmp_path)
    with pytest.raises(RuntimeError, match="authorization"):
        await tool(command="true")
    handle = RunHandle.start(
        make_agent(tool),
        Task.create_tool_call(tool_name="run_shell", args={"command": "printf 'ready'; sleep 10; touch leaked"}),
    )
    async for event in handle.events():
        if event.type == "process.output":
            await handle.cancel()
    assert (await handle.result()).status == "canceled"
    assert not (tmp_path / "leaked").exists()


@pytest.mark.parametrize(
    "settings",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": float("inf")},
        {"max_output_bytes": -1},
        {"max_output_bytes": 1.5},
        {"env": {"BAD=KEY": "x"}},
    ],
)
def test_command_factory_rejects_invalid_settings(tmp_path, settings):
    with pytest.raises(ValueError):
        shell_tool(cwd=tmp_path, **settings)
    with pytest.raises(ValueError):
        git_tool(cwd=tmp_path, **settings)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["", "  ", "echo\x00bad"])
async def test_invalid_shell_scripts(tmp_path, command):
    with pytest.raises(ValueError):
        await make_agent(shell_tool(cwd=tmp_path)).call_tool("run_shell", command=command)


@pytest.mark.asyncio
async def test_git_all_operations_literal_paths_and_policy(repository):
    previews = []

    async def approve(request, context):
        previews.append(request.action)
        return True

    agent = make_agent(
        git_tool(cwd=repository, env=GIT_ENV, allow_write=True),
        policy=CapabilityPolicy({"git.write": "require_approval"}),
        approval_handler=approve,
    )
    # Leading dashes and pathspec magic must be literal filenames.
    filename = ":(glob)*"
    (repository / filename).write_text("first\n")
    (repository / "untouched").write_text("must stay untracked")
    status = await agent.call_tool("git", operation="status")
    assert "untouched" in status.stdout
    added = await agent.call_tool("git", operation="add", paths=[filename])
    assert added.exit_code == 0
    diff = await agent.call_tool("git", operation="diff", staged=True)
    assert "+first" in diff.stdout and "must stay untracked" not in diff.stdout
    commit = await agent.call_tool("git", operation="commit", message="Initial commit")
    assert commit.exit_code == 0, commit.stderr
    log = await agent.call_tool("git", operation="log", max_count=1)
    assert "Initial commit" in log.stdout
    shown = await agent.call_tool("git", operation="show", revision="HEAD", paths=[filename])
    assert "+first" in shown.stdout
    (repository / filename).write_text("second\n")
    diff = await agent.call_tool("git", operation="diff", paths=[filename])
    assert "+second" in diff.stdout
    assert len(previews) == 2
    assert all(action.capabilities == {"process.execute", "git.write"} for action in previews)
    readonly = make_agent(git_tool(cwd=repository))
    with pytest.raises(ValueError):
        await readonly.call_tool("git", operation="add", paths=["untouched"])
    denied = make_agent(git_tool(cwd=repository, allow_write=True), policy=CapabilityPolicy({"git.write": "deny"}))
    with pytest.raises(ActionDeniedError):
        await denied.call_tool("git", operation="add", paths=["untouched"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    [
        {"operation": "push"},
        {"operation": "show", "revision": "--output=bad"},
        {"operation": "diff", "paths": ["../outside"]},
        {"operation": "add"},
        {"operation": "commit", "message": "  "},
        {"operation": "status", "staged": True},
        {"operation": "log", "max_count": 101},
        {"operation": "status", "message": "unexpected"},
    ],
)
async def test_git_rejects_unsupported_or_ambiguous_arguments(repository, args):
    with pytest.raises(ValueError):
        await make_agent(git_tool(cwd=repository, allow_write=True)).call_tool("git", **args)


@pytest.mark.asyncio
async def test_git_disables_hooks_fsmonitor_external_diff_and_textconv(repository):
    def git(*args):
        subprocess.run(["git", "-C", str(repository), *args], check=True, env=GIT_ENV, capture_output=True)

    hook = repository / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\ntouch hook-ran\nexit 1\n")
    hook.chmod(0o700)
    git("config", "core.fsmonitor", "touch fsmonitor-ran")
    git("config", "diff.external", "touch diff-ran")
    git("config", "diff.test.textconv", "touch textconv-ran")
    (repository / ".gitattributes").write_text("*.txt diff=test\n")
    (repository / "note.txt").write_text("before\n")
    agent = make_agent(git_tool(cwd=repository, allow_write=True, env=GIT_ENV))
    await agent.call_tool("git", operation="status")
    await agent.call_tool("git", operation="add", paths=["note.txt", ".gitattributes"])
    result = await agent.call_tool("git", operation="commit", message="No hooks")
    assert result.exit_code == 0, result.stderr
    (repository / "note.txt").write_text("after\n")
    result = await agent.call_tool("git", operation="diff")
    assert "+after" in result.stdout
    await agent.call_tool("git", operation="show")
    assert not any(repository.glob("*-ran"))


@pytest.mark.asyncio
async def test_user_feedback_reaches_next_model_step_with_live_events():
    asked = asyncio.Event()
    answer_ready = asyncio.Event()
    seen = []

    async def handler(request):
        seen.append(request)
        asked.set()
        await answer_ready.wait()
        return "A custom answer"

    calls = []

    def model(history, system_prompt):
        calls.append(list(history.messages))
        if len(calls) == 1:
            return {"type": "tool_call", "tool": "ask_user", "args": {"question": "Which?", "options": ["A", "B"]}}
        return {"type": "final", "content": "Continued with the user's answer"}

    agent = make_agent(ask_user_tool(handler), llm=create_llm("mock", response_callback=model))
    handle = RunHandle.start(agent, Task.create_infer(prompt="Ask before proceeding"))
    await asyncio.wait_for(asked.wait(), 2)
    assert len(calls) == 1
    async for event in handle.events():
        if event.type == "user_input.requested":
            break
    answer_ready.set()
    result = await asyncio.wait_for(handle.result(), 2)
    assert result.status == "completed"
    assert "A custom answer" in json.dumps(calls[1])
    assert seen[0].task_id == result.task.id
    assert seen[0].options == ("A", "B")
    types = [e.type for e in result.report.events]
    assert types.index("user_input.requested") < types.index("user_input.answered")


@pytest.mark.asyncio
async def test_user_timeout_decline_concurrency_and_cleanup():
    cleaned = []

    async def waiting(request):
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.append(request.request_id)

    agent = make_agent(ask_user_tool(waiting, timeout_seconds=0.02))
    results = await asyncio.gather(*(agent.call_tool("ask_user", question=q) for q in ("One?", "Two?")))
    assert all(r.status == "timed_out" and r.answer is None for r in results)
    assert len(set(cleaned)) == 2
    assert {r.request_id for r in results} == set(cleaned)

    async def decline(request):
        return None

    result = await make_agent(ask_user_tool(decline)).call_tool("ask_user", question="Continue?")
    assert result.status == "declined" and result.answer is None


@pytest.mark.asyncio
async def test_user_cancellation_budget_and_denial():
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def handler(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    agent = make_agent(ask_user_tool(handler))
    handle = RunHandle.start(agent, Task.create_tool_call(tool_name="ask_user", args={"question": "Wait?"}))
    await asyncio.wait_for(started.wait(), 2)
    await handle.cancel()
    assert (await asyncio.wait_for(handle.result(), 2)).status == "canceled"
    assert cleaned.is_set()
    assert any(e.type == "user_input.canceled" for e in handle.report.events)
    context = RunContext(budget=RunBudget(max_runtime_seconds=0.02))
    with pytest.raises(BudgetExceededError):
        await agent.call_tool_in_context("ask_user", context, question="Budget?")
    started.clear()
    denied = make_agent(ask_user_tool(handler), policy=CapabilityPolicy({"user.interact": "deny"}))
    with pytest.raises(ActionDeniedError):
        await denied.call_tool("ask_user", question="Never shown")
    assert not started.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["", "   ", 42, "x" * 11])
async def test_invalid_user_answers(answer):
    async def handler(request):
        return answer

    with pytest.raises(ValueError, match="answer"):
        await make_agent(ask_user_tool(handler, max_answer_chars=10)).call_tool("ask_user", question="Hello?")


@pytest.mark.asyncio
async def test_callback_timeout_is_not_mistaken_for_user_timeout():
    async def handler(request):
        raise TimeoutError("UI service failed")

    with pytest.raises(TimeoutError, match="UI service"):
        await make_agent(ask_user_tool(handler)).call_tool("ask_user", question="Hello?")
