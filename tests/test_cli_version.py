import pytest

from protolink.__version__ import __version__
from protolink.cli import main as cli_main


def test_cli_version_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli_main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"protolink {__version__}\n"
