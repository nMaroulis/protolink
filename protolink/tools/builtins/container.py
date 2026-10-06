"""Optional Docker process isolation through the existing ExecutionBackend contract."""

from __future__ import annotations

import asyncio
import math
import os
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from protolink.core.execution import ToolExecution
from protolink.tools.builtins.process import LocalExecutionBackend, ProcessResult, ProcessSpec


class DockerExecutionBackend:
    """Run approved commands in disposable containers with explicit resources.

    The caller supplies an existing workspace and a trusted, already-pulled image
    (prefer a digest). Only that directory is mounted, read-only unless writable
    is enabled. Network defaults to none, root filesystem is read-only, privileges
    and Linux capabilities are disabled and CPU/memory/PID limits are explicit.
    Tool argv[0] resolves inside the image; remaining arguments and
    cwd retain their approved values. Images must contain the configured tools.

    Requires the Docker CLI/daemon but no Python extra. Docker is a trusted local
    execution service, not a guarantee against hostile kernel/daemon exploits.
    Normal exit, timeout and cancellation force-remove the named container.
    Abrupt application death can leave daemon work requiring external inspection;
    durable uncertain effects are never automatically replayed.
    """

    def __init__(
        self,
        *,
        image: str,
        workspace: str | Path,
        writable: bool = False,
        network: bool = False,
        memory_mb: int = 512,
        cpus: float = 1.0,
        pids_limit: int = 128,
        user: str | None = None,
        executable: str = "docker",
        docker_env: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(image, str) or not image or image.startswith("-") or any(char.isspace() for char in image):
            raise ValueError("image must be a nonblank Docker image reference")
        self.workspace = Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir() or "," in str(self.workspace):
            raise ValueError("workspace must be an existing directory without commas")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (memory_mb, pids_limit)):
            raise ValueError("memory_mb and pids_limit must be positive integers")
        if isinstance(cpus, bool) or not math.isfinite(cpus) or cpus <= 0:
            raise ValueError("cpus must be finite and positive")
        self.user = user or (f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") and os.getuid() else "65534:65534")
        if not re.fullmatch(r"[1-9][0-9]*(?::[0-9]+)?", self.user):
            raise ValueError("user must be an explicit non-root numeric UID with optional GID")
        resolved = shutil.which(executable)
        if resolved is None:
            raise FileNotFoundError("Docker CLI not found; install Docker or configure executable")
        self.executable = str(Path(resolved).resolve())
        self.image, self.writable, self.network = image, writable, network
        self.memory_mb, self.cpus, self.pids_limit = memory_mb, cpus, pids_limit
        self.docker_env = dict(docker_env) if docker_env is not None else {"PATH": os.defpath}
        if any(
            not isinstance(key, str) or not isinstance(value, str) or not key or "=" in key or "\x00" in key + value
            for key, value in self.docker_env.items()
        ):
            raise ValueError("docker_env must contain NUL-free string keys and values")
        self.boundary = (
            f"Docker image {image}; workspace {self.workspace}; writable={writable}; network={network}; "
            f"user={self.user}; memory={memory_mb}MiB; cpus={cpus}; pids={pids_limit}"
        )

    def command(self, spec: ProcessSpec, name: str) -> tuple[str, ...]:
        """Build an argument array, accepting only approved cwd inside the mounted workspace."""
        directory = Path(spec.cwd).resolve(strict=True)
        if not directory.is_relative_to(self.workspace):
            raise ValueError("Container cwd must be inside the configured workspace")
        mount = f"type=bind,source={self.workspace},target={self.workspace}" + ("" if self.writable else ",readonly")
        argv = [
            self.executable,
            "run",
            "--rm",
            "--pull=never",
            "--name",
            name,
            "--read-only",
            "--no-healthcheck",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--network",
            "bridge" if self.network else "none",
            "--user",
            self.user,
            "--memory",
            f"{self.memory_mb}m",
            "--memory-swap",
            f"{self.memory_mb}m",
            "--cpus",
            str(self.cpus),
            "--pids-limit",
            str(self.pids_limit),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--mount",
            mount,
            "--workdir",
            str(directory),
        ]
        for key, value in spec.env.items():
            argv.extend(["--env", f"{key}={value}"])
        argv.extend(["--entrypoint", spec.argv[0], self.image, *spec.argv[1:]])
        return tuple(argv)

    def resolve_executable(self, executable: str, *, cwd: str, env: Mapping[str, str]) -> str:
        """Retain the approved container executable instead of resolving it on the host.

        Absolute paths refer to the container filesystem; names resolve on the
        image's PATH. Relative paths containing a slash resolve against mounted
        cwd. The image and mount are declared in the authorization boundary.
        """
        return executable

    async def execute(self, spec: ProcessSpec, execution: ToolExecution) -> ProcessResult:
        """Use bounded native pipe draining and remove daemon-side work before returning."""
        execution.check()
        name = f"protolink-{uuid4().hex}"
        await execution.emit("container.requested", name=name, image=self.image)
        wrapped = ProcessSpec(
            self.command(spec, name), str(self.workspace), self.docker_env, spec.timeout_seconds, spec.max_output_bytes
        )
        try:
            return await LocalExecutionBackend().execute(wrapped, execution)
        finally:
            cleanup = asyncio.create_task(self._remove(name))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    async def _remove(self, name: str) -> None:
        """Bound cleanup independently so cancellation cannot orphan a live container."""
        process = await asyncio.create_subprocess_exec(
            self.executable,
            "rm",
            "--force",
            name,
            env=self.docker_env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(10):
                _, error = await process.communicate()
                if process.returncode and b"No such container" not in error:
                    raise RuntimeError(
                        f"Container cleanup could not be confirmed; inspect {name}: "
                        f"{error[:1000].decode(errors='replace')}"
                    )
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
