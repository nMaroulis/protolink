"""Developer tooling helpers for Protolink.

The devtools package powers the ``protolink`` CLI inspection commands and the
local dashboard. It intentionally depends on Protolink's public runtime
contracts rather than private agent internals, so applications can reuse the
collectors and renderers in their own CLIs or notebooks.
"""

from .doctor import build_doctor_report
from .models import CheckResult, DoctorReport, RunReplayItem, RunReplayView
from .registry import fetch_registry_agents, inspect_registry_agent
from .runs import build_run_replay_view, list_run_store_records

__all__ = [
    "CheckResult",
    "DoctorReport",
    "RunReplayItem",
    "RunReplayView",
    "build_doctor_report",
    "build_run_replay_view",
    "fetch_registry_agents",
    "inspect_registry_agent",
    "list_run_store_records",
]
