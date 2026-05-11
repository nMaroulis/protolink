"""
Coder Agent — The "Hands" of the Coding Assistant (Tools-Only)

This agent is the file system interface. It exposes deterministic tools for
reading, writing, listing, and searching files — no LLM needed.

═══════════════════════════════════════════════════════════════════════════
PROTOLINK CONCEPTS DEMONSTRATED:
─────────────────────────────────
1. TOOL-ONLY AGENT: An agent with no LLM attached. It's a pure "worker"
   that executes tools reliably and deterministically.
2. @agent.tool DECORATOR: Turn any Python function into a discoverable,
   callable tool that other agents can invoke via `agent_call`.
3. INPUT SCHEMAS: Define typed input schemas so the Orchestrator's LLM
   knows exactly what arguments each tool expects.

WHY A SEPARATE AGENT?
─────────────────────
In a real coding assistant (like Claude Code), file operations are
isolated from reasoning. The "brain" decides WHAT to do; the "hands"
do it. This separation means:
  • The Planner agent can reason without filesystem access (safer)
  • The Coder agent can execute without hallucinating (deterministic)
  • The Orchestrator coordinates the two via Protolink's agent_call
═══════════════════════════════════════════════════════════════════════════
"""

import fnmatch
import os

from protolink.agents import Agent
from protolink.discovery import Registry

# ---------------------------------------------------------------------------
# Safety: All file operations are sandboxed to WORKSPACE_DIR.
# This prevents the agent from accessing files outside the project.
# ---------------------------------------------------------------------------
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", os.path.join(os.path.dirname(__file__), "workspace"))


def _safe_path(path: str) -> str:
    """Resolve a path and ensure it's within the workspace sandbox.

    This is critical for security — we never want an AI agent to
    read or write arbitrary files on the host machine.
    """
    # Resolve relative paths against the workspace
    if not os.path.isabs(path):
        full_path = os.path.abspath(os.path.join(WORKSPACE_DIR, path))
    else:
        full_path = os.path.abspath(path)

    # Security check: must be within workspace
    if not full_path.startswith(os.path.abspath(WORKSPACE_DIR)):
        raise ValueError(
            f"Access denied: '{path}' is outside the workspace. All operations are sandboxed to: {WORKSPACE_DIR}"
        )
    return full_path


