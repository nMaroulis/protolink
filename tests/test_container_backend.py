"""Check Docker arguments and lifecycle using an actual disposable CLI fixture."""

import asyncio
import json
import os
import sys

import pytest

from protolink import Agent
from protolink.tools import DockerExecutionBackend, process_tool
from protolink.tools.builtins.process import ProcessSpec


@pytest.fixture
def docker(tmp_path):
    executable = tmp_path / "docker-fixture"
    log = tmp_path / "commands.jsonl"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, time\n"
        "with open(os.environ['DOCKER_LOG'], 'a') as f: f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1] == 'run':\n"
        " print('x' * 500, flush=True)\n"
        " if '--hang' in sys.argv: time.sleep(30)\n"
    )
    executable.chmod(0o700)
    backend = DockerExecutionBackend(
        image="trusted@sha256:abc", workspace=tmp_path, executable=str(executable), docker_env={"DOCKER_LOG": str(log)}
    )
    return backend, log


def test_container_boundary_flags_and_outside_cwd_rejected(docker, tmp_path):
    backend, _ = docker
    argv = backend.command(ProcessSpec(("image-only-tool", "arg"), str(tmp_path), {"VISIBLE": "value"}), "safe-name")
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[argv.index("--entrypoint") + 1] == "image-only-tool"
    assert argv[argv.index("--memory-swap") + 1] == "512m"
    assert "--cap-drop=ALL" in argv and "--security-opt=no-new-privileges" in argv
    assert "--pull=never" in argv and "--read-only" in argv
    assert argv[argv.index("--mount") + 1].endswith(",readonly")
    assert "VISIBLE=value" in argv
    with pytest.raises(ValueError, match="inside"):
        backend.command(ProcessSpec(("tool",), str(tmp_path.parent), {}), "safe-name")


@pytest.mark.asyncio
@pytest.mark.parametrize("hang", [False, True])
async def test_container_result_output_limits_timeout_and_daemon_cleanup(docker, tmp_path, hang):
    backend, log = docker
    agent = Agent(name="container", tools=[process_tool(backend=backend)], verbosity=0)
    result = await agent.call_tool(
        "execute_command",
        argv=["image-only-tool", "--hang"] if hang else ["image-only-tool"],
        cwd=str(tmp_path),
        env={"VISIBLE": "value"},
        max_output_bytes=20,
        timeout_seconds=0.6 if hang else 5,
    )
    assert result.truncated and len(result.stdout) <= 20
    assert result.timed_out is hang
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(records) == 2 and records[0][0] == "run" and records[1][:2] == ["rm", "--force"]
    assert records[1][-1] == records[0][records[0].index("--name") + 1]


@pytest.mark.asyncio
async def test_canceled_container_is_removed_before_run_returns(docker, tmp_path):
    backend, log = docker
    agent = Agent(name="cancel-container", tools=[process_tool(backend=backend)], verbosity=0)
    running = asyncio.create_task(
        agent.call_tool("execute_command", argv=["tool", "--hang"], cwd=str(tmp_path), env={})
    )
    for _ in range(100):
        if log.exists():
            break
        await asyncio.sleep(0.01)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert records[-1][:2] == ["rm", "--force"]


@pytest.mark.skipif(not os.environ.get("PROTOLINK_TEST_DOCKER_IMAGE"), reason="Opt-in live Docker image required")
@pytest.mark.asyncio
async def test_live_docker_boundary_and_timeout(tmp_path):
    """Use a pre-pulled operator-selected image; never start Docker or pull images."""
    source = tmp_path / "input.txt"
    source.write_text("mounted evidence")
    names = []

    class TrackingBackend(DockerExecutionBackend):
        async def _remove(self, name):
            names.append(name)
            await super()._remove(name)

    backend = TrackingBackend(image=os.environ["PROTOLINK_TEST_DOCKER_IMAGE"], workspace=tmp_path)
    agent = Agent(name="live-container", tools=[process_tool(backend=backend)], verbosity=0)
    command = (
        "cat input.txt; id -u; ls /sys/class/net; "
        "if touch input.txt /root-write-test 2>/dev/null; then exit 42; fi; "
        "grep '^CapEff:' /proc/self/status"
    )
    result = await agent.call_tool("execute_command", argv=["/bin/sh", "-c", command], cwd=str(tmp_path), env={})
    assert result.exit_code == 0 and not result.timed_out
    assert "mounted evidence" in result.stdout
    assert "CapEff:\t0000000000000000" in result.stdout
    assert "eth0" not in result.stdout
    assert source.read_text() == "mounted evidence"
    timed = await agent.call_tool(
        "execute_command", argv=["/bin/sh", "-c", "sleep 30"], cwd=str(tmp_path), env={}, timeout_seconds=1
    )
    assert timed.timed_out
    for name in names:
        process = await asyncio.create_subprocess_exec(
            backend.executable,
            "container",
            "inspect",
            name,
            env=backend.docker_env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert await process.wait() != 0
