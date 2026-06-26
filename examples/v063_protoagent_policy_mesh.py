"""ProtoAgent-style policy mesh using Protolink runtime actions.

This is not the full ProtoAgent app. It mirrors that architecture abstractly:

* Explorer is read-only and can only use ``workspace.read`` tools.
* Coder can write, but ``workspace.write`` requires application approval.
* Architect is the user-facing coordinator and may delegate to other agents.

The prompts are intentionally tiny; the point is to showcase tool capabilities,
``CapabilityPolicy``, ``action_builder`` previews, and approval handling.

Run it with:

    python examples/v063_protoagent_policy_mesh.py
"""

from __future__ import annotations

import asyncio
import difflib
import re
import tempfile
from pathlib import Path
from typing import Any

from protolink import (
    Agent,
    ApprovalDecision,
    ApprovalRequest,
    Artifact,
    CapabilityPolicy,
    Part,
    RunAction,
    RunContext,
    create_llm,
)

EXPLORER_SYSTEM_PROMPT = "Map workspace context with read-only tools. Keep answers cited and concise."
CODER_SYSTEM_PROMPT = "Prepare focused file changes with a diff preview before writing."
ARCHITECT_SYSTEM_PROMPT = "Coordinate Explorer for evidence and Coder for approved writes."


def safe_path(path: str, workspace: str) -> Path:
    """Resolve a path inside ``workspace`` and reject traversal attempts."""
    root = Path(workspace).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"Path escapes workspace: {path}")
    return target


def read_file(path: str, workspace: str) -> dict[str, Any]:
    """Read a UTF-8 text file and include line numbers for agent context."""
    target = safe_path(path, workspace)
    lines = target.read_text(encoding="utf-8").splitlines()
    return {
        "path": str(target.relative_to(Path(workspace).resolve())),
        "lines": [f"{index + 1:04d}: {line}" for index, line in enumerate(lines)],
    }


def list_directory(path: str, workspace: str) -> dict[str, Any]:
    """List direct children of one workspace directory."""
    target = safe_path(path, workspace)
    return {
        "path": str(target.relative_to(Path(workspace).resolve()) or "."),
        "entries": sorted(child.name + ("/" if child.is_dir() else "") for child in target.iterdir()),
    }


def search_regex(pattern: str, path: str, file_filter: str, workspace: str) -> dict[str, Any]:
    """Search workspace text files with a regular expression."""
    root = safe_path(path, workspace)
    compiled = re.compile(pattern)
    file_match = re.compile(file_filter)
    matches: list[dict[str, Any]] = []
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file() or not file_match.search(candidate.name):
            continue
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if compiled.search(line):
                matches.append(
                    {
                        "path": str(candidate.relative_to(Path(workspace).resolve())),
                        "line": line_number,
                        "text": line,
                    }
                )
    return {"matches": matches}


def get_git_status(_workspace: str) -> dict[str, Any]:
    """Return a stable placeholder for the example workspace status."""
    return {"status": "clean", "note": "Temp workspace used by the example."}


def build_context_pack(query: str, workspace: str) -> dict[str, Any]:
    """Build a tiny evidence pack for a repository question."""
    files = list_directory(".", workspace)["entries"]
    return {"query": query, "files": files[:5], "summary": "Local context pack assembled."}


def write_file(path: str, content: str, workspace: str, *, overwrite: bool = True) -> dict[str, Any]:
    """Write a UTF-8 file inside the workspace after policy approval."""
    target = safe_path(path, workspace)
    if target.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": str(target.relative_to(Path(workspace).resolve())), "bytes": len(content.encode())}


def build_diff(path: str, content: str, workspace: str, *, create: bool) -> str:
    """Create a unified-diff preview for a workspace write."""
    target = safe_path(path, workspace)
    old_text = "" if create or not target.exists() else target.read_text(encoding="utf-8")
    old_lines = old_text.splitlines(keepends=True)
    new_lines = content.splitlines(keepends=True)
    rel_path = str(target.relative_to(Path(workspace).resolve()))
    from_file = "/dev/null" if create else f"a/{rel_path}"
    to_file = f"b/{rel_path}"
    return "".join(difflib.unified_diff(old_lines, new_lines, fromfile=from_file, tofile=to_file))


def build_write_action(
    arguments: dict[str, Any],
    context: RunContext,
    workspace: str,
    *,
    create: bool,
) -> RunAction:
    """Prepare a policy-gated write action with a structured diff artifact."""
    path = str(arguments["path"])
    content_key = "content" if create else "updated_content"
    content = str(arguments[content_key])
    target = safe_path(path, workspace)
    diff = build_diff(path, content, workspace, create=create)
    artifact = Artifact(
        kind="preview",
        name=path,
        uri=target.as_uri(),
        media_type="text/x-diff",
        parts=[Part.text(diff)],
        metadata={"purpose": "approval_preview", "workspace_uri": context.workspace_uri},
    )
    action = RunAction(
        kind="workspace.create" if create else "workspace.write",
        name="create_new_file" if create else "replace_file",
        payload={"arguments": dict(arguments)},
        description=("Create" if create else "Replace") + f" {path}",
        metadata={"path": path, "workspace_uri": context.workspace_uri},
    )
    return action.with_artifacts([artifact])


async def approve_write(request: ApprovalRequest, _context: RunContext) -> ApprovalDecision:
    """Render the preview and approve deterministically for this example."""
    print("Approval required:", request.action.description)
    for artifact in request.action.artifacts:
        print("Preview artifact:", artifact.name)
        for part in artifact.parts:
            first_line = str(part.content).splitlines()[0] if str(part.content).splitlines() else ""
            print("Diff starts with:", first_line)
    return ApprovalDecision(
        approved=True,
        request_id=request.request_id,
        reason="Example auto-approval",
        decided_by="example",
    )


