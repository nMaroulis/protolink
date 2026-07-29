"""Command-line utilities for bootstrapping Protolink projects.

The CLI intentionally starts small and conservative. It exposes deterministic
scaffolding commands that generate runnable source files without requiring a
network service, registry, or LLM credentials. This keeps the first developer
experience fast while preserving Protolink's standard runtime APIs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from protolink.__version__ import __version__
from protolink.devtools import (
    build_doctor_report,
    build_run_diff_view,
    build_run_replay_view,
    fetch_registry_agents,
    inspect_registry_agent,
    list_run_store_records,
)
from protolink.devtools.server import build_dashboard_snapshot, serve_dashboard
from protolink.templates import TEMPLATES
from protolink.utils.renderers.devtools import DevtoolsHtmlRenderer, DevtoolsTextRenderer


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser and command tree.

    The parser is kept separate from ``main()`` so tests can exercise command
    construction and command execution independently. Subcommands are explicit
    instead of inferred dynamically, which keeps the public CLI stable and
    makes generated help output predictable.
    """
    parser = argparse.ArgumentParser(
        prog="protolink",
        description="Developer utilities for Protolink projects.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create starter files.")
    init_subparsers = init_parser.add_subparsers(dest="kind", required=True)

    agent_parser = init_subparsers.add_parser("agent", help="Create a one-file starter agent.")
    agent_parser.add_argument(
        "path",
        nargs="?",
        default="agent.py",
        help="Output file path. Defaults to ./agent.py.",
    )
    agent_parser.add_argument(
        "--template",
        choices=sorted(TEMPLATES),
        default="basic",
        help="Starter template to use.",
    )
    agent_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )

    doctor_parser = subparsers.add_parser("doctor", help="Check local Protolink readiness.")
    doctor_parser.add_argument("--agent-url", help="Optional HTTP agent URL to probe.")
    doctor_parser.add_argument("--registry-url", help="Optional HTTP registry URL to probe.")
    doctor_parser.add_argument("--store", help="Optional SQLite run-store path to inspect.")
    doctor_parser.add_argument("--timeout", type=float, default=3.0, help="Probe timeout in seconds.")
    doctor_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")

    registry_parser = subparsers.add_parser("registry", help="Inspect a running registry.")
    registry_subparsers = registry_parser.add_subparsers(dest="registry_command", required=True)
    registry_list_parser = registry_subparsers.add_parser("list", help="List registered agents.")
    registry_list_parser.add_argument("--url", required=True, help="Registry base URL.")
    registry_list_parser.add_argument("--name", help="Filter by agent name.")
    registry_list_parser.add_argument("--role", help="Filter by role.")
    registry_list_parser.add_argument("--tag", action="append", default=[], help="Filter by tag. Can be repeated.")
    registry_list_parser.add_argument("--timeout", type=float, default=3.0, help="HTTP timeout in seconds.")
    registry_list_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")

    registry_inspect_parser = registry_subparsers.add_parser("inspect", help="Show one registered agent.")
    registry_inspect_parser.add_argument("selector", help="Agent name or URL.")
    registry_inspect_parser.add_argument("--url", required=True, help="Registry base URL.")
    registry_inspect_parser.add_argument("--timeout", type=float, default=3.0, help="HTTP timeout in seconds.")
    registry_inspect_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")

    run_parser = subparsers.add_parser("run", help="Inspect stored runs.")
    run_subparsers = run_parser.add_subparsers(dest="run_command", required=True)
    run_list_parser = run_subparsers.add_parser("list", help="List task snapshots and run reports.")
    run_list_parser.add_argument("--store", default="runs.db", help="SQLite run-store path.")
    run_list_parser.add_argument("--limit", type=int, default=20, help="Maximum records per section.")
    run_list_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")

    run_replay_parser = run_subparsers.add_parser("replay", help="Replay a stored run report or task snapshot.")
    run_replay_parser.add_argument("run_id", help="Run ID or task ID.")
    run_replay_parser.add_argument("--store", default="runs.db", help="SQLite run-store path.")
    run_replay_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")

    run_diff_parser = run_subparsers.add_parser(
        "diff",
        help="Compare two stored run reports after normalizing volatile fields.",
    )
    run_diff_parser.add_argument("baseline_run_id", help="Baseline run-report ID.")
    run_diff_parser.add_argument("candidate_run_id", help="Candidate run-report ID.")
    run_diff_parser.add_argument("--store", default="runs.db", help="SQLite run-store path.")
    run_diff_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")

    dashboard_parser = subparsers.add_parser("dashboard", help="Open the local Protolink dashboard.")
    dashboard_parser.add_argument("--registry-url", help="Optional HTTP registry URL.")
    dashboard_parser.add_argument(
        "--store",
        help="Optional SQLite run-store path; an existing ./runs.db is discovered automatically.",
    )
    dashboard_parser.add_argument(
        "--traces",
        "--telemetry",
        dest="traces",
        help="Optional local telemetry traces.jsonl path.",
    )
    dashboard_parser.add_argument("--host", default="127.0.0.1", help="Dashboard bind host.")
    dashboard_parser.add_argument("--port", type=int, default=8765, help="Dashboard bind port.")
    dashboard_parser.add_argument("--open", action="store_true", help="Open the dashboard in a browser.")
    dashboard_parser.add_argument("--output", help="Write a static dashboard HTML snapshot and exit.")

    return parser


