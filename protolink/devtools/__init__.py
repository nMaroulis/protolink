"""Developer tooling helpers for Protolink.

The devtools package powers the ``protolink`` CLI inspection commands and the local dashboard. It intentionally depends
on Protolink's public runtime contracts rather than private agent internals, so applications can reuse the collectors
and renderers in their own CLIs or notebooks.
"""

from .agents import chat_with_agent, ping_agent
from .doctor import build_doctor_report
from .models import CheckResult, DoctorReport, RunDiffView, RunReplayItem, RunReplayView
from .registry import fetch_registry_agents, inspect_registry_agent
from .runs import build_run_diff_view, build_run_replay_view, list_run_store_records
from .traces import TraceJsonlReader, list_trace_records, load_trace_record

__all__ = [
    "CheckResult",
    "DoctorReport",
    "RunDiffView",
    "RunReplayItem",
    "RunReplayView",
    "TraceJsonlReader",
    "build_doctor_report",
    "build_run_diff_view",
    "build_run_replay_view",
    "chat_with_agent",
    "fetch_registry_agents",
    "inspect_registry_agent",
    "list_run_store_records",
    "list_trace_records",
    "load_trace_record",
    "ping_agent",
]
