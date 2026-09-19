"""Opt-in process execution. The local backend runs on the host, without isolation."""

from __future__ import annotations

import asyncio
import codecs
import math
import os
import shutil
import signal
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from protolink.core.actions import RunAction
from protolink.core.artifact import Artifact
from protolink.core.execution import ToolExecution
from protolink.core.part import Part
from protolink.core.run_context import RunContext
from protolink.tools.prepared import PreparedTool


@dataclass(frozen=True)
class ProcessSpec:
    """Exact command, explicit environment, and limits approved for a backend.

    Environment inheritance is never implicit. Pass a copied environment mapping
    explicitly when inheritance is desired. ``max_output_bytes`` caps combined
    stdout/stderr bytes retained and emitted; excess output is drained/discarded.
    """

    argv: tuple[str, ...]
    cwd: str
    env: dict[str, str]
    timeout_seconds: float = 60.0
    max_output_bytes: int = 65536


@dataclass(frozen=True)
class ProcessResult:
    """Bounded UTF-8 output (replacement decoding) and process termination facts."""

    exit_code: int | None
    stdout: str
    stderr: str
    truncated: bool
    timed_out: bool
    canceled: bool
    duration_seconds: float
    budget_exceeded: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize the result for task parts, events, and reports."""
        return asdict(self)


class ProcessCancelledError(asyncio.CancelledError):
    """Native cancellation retaining a typed result after process cleanup."""

    def __init__(self, result: ProcessResult) -> None:
        """Keep partial output accessible while preserving cancellation semantics."""
        super().__init__("Process execution canceled")
        self.result = result


class ExecutionBackend(Protocol):
    """Small extension point for host, container, or remote process execution."""

    boundary: str

    async def execute(self, spec: ProcessSpec, execution: ToolExecution) -> ProcessResult:
        """Execute the approved specification, respecting live limits and cancellation."""
        ...


class LocalExecutionBackend:
    """Execute on the host with an explicit environment and no implicit shell.

    POSIX children get a new session; its process group is terminated on every
    exit, timeout, or cancellation. Descendants that create their own session can
    escape this cleanup. On Windows only the immediate child is terminated.
    Neither behavior is a sandbox or a boundary against hostile host processes.
    """

    boundary = "host process; no sandbox or filesystem/network isolation"

    async def execute(self, spec: ProcessSpec, execution: ToolExecution) -> ProcessResult:
        """Launch a process, drain both pipes, and reap it before returning."""
        execution.check()
        started = time.monotonic()
        remaining = execution.remaining_seconds
        timeout = min(spec.timeout_seconds, remaining) if remaining is not None else spec.timeout_seconds
        output: dict[str, list[str]] = {"stdout": [], "stderr": []}
        used = 0
        truncated = False
        timed_out = canceled = False
        # Shield creation so cancellation cannot lose a child spawned just before
        # create_subprocess_exec returns its handle.
        launch = asyncio.create_task(
            asyncio.create_subprocess_exec(
                *spec.argv,
                cwd=spec.cwd,
                env=dict(spec.env),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
        )
        try:
            process = await asyncio.shield(launch)
        except asyncio.CancelledError:
            canceled = True
            process = await launch

        async def drain(stream: asyncio.StreamReader, channel: str) -> None:
            nonlocal used, truncated
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            while chunk := await stream.read(8192):
                kept = chunk[: max(0, spec.max_output_bytes - used)]
                used += len(kept)
                truncated |= len(kept) != len(chunk)
                text = decoder.decode(kept)
                if text:
                    output[channel].append(text)
                    await execution.emit("process.output", channel=channel, text=text)
            tail = decoder.decode(b"", final=True)
            if tail:
                output[channel].append(tail)
                await execution.emit("process.output", channel=channel, text=tail)

        assert process.stdout is not None and process.stderr is not None
        readers = [
            asyncio.create_task(drain(process.stdout, "stdout")),
            asyncio.create_task(drain(process.stderr, "stderr")),
        ]
        try:
            if canceled:
                raise asyncio.CancelledError
            async with asyncio.timeout(timeout):
                # Process.wait can wait for inherited pipes after the leader
                # exits. Observe leader termination so its descendants are
                # cleaned up promptly even when they keep those pipes open.
                while process.returncode is None:
                    await asyncio.sleep(0.01)
                self._terminate(process)
                await process.wait()
                await asyncio.gather(*readers)
        except TimeoutError:
            timed_out = True
        except asyncio.CancelledError:
            canceled = True
        finally:
            cleanup = asyncio.create_task(self._cleanup(process, readers))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                canceled = True
                await cleanup

        result = ProcessResult(
            exit_code=process.returncode,
            stdout="".join(output["stdout"]),
            stderr="".join(output["stderr"]),
            truncated=truncated,
            timed_out=timed_out,
            canceled=canceled,
            duration_seconds=time.monotonic() - started,
            budget_exceeded=timed_out and remaining is not None and remaining <= spec.timeout_seconds,
        )
        await execution.emit("process.finished", result=result.to_dict())
        if canceled:
            raise ProcessCancelledError(result)
        return result

    @staticmethod
    def _terminate(process: asyncio.subprocess.Process) -> None:
        """Signal the owned process group (or immediate Windows child)."""
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            elif process.returncode is None:
                process.kill()
        except ProcessLookupError:
            pass

    @classmethod
    async def _cleanup(cls, process: asyncio.subprocess.Process, readers: list[asyncio.Task[None]]) -> None:
        """Reap the child and close pipes if escaped descendants keep them open."""
        cls._terminate(process)
        try:
            await asyncio.wait_for(asyncio.gather(process.wait(), *readers, return_exceptions=True), timeout=1.0)
        except TimeoutError:
            # asyncio.Process exposes no public close(). Its subprocess
            # transport owns the pipes; closing it prevents escaped descendants
            # from keeping the host's descriptors alive indefinitely.
            transport = getattr(process, "_transport", None)
            if transport is not None:
                transport.close()


def _prepare_process_action(
    arguments: dict[str, Any],
    executor: ExecutionBackend,
    *,
    name: str,
    capabilities: tuple[str, ...],
    max_timeout_seconds: float,
    max_output_bytes: int,
    implicit_shell: bool = False,
) -> RunAction:
    """Resolve a bounded command and attach its exact authorization preview."""
    args = dict(arguments)
    argv = args["argv"]
    if not argv or any("\x00" in value for value in argv) or not argv[0]:
        raise ValueError("argv must contain a nonempty executable and no NUL bytes")
    directory = Path(args["cwd"]).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("cwd must be an existing directory")
    env = dict(args["env"])
    if any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or not key
        or "=" in key
        or "\x00" in key
        or "\x00" in value
        for key, value in env.items()
    ):
        raise ValueError("Invalid environment entry")
    args["env"] = env
    executable = argv[0]
    if not os.path.isabs(executable):
        if os.path.dirname(executable):
            executable = str(directory / executable)
        else:
            executable = shutil.which(executable, path=env.get("PATH", "")) or ""
    if not executable:
        raise ValueError("Executable requires an absolute path or an explicit env PATH")
    args["argv"] = [str(Path(executable).resolve(strict=True)), *argv[1:]]
    args["cwd"] = str(directory)
    duration = args.get("timeout_seconds", 60.0)
    output_limit = args.get("max_output_bytes", 65536)
    if not math.isfinite(duration) or not 0 < duration <= max_timeout_seconds:
        raise ValueError("timeout_seconds exceeds the configured execution limit")
    if isinstance(output_limit, bool) or not isinstance(output_limit, int) or not 0 <= output_limit <= max_output_bytes:
        raise ValueError("max_output_bytes exceeds the configured output limit")
    args.update(timeout_seconds=duration, max_output_bytes=output_limit)
    action = RunAction(
        kind="tool.call",
        name=name,
        payload={"arguments": args, "boundary": executor.boundary},
        capabilities=frozenset(capabilities),
    )
    preview = Artifact(
        kind="preview",
        name="Command execution",
        parts=[
            Part.json(
                {
                    **args,
                    "boundary": executor.boundary,
                    "implicit_shell": implicit_shell,
                }
            )
        ],
    )
    return action.with_artifacts([preview])


async def _execute_process(execution: ToolExecution, executor: ExecutionBackend) -> ProcessResult:
    """Execute only the resolved command retained by native authorization."""
    payload = execution.authorization.action.payload
    args = payload.get("process", payload["arguments"])
    spec = ProcessSpec(
        argv=tuple(args["argv"]),
        cwd=args["cwd"],
        env=dict(args["env"]),
        timeout_seconds=args["timeout_seconds"],
        max_output_bytes=args["max_output_bytes"],
    )
    return await executor.execute(spec, execution)


def process_tool(
    *, backend: ExecutionBackend | None = None, max_timeout_seconds: float = 300.0, max_output_bytes: int = 1048576
) -> PreparedTool:
    """Create ``execute_command`` without launching a process or inheriting secrets.

    Register on an Agent with a capability rule for ``process.execute``. The
    existing default Agent policy allows capabilities; applications requiring a
    human decision should use ``{"process.execute": "require_approval"}``.
    Factory limits are ceilings that command arguments cannot increase.
    """
    if (
        not math.isfinite(max_timeout_seconds)
        or max_timeout_seconds <= 0
        or isinstance(max_output_bytes, bool)
        or not isinstance(max_output_bytes, int)
        or max_output_bytes < 0
    ):
        raise ValueError("Process limits must be finite and positive (output may be zero)")
    executor = backend if backend is not None else LocalExecutionBackend()

    def execute_command(
        argv: list[str], cwd: str, env: dict[str, str], timeout_seconds: float = 60.0, max_output_bytes: int = 65536
    ) -> ProcessResult:
        """Execute an argument array with explicit cwd/environment and bounded output/time."""
        raise AssertionError("Signature only")

    def prepare(arguments: dict[str, Any], context: RunContext) -> RunAction:
        return _prepare_process_action(
            arguments,
            executor,
            name="execute_command",
            capabilities=("process.execute",),
            max_timeout_seconds=max_timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

    async def execute(execution: ToolExecution) -> ProcessResult:
        return await _execute_process(execution, executor)

    return PreparedTool(execute_command, prepare=prepare, execute=execute, capabilities=("process.execute",))
