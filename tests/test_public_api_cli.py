from pathlib import Path

from protolink import Agent, AgentCard, LocalTraceRecorder, LocalTraceTelemetry, Pipeline, Task, Tool, create_llm
from protolink.cli import main as cli_main


def test_top_level_happy_path_exports():
    assert Agent is not None
    assert AgentCard is not None
    assert LocalTraceRecorder is not None
    assert LocalTraceTelemetry is not None
    assert Pipeline is not None
    assert Task is not None
    assert Tool is not None
    assert create_llm("mock", default_response="ok").provider == "mock"


def test_cli_init_agent_creates_template(tmp_path: Path):
    target = tmp_path / "agent.py"

    assert cli_main(["init", "agent", str(target)]) == 0
    content = target.read_text(encoding="utf-8")

    assert "from protolink import Agent" in content
    assert "LocalTraceTelemetry" in content
    assert "Task.create_tool_call" in content

    assert cli_main(["init", "agent", str(target)]) == 1

    assert cli_main(["init", "agent", str(target), "--template", "tool", "--force"]) == 0
    assert "Tool-first Protolink agent starter" in target.read_text(encoding="utf-8")
