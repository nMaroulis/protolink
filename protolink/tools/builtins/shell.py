"""Application-configured shell commands using the native process boundary."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

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

_Command = Annotated[
    str, Field(min_length=1, max_length=65536, description="Shell script, including pipes or redirects.")
]


def shell_tool(
    *,
    cwd: str | Path,
    env: Mapping[str, str] | None = None,
    shell: str = "/bin/sh",
    timeout_seconds: float = 60.0,
    max_output_bytes: int = 65536,
    backend: ExecutionBackend | None = None,
) -> PreparedTool:
    """Create ``run_shell(command)`` with application-owned execution settings.

    Each call starts a fresh noninteractive shell: ``cd``, variables, and other
    shell state do not persist. Scripts may use pipelines and redirections.
    Output and termination facts are returned as ``ProcessResult``; nonzero
    exits and timeouts are results, not exceptions. Requires ``process.execute``
    and ``shell.execute`` through an Agent, with an exact command preview.

    Args:
        cwd: Existing working directory, resolved once at registration.
        env: Complete child environment, copied at registration. ``None`` uses
            only ``PATH=os.defpath``; parent credentials are never inherited.
        shell: POSIX-compatible shell executable accepting ``-c`` (default
            ``/bin/sh``). Windows requires an installed compatible shell.
        timeout_seconds: Positive finite wall-time limit for each command,
            further bounded by the active run's remaining runtime budget.
        max_output_bytes: Nonnegative cap on combined stdout/stderr bytes.
        backend: Optional trusted execution backend; defaults to host execution.

    Returns:
        A fresh prepared tool accepting only a ``command`` string. Configuration
        and backend objects must be reattached after loading Agent dict/YAML.

    Raises:
        ValueError: Limits or environment entries are invalid.
        OSError: The directory or executable cannot be resolved.

    The local backend is not a sandbox. A configured cwd does not restrict file
    or network access. Use policy approval or an isolated backend as appropriate
    for the application. Registering the factory launches no process.
    """
    executor = backend if backend is not None else LocalExecutionBackend()
    settings = {
        "argv": [shell, "-c", ":"],
        "cwd": str(cwd),
        "env": dict(env) if env is not None else {"PATH": os.defpath},
        "timeout_seconds": timeout_seconds,
        "max_output_bytes": max_output_bytes,
    }
    capabilities = ("process.execute", "shell.execute")
    configured = _prepare_process_action(
        settings,
        executor,
        name="run_shell",
        capabilities=capabilities,
        max_timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        implicit_shell=True,
    ).payload["arguments"]

    def run_shell(command: _Command) -> ProcessResult:
        """Run a shell script in the configured directory. Return bounded output and exit status.

        Commands run in a fresh noninteractive shell; pipes and redirects are supported.
        No shell state persists between calls. Check exit_code and timed_out before continuing.
        """
        raise AssertionError("Signature only")

    def prepare(arguments: dict[str, Any], context: RunContext) -> RunAction:
        command = arguments["command"]
        if not command.strip():
            raise ValueError("command must not be blank")
        action = _prepare_process_action(
            {**configured, "argv": [configured["argv"][0], "-c", command]},
            executor,
            name="run_shell",
            capabilities=capabilities,
            max_timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            implicit_shell=True,
        )

        return action.with_payload(
            {**action.payload, "arguments": dict(arguments), "process": action.payload["arguments"]}
        )

    async def execute(execution: ToolExecution) -> ProcessResult:
        return await _execute_process(execution, executor)

    tool = PreparedTool(run_shell, prepare=prepare, execute=execute, capabilities=capabilities)
    tool.tags = ["builtin", "shell", "execution"]
    tool.examples = [{"command": "printf 'hello\\n' | sort"}]
    return tool