def _init_agent(path: str, *, template: str, force: bool) -> int:
    """Create a starter agent source file from a bundled template.

    Args:
        path: Destination file path. Parent directories are created when
            needed.
        template: Key in ``protolink.templates.TEMPLATES`` identifying the
            starter variant to write.
        force: Whether to overwrite an existing destination file.

    Returns:
        Process-style exit code: ``0`` on success and ``1`` when overwrite
        protection prevents writing the file.
    """
    output_path = Path(path).expanduser()
    if output_path.exists() and not force:
        print(f"Refusing to overwrite existing file: {output_path}", file=sys.stderr)
        print("Use --force to overwrite it.", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(TEMPLATES[template], encoding="utf-8")
    print(f"Created {output_path}")
    return 0


def _write_text(path: str, content: str, *, label: str) -> int:
    """Write CLI-generated content to disk."""
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"Created {label}: {output_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the Protolink CLI.

    Args:
        argv: Optional argument vector for tests and embedding. When ``None``,
            ``argparse`` reads from ``sys.argv``.

    Returns:
        Integer exit code suitable for ``raise SystemExit(main())``.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "init" and args.kind == "agent":
        return _init_agent(args.path, template=args.template, force=args.force)

    text_renderer = DevtoolsTextRenderer()

    if args.command == "doctor":
        report = build_doctor_report(
            agent_url=args.agent_url,
            registry_url=args.registry_url,
            store_path=args.store,
            timeout=args.timeout,
        )
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(text_renderer.render_doctor(report))
        return 1 if report.status == "error" else 0

    if args.command == "registry" and args.registry_command == "list":
        filter_by = {"name": args.name, "role": args.role, "tags": args.tag}
        try:
            cards = fetch_registry_agents(args.url, filter_by=filter_by, timeout=args.timeout)
        except Exception as exc:
            print(f"Failed to inspect registry: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(cards, indent=2))
        else:
            print(text_renderer.render_registry_agents(cards))
        return 0

    if args.command == "registry" and args.registry_command == "inspect":
        try:
            card = inspect_registry_agent(args.url, args.selector, timeout=args.timeout)
        except Exception as exc:
            print(f"Failed to inspect registry: {exc}", file=sys.stderr)
            return 1
        if card is None:
            print(f"Agent not found: {args.selector}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(card, indent=2))
        else:
            print(text_renderer.render_registry_agents([card]))
        return 0

    if args.command == "run" and args.run_command == "list":
        records = list_run_store_records(args.store, limit=args.limit)
        if args.json:
            print(json.dumps(records, indent=2))
        else:
            print(text_renderer.render_run_list(records))
        return 0

    if args.command == "run" and args.run_command == "replay":
        view = build_run_replay_view(args.store, args.run_id)
        if args.json:
            print(json.dumps(view.to_dict(), indent=2))
        else:
            print(text_renderer.render_run_replay(view))
        return 1 if view.source == "missing" else 0

    if args.command == "run" and args.run_command == "diff":
        view = build_run_diff_view(
            args.store,
            args.baseline_run_id,
            args.candidate_run_id,
        )
        if args.json:
            print(json.dumps(view.to_dict(), indent=2))
        else:
            print(text_renderer.render_run_diff(view))
        if view.status == "missing":
            return 2
        return 0 if view.status == "match" else 1

    if args.command == "dashboard":
        html_renderer = DevtoolsHtmlRenderer()
        dashboard_store: str | Path | None = args.store
        default_store = Path("runs.db")
        if dashboard_store is None and default_store.is_file():
            dashboard_store = default_store
        if args.output:
            snapshot = build_dashboard_snapshot(
                registry_url=args.registry_url,
                store_path=dashboard_store,
                trace_path=args.traces,
            )
            return _write_text(args.output, html_renderer.render_dashboard(snapshot), label="dashboard")
        serve_dashboard(
            host=args.host,
            port=args.port,
            registry_url=args.registry_url,
            store_path=dashboard_store,
            trace_path=args.traces,
            open_browser=args.open,
        )
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