def create_coder_agent(registry: Registry | None = None) -> Agent:
    """
    Create and configure the Coder Agent.

    The Coder Agent is a TOOL-ONLY agent — it has no LLM attached.
    It exposes four filesystem tools that other agents can invoke
    via Protolink's `agent_call` with action `tool_call`.

    Parameters
    ----------
    registry : Registry, optional
        The agent registry for discovery. When provided, this agent
        registers itself so the Orchestrator can discover and call it.
    """

    # ─── Create the Agent ─────────────────────────────────────────────
    # Notice: NO `llm` parameter! This is a pure tool agent.
    # Protolink agents don't need an LLM to be useful — they can
    # serve as reliable, deterministic workers in the mesh.
    # ──────────────────────────────────────────────────────────────────
    agent = Agent(
        card={
            "name": "coder",
            "description": (
                "File system operations agent. Reads, writes, lists, and searches "
                "project files. Use this agent for all file interactions."
            ),
            "url": os.getenv("CODER_AGENT_URL", "http://localhost:8030"),
        },
        transport="http",
        registry=registry,
    )

    # ══════════════════════════════════════════════════════════════════
    # TOOL 1: read_file
    # ──────────────────────────────────────────────────────────────────
    # The @agent.tool decorator registers this function as a Protolink
    # Tool. When another agent calls:
    #   agent_call → coder.read_file(path="utils.py")
    # Protolink routes the request over HTTP, executes this function,
    # and returns the result — all automatically.
    # ══════════════════════════════════════════════════════════════════
    @agent.tool(
        name="read_file",
        description="Read the contents of a file. Returns the file content as a string with line numbers.",
        # input_schema={"path": str} # Input schema is automatically inferred from the function signature and typehints
    )
    def read_file(path: str) -> dict:
        """Read a file from the workspace and return its contents with line numbers."""
        print(f"\n   📖 [coder] read_file: {path}")

        safe = _safe_path(path)

        if not os.path.exists(safe):
            return {"success": False, "error": f"File not found: {path}"}

        if not os.path.isfile(safe):
            return {"success": False, "error": f"Not a file: {path}"}

        with open(safe) as f:
            lines = f.readlines()

        # Format with line numbers (useful for the Planner to reference specific lines)
        numbered = "".join(f"{i + 1:4d} | {line}" for i, line in enumerate(lines))
        print(f"   📖 [coder] → Read {len(lines)} lines from {path}")

        return {
            "success": True,
            "path": path,
            "content": numbered,
            "raw_content": "".join(lines),
            "line_count": len(lines),
        }

    # ══════════════════════════════════════════════════════════════════
    # TOOL 2: write_file
    # ──────────────────────────────────────────────────────────────────
    # This tool writes (or overwrites) a file. The Orchestrator calls
    # this after the Planner generates the new file content.
    # ══════════════════════════════════════════════════════════════════
    @agent.tool(
        name="write_file",
        description="Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
        input_schema={"path": str, "content": str},
    )
    def write_file(path: str, content: str) -> dict:
        """Write content to a file in the workspace."""
        print(f"\n   ✍️  [coder] write_file: {path}")

        safe = _safe_path(path)

        # Create parent directories if needed
        os.makedirs(os.path.dirname(safe), exist_ok=True)

        with open(safe, "w") as f:
            f.write(content)

        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        print(f"   ✍️  [coder] → Wrote {line_count} lines to {path}")

        return {
            "success": True,
            "path": path,
            "lines_written": line_count,
            "message": f"Successfully wrote {line_count} lines to {path}",
        }

    # ══════════════════════════════════════════════════════════════════
    # TOOL 3: list_directory
    # ──────────────────────────────────────────────────────────────────
    # Lists directory contents. Essential for workspace exploration.
    # ══════════════════════════════════════════════════════════════════
    @agent.tool(
        name="list_directory",
        description="List the contents of a directory. Returns files and subdirectories with their types and sizes.",
        input_schema={"path": str},
    )
    def list_directory(path: str = ".") -> dict:
        """List contents of a directory in the workspace."""
        print(f"\n   📁 [coder] list_directory: {path}")

        safe = _safe_path(path)

        if not os.path.exists(safe):
            return {"success": False, "error": f"Directory not found: {path}"}

        if not os.path.isdir(safe):
            return {"success": False, "error": f"Not a directory: {path}"}

        entries = []
        for name in sorted(os.listdir(safe)):
            # Skip hidden files and __pycache__
            if name.startswith(".") or name == "__pycache__":
                continue
            entry_path = os.path.join(safe, name)
            entry = {
                "name": name,
                "type": "directory" if os.path.isdir(entry_path) else "file",
            }
            if os.path.isfile(entry_path):
                entry["size_bytes"] = os.path.getsize(entry_path)
            entries.append(entry)

        print(f"   📁 [coder] → Found {len(entries)} entries in {path}")

        return {
            "success": True,
            "path": path,
            "entries": entries,
            "count": len(entries),
        }

    # ══════════════════════════════════════════════════════════════════
    # TOOL 4: search_in_files
    # ──────────────────────────────────────────════════════════════════
    # Grep-like search across files. Crucial for understanding a
    # codebase before making changes.
    # ══════════════════════════════════════════════════════════════════
    @agent.tool(
        name="search_in_files",
        description=(
            "Search for a text pattern across files in a directory. "
            "Returns matching lines with file paths and line numbers. "
            "Optionally filter by file extension (e.g., '*.py')."
        ),
        input_schema={"pattern": str, "path": str, "file_filter": str},
    )
    def search_in_files(pattern: str, path: str = ".", file_filter: str = "*") -> dict:
        """Search for a pattern across workspace files."""
        print(f"\n   🔍 [coder] search_in_files: '{pattern}' in {path} (filter: {file_filter})")

        safe = _safe_path(path)

        if not os.path.exists(safe):
            return {"success": False, "error": f"Path not found: {path}"}

        matches = []
        files_searched = 0

        # Walk the directory tree
        if os.path.isfile(safe):
            files_to_search = [(os.path.dirname(safe), [], [os.path.basename(safe)])]
        else:
            files_to_search = os.walk(safe)

        for root, _dirs, files in files_to_search:
            for filename in files:
                # Apply file filter
                if not fnmatch.fnmatch(filename, file_filter):
                    continue
                # Skip binary-looking files
                if filename.endswith((".pyc", ".pyo", ".so", ".o", ".class")):
                    continue

                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, WORKSPACE_DIR)
                files_searched += 1

                try:
                    with open(filepath) as f:
                        for line_num, line in enumerate(f, 1):
                            if pattern.lower() in line.lower():
                                matches.append(
                                    {
                                        "file": rel_path,
                                        "line": line_num,
                                        "content": line.rstrip(),
                                    }
                                )
                except (UnicodeDecodeError, PermissionError):
                    continue  # Skip binary/unreadable files

        print(f"   🔍 [coder] → {len(matches)} matches in {files_searched} files")

        return {
            "success": True,
            "pattern": pattern,
            "matches": matches[:50],  # Cap results to avoid huge payloads
            "total_matches": len(matches),
            "files_searched": files_searched,
        }

    return agent


# ---------------------------------------------------------------------------
# Standalone execution (for distributed deployment)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from protolink.discovery import Registry

    registry = Registry(
        url=os.getenv("REGISTRY_URL", "http://localhost:9000"),
        transport="http",
    )
    agent = create_coder_agent(registry)
    print(f"Coder Agent running at {agent.card.url}")
    print("Press Ctrl+C to stop")
    try:
        agent.start()
    except KeyboardInterrupt:
        agent.stop()
