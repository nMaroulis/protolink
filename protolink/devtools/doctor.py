"""Readiness checks for the ``protolink doctor`` command."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from protolink.__version__ import __version__
from protolink.devtools.models import CheckResult, DoctorReport


def build_doctor_report(
    *,
    agent_url: str | None = None,
    registry_url: str | None = None,
    store_path: str | Path | None = None,
    timeout: float = 3.0,
) -> DoctorReport:
    """Build a local development readiness report.

    Args:
        agent_url: Optional agent URL to probe through ``/.well-known/agent.json``.
        registry_url: Optional registry URL to probe through ``/agents/``.
        store_path: Optional SQLite run-store path to inspect.
        timeout: Network probe timeout in seconds.

    Returns:
        A structured ``DoctorReport`` suitable for text or JSON rendering.
    """
    checks: list[CheckResult] = [
        CheckResult("protolink", "ok", f"version {__version__}"),
        *_optional_dependency_checks(),
    ]

    if store_path is not None:
        checks.append(_check_run_store(Path(store_path)))
    if agent_url:
        checks.append(_probe_json_endpoint("agent", agent_url.rstrip("/") + "/.well-known/agent.json", timeout))
    if registry_url:
        checks.append(_probe_json_endpoint("registry", registry_url.rstrip("/") + "/agents/", timeout))

    return DoctorReport(tuple(checks))


def _optional_dependency_checks() -> list[CheckResult]:
    """Return optional dependency availability checks."""
    groups = {
        "http extra": ("httpx", "starlette", "websockets"),
        "llm api extras": ("openai", "anthropic"),
        "metrics extra": ("tiktoken",),
        "telemetry extras": ("langfuse", "langsmith"),
    }
    checks: list[CheckResult] = []
    for group, modules in groups.items():
        missing = [module for module in modules if importlib.util.find_spec(module) is None]
        if missing:
            checks.append(
                CheckResult(
                    group,
                    "warn",
                    "missing optional modules: " + ", ".join(missing),
                    metadata={"missing": missing},
                )
            )
        else:
            checks.append(CheckResult(group, "ok", "available", metadata={"modules": list(modules)}))
    return checks


def _check_run_store(path: Path) -> CheckResult:
    """Inspect whether a SQLite run store is readable and has expected tables."""
    if not path.exists():
        return CheckResult("run store", "warn", f"{path} does not exist yet")

    try:
        with sqlite3.connect(str(path)) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND (name LIKE '%run%' OR name LIKE '%task%')"
            ).fetchall()
    except sqlite3.Error as exc:
        return CheckResult("run store", "error", f"failed to read {path}: {exc}")

    tables = sorted(str(row[0]) for row in rows)
    if not tables:
        return CheckResult("run store", "warn", f"{path} is readable but no Protolink tables were found")
    return CheckResult("run store", "ok", f"{path} contains {len(tables)} candidate table(s)", {"tables": tables})


def _probe_json_endpoint(name: str, url: str, timeout: float) -> CheckResult:
    """Probe an HTTP JSON endpoint without adding optional client dependencies."""
    if not url.startswith(("http://", "https://")):
        return CheckResult(name, "warn", f"skipped non-HTTP URL: {url}")

    try:
        request = Request(url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status_code = getattr(response, "status", 200)
        payload: Any = json.loads(raw.decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return CheckResult(name, "error", f"failed to probe {url}: {exc}")

    detail = f"HTTP {status_code}, JSON {type(payload).__name__}"
    metadata = {"url": url, "status_code": status_code}
    if isinstance(payload, list):
        metadata["items"] = len(payload)
    elif isinstance(payload, dict):
        metadata["keys"] = sorted(str(key) for key in payload)
    return CheckResult(name, "ok", detail, metadata)
