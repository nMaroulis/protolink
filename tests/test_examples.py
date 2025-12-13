import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES_TO_SKIP = ["__init__.py", "http_agents.py", "llms.py", "registry.py", "streaming_agent.py"]
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
example_scripts = [str(p) for p in EXAMPLES_DIR.glob("*.py") if p.name not in EXAMPLES_TO_SKIP]


@pytest.mark.parametrize("script", example_scripts, ids=lambda x: Path(x).name)
def test_example_scripts(script):
    """Test that example scripts run without errors."""
    with open(script) as f:
        content = f.read()
        # TODO(): maybe skip this line
        if 'if __name__ == "__main__":' not in content:
            pytest.skip(f"Skipping {script}: no main guard found")
    result = subprocess.run(
        [sys.executable, script],
        cwd=EXAMPLES_DIR,
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Check for errors
    assert result.returncode == 0, (
        f"Script {script} failed with return code {result.returncode}\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
