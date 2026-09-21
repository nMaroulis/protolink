"""Structured local Git operations with bounded output and explicit write access."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

from protolink.core.actions import RunAction
from protolink.core.execution import ToolExecution
from protolink.core.run_context import RunContext
from protolink.tools.builtins.process import (
    ExecutionBackend,
    LocalExecutionBackend,
    ProcessResult,
    _execute_process,
    _prepare_process_action,
)
from protolink.tools.prepared import PreparedTool

GitOperation = Literal["status", "diff", "log", "show", "add", "commit"]
"""Local Git operations exposed to models; remote and destructive commands are absent."""

_Paths = Annotated[
    list[str] | None,
    Field(description="Literal paths relative to the configured directory. Required for add; omitted means all paths."),
]
_Revision = Annotated[str | None, Field(description="Revision for diff, log, or show. Defaults to HEAD for log/show.")]
_Count = Annotated[int, Field(ge=1, le=100, description="Maximum commits returned by log (1-100).")]


def git_tool(
    *,
    cwd: str | Path,
    allow_write: bool = False,
    env: Mapping[str, str] | None = None,
    executable: str = "git",
    timeout_seconds: float = 60.0,
    max_output_bytes: int = 65536,
    backend: ExecutionBackend | None = None,
) -> PreparedTool:
    """Create ``git(operation, ...)`` for one application-selected directory.

    Read operations are ``status``, ``diff``, ``log``, and ``show``. Set
    ``allow_write=True`` to expose ``add`` and ``commit``. Every operation needs
    ``process.execute`` plus ``git.read`` or ``git.write``; write permission in
    the factory does not override Agent policy. Commands never use a shell.

    Args:
        cwd: Existing directory in a repository, resolved at registration.
        allow_write: Enable staging explicit paths and committing the index.
            Commits include ALL staged changes, including preexisting ones.
        env: Complete copied environment; ``None`` supplies only a system PATH.
            Supply author/committer variables explicitly when needed. Git's
            system/global config, terminal prompts, and optional locks are
            disabled regardless of this mapping; local repo config still applies.
        executable: Git executable, absolute or resolved using the configured PATH.
        timeout_seconds: Positive finite command limit, bounded by run budgets.
        max_output_bytes: Nonnegative combined stdout/stderr byte limit.
        backend: Trusted process backend; defaults to the local host.

    Returns:
        A fresh prepared tool returning ``ProcessResult``. Nonzero exit codes,
        including missing repositories/revisions, are results, not exceptions.
        Reattach configuration/backend after restoring Agent dict/YAML.

    Raises:
        ValueError: Invalid configuration, options, paths, or disabled writes.
        OSError: The configured directory or executable cannot be resolved.

    Hooks, fsmonitor, signing, external diff, and textconv are disabled. Git
    attributes/clean filters may still execute code during staging; this is host
    execution, not isolation for untrusted repositories. Mutation is not
    automatically rolled back. Registration never runs Git.
    """
    executor = backend if backend is not None else LocalExecutionBackend()
    environment = dict(env) if env is not None else {"PATH": os.defpath}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    settings = {
        "argv": [executable],
        "cwd": str(cwd),
        "env": environment,
        "timeout_seconds": timeout_seconds,
        "max_output_bytes": max_output_bytes,
    }
    configured = _prepare_process_action(
        settings,
        executor,
        name="git",
        capabilities=("process.execute",),
        max_timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
    ).payload["arguments"]

    def git(
        operation: GitOperation,
        *,
        paths: _Paths = None,
        revision: _Revision = None,
        staged: bool = False,
        message: str | None = None,
        max_count: _Count = 10,
    ) -> ProcessResult:
        """Inspect a local repository or explicitly stage/commit changes.

        status: short branch/status output, optionally filtered by paths.
        diff: working-tree changes, or staged=True for index changes; optional revision and paths.
        log: recent commits, with optional revision, paths, and max_count.
        show: one revision (default HEAD), with optional paths.
        add: stage the explicit nonempty paths list, including deletions.
        commit: commit ALL staged changes with the required message.
        Check exit_code, timed_out, and truncated in the result before continuing.
        """
        raise AssertionError("Signature only")

    def prepare(arguments: dict[str, Any], context: RunContext) -> RunAction:
        operation = arguments["operation"]
        paths = arguments.get("paths")
        revision = arguments.get("revision")
        staged = arguments.get("staged", False)
        message = arguments.get("message")
        max_count = arguments.get("max_count", 10)
        if operation in {"add", "commit"} and not allow_write:
            raise ValueError("Git writes require git_tool(allow_write=True)")
        if paths is not None:
            if not paths or operation == "commit":
                raise ValueError("paths must be nonempty and are not accepted by commit")
            for path in paths:
                if not path or "\x00" in path or Path(path).is_absolute() or ".." in Path(path).parts:
                    raise ValueError("paths must be literal relative paths without '..' or NUL bytes")
        if revision is not None:
            if operation not in {"diff", "log", "show"} or not revision.strip() or revision.startswith("-"):
                raise ValueError("revision must be a non-option revision for diff, log, or show")
        if staged and operation != "diff":
            raise ValueError("staged is only supported by diff")
        if max_count != 10 and operation != "log":
            raise ValueError("max_count is only supported by log")
        if message is not None and operation != "commit":
            raise ValueError("message is only supported by commit")

        argv = [
            configured["argv"][0],
            "--no-pager",
            "--literal-pathspecs",
            "-c",
            "color.ui=false",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "maintenance.auto=false",
            "-c",
            "gc.auto=0",
            operation,
        ]
        if operation == "status":
            argv += ["--short", "--branch", "--untracked-files=normal"]
        elif operation in {"diff", "show"}:
            argv += ["--no-ext-diff", "--no-textconv"]
            if staged:
                argv += ["--cached"]
            if revision is not None or operation == "show":
                argv += [revision if revision is not None else "HEAD"]
        elif operation == "log":
            argv += [f"--max-count={max_count}", "--format=medium", revision if revision is not None else "HEAD"]
        elif operation == "add":
            if not paths:
                raise ValueError("add requires explicit nonempty paths")
        elif operation == "commit":
            if message is None or not message.strip():
                raise ValueError("commit requires a nonempty message")
            argv += ["--no-gpg-sign", "--no-verify", "-m", message]
        # Always terminate revision/option parsing, including when no paths are supplied.
        argv += ["--", *(paths or [])]
        capability = "git.write" if operation in {"add", "commit"} else "git.read"
        action = _prepare_process_action(
            {**configured, "argv": argv},
            executor,
            name="git",
            capabilities=("process.execute", capability),
            max_timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

        return action.with_payload(
            {**action.payload, "arguments": dict(arguments), "process": action.payload["arguments"]}
        )

    async def execute(execution: ToolExecution) -> ProcessResult:
        return await _execute_process(execution, executor)

    tool = PreparedTool(git, prepare=prepare, execute=execute, capabilities=("process.execute",))
    if not allow_write:
        assert tool.input_schema is not None
        tool.input_schema["properties"]["operation"]["enum"] = ["status", "diff", "log", "show"]
    tool.tags = ["builtin", "git", "execution"]
    tool.examples = [{"operation": "status"}, {"operation": "diff", "staged": True}]
    return tool