def create_explorer_agent(workspace: str) -> Agent:
    """Create the read-only Explorer agent."""
    agent = Agent(
        card={
            "name": "explorer",
            "description": "Read-only repository cartographer.",
            "url": "runtime://v063-explorer",
            "capabilities": {"delegation": False, "tool_calling": True, "multi_step_reasoning": True},
            "tags": ["protoagent", "context", "read-only", "coding"],
        },
        transport="runtime",
        llm=create_llm("mock", default_response="Explorer mock response"),
        system_prompt=EXPLORER_SYSTEM_PROMPT,
        policy=CapabilityPolicy({"workspace.read": "allow"}, default_effect="deny"),
        verbosity=0,
    )

    @agent.tool(name="read_file", description="Read a UTF-8 text file.", capabilities=["workspace.read"])
    def read_file_tool(path: str) -> dict[str, Any]:
        """Read one file from the workspace."""
        return read_file(path, workspace)

    @agent.tool(name="list_directory", description="List workspace files.", capabilities=["workspace.read"])
    def list_directory_tool(path: str = ".") -> dict[str, Any]:
        """List one directory from the workspace."""
        return list_directory(path, workspace)

    @agent.tool(name="search_regex", description="Search files by regex.", capabilities=["workspace.read"])
    def search_regex_tool(pattern: str, path: str = ".", file_filter: str = ".*") -> dict[str, Any]:
        """Search for matching lines in the workspace."""
        return search_regex(pattern, path, file_filter, workspace)

    @agent.tool(name="get_git_status", description="Return git status.", capabilities=["workspace.read"])
    def get_git_status_tool() -> dict[str, Any]:
        """Return workspace status."""
        return get_git_status(workspace)

    @agent.tool(
        name="build_context_pack",
        description="Build a focused evidence pack.",
        capabilities=["workspace.read"],
    )
    def build_context_pack_tool(query: str) -> dict[str, Any]:
        """Build a tiny evidence pack."""
        return build_context_pack(query, workspace)

    return agent


def create_coder_agent(workspace: str) -> Agent:
    """Create the approval-gated Coder agent."""
    agent = Agent(
        card={
            "name": "coder",
            "description": "File modification agent with approved diff previews.",
            "url": "runtime://v063-coder",
            "capabilities": {"delegation": False, "tool_calling": True, "multi_step_reasoning": True},
            "tags": ["protoagent", "diffs", "coding"],
        },
        transport="runtime",
        llm=create_llm("mock", default_response="Coder mock response"),
        system_prompt=CODER_SYSTEM_PROMPT,
        policy=CapabilityPolicy({"workspace.write": "require_approval"}, default_effect="deny"),
        approval_handler=approve_write,
        verbosity=0,
    )

    @agent.tool(
        name="generate_unified_diff",
        description="Replace a file after approval.",
        capabilities=["workspace.write"],
        action_builder=lambda arguments, context: build_write_action(
            arguments,
            context,
            workspace,
            create=False,
        ),
    )
    def generate_unified_diff(path: str, updated_content: str) -> dict[str, Any]:
        """Replace one file after Protolink authorizes the action."""
        return write_file(path, updated_content, workspace)

    @agent.tool(
        name="create_new_file",
        description="Create a new file after approval.",
        capabilities=["workspace.write"],
        action_builder=lambda arguments, context: build_write_action(
            arguments,
            context,
            workspace,
            create=True,
        ),
    )
    def create_new_file(path: str, content: str) -> dict[str, Any]:
        """Create one file after Protolink authorizes the action."""
        return write_file(path, content, workspace, overwrite=False)

    return agent


def create_architect_agent() -> Agent:
    """Create the delegating Architect coordinator."""
    return Agent(
        card={
            "name": "architect",
            "description": "User-facing coordinator for Explorer and Coder.",
            "url": "runtime://v063-architect",
            "capabilities": {"delegation": True, "tool_calling": True, "multi_step_reasoning": True},
            "tags": ["protoagent", "orchestrator", "coding"],
        },
        transport="runtime",
        llm=create_llm("mock", default_response="Architect mock response"),
        system_prompt=ARCHITECT_SYSTEM_PROMPT,
        policy=CapabilityPolicy({"agent.delegate": "allow"}, default_effect="deny"),
        verbosity=0,
    )


async def main() -> None:
    """Run the abstract Explorer/Coder/Architect policy mesh."""
    with tempfile.TemporaryDirectory(prefix="protolink-v063-policy-") as workspace:
        root = Path(workspace)
        (root / "README.md").write_text("# Demo\n\nUse Explorer for context and Coder for writes.\n", encoding="utf-8")

        explorer = create_explorer_agent(workspace)
        coder = create_coder_agent(workspace)
        architect = create_architect_agent()
        context = RunContext(
            run_id="run_v063_protoagent_policy",
            workspace_uri=root.as_uri(),
            permissions={"workspace.write": "allow"},
        )

        context_pack = await explorer.call_tool_in_context(
            "build_context_pack",
            context,
            query="How is this tiny repo structured?",
        )
        created = await coder.call_tool_in_context(
            "create_new_file",
            context,
            path="notes/plan.md",
            content="# Plan\n\nExplorer reads. Coder writes after approval.\n",
        )

        print("Architect policy allows delegation:", architect.card.capabilities.delegation)
        print("Explorer context files:", context_pack["files"])
        print("Coder write result:", created)
        print("Created content:", (root / "notes" / "plan.md").read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    asyncio.run(main())
