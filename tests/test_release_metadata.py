"""Keep the published package, lockfiles, and documentation on one release."""

import json
import re
from pathlib import Path

import tomllib

from protolink import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_release_versions_match() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    docs = json.loads((ROOT / "docs/package.json").read_text(encoding="utf-8"))
    docs_lock = json.loads((ROOT / "docs/package-lock.json").read_text(encoding="utf-8"))

    assert project["project"]["version"] == __version__
    assert docs["version"] == docs_lock["version"] == docs_lock["packages"][""]["version"] == __version__
    assert f"Documentation version: **{__version__}**" in (ROOT / "docs/content/index.md").read_text(encoding="utf-8")
    changelog = (ROOT / "docs/content/changelog.md").read_text(encoding="utf-8")
    assert re.search(rf"^## \[{re.escape(__version__)}\] - .+$", changelog, re.MULTILINE)


def test_ruff_version_matches_precommit() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = project["project"]["optional-dependencies"]["test"]
    ruff = next(requirement for requirement in requirements if requirement.startswith("ruff=="))
    version = ruff.removeprefix("ruff==")

    assert f"rev: v{version}" in (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
