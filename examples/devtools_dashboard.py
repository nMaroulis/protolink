"""Generate a local Protolink dashboard demo.

Run from the repository root:

    .venv/bin/python examples/devtools_dashboard.py

By default the demo writes to a temporary directory. Pass ``--output-dir`` to keep the generated dashboard HTML and
SQLite run store in a project-local path.

The example is provider-free. It creates a few mock-LLM agents, registers their agent cards in an in-process registry,
runs a small task loop, persists task snapshots and run reports, and renders a dashboard snapshot that users can open
or serve with ``protolink dashboard``.

The generated registry uses ``RuntimeTransport`` so it stays provider-free and does not bind ports. The dashboard's ping
and chat controls become active when the served dashboard points at a running HTTP registry with HTTP agent URLs. The
embedded Studio project uses the public, provider-free starter blueprint and the same catalog as the served dashboard.
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path
from typing import Any, Literal

from protolink import Agent, AgentCard, RunContext, RunRecorder, SQLiteRunStore, Task, create_llm
from protolink.core.agent_card import AgentCapabilities
from protolink.devtools import default_studio_blueprint, studio_catalog
from protolink.devtools.server import serve_dashboard
from protolink.discovery import Registry
from protolink.transport import HTTPTransport, RuntimeTransport
from protolink.types import AgentRoleType
from protolink.utils.renderers.devtools import DevtoolsHtmlRenderer


async def main(
    output_dir: Path,
    *,
    serve_live: bool = False,
    host: str = "127.0.0.1",
    dashboard_port: int = 8877,
    registry_port: int = 9017,
    agent_base_port: int = 8117,
) -> None:
    """Create a dashboard-ready registry snapshot and persisted run store."""
    output_dir.mkdir(parents=True, exist_ok=True)
    store_path = output_dir / "runs.db"
    dashboard_path = output_dir / "dashboard.html"

    run_store = SQLiteRunStore(store_path)
    registry_url = f"http://{host}:{registry_port}" if serve_live else "runtime://dashboard-demo-registry"
    registry = (
        Registry(url=registry_url, transport="http", verbosity=0)
        if serve_live
        else Registry(transport=RuntimeTransport(url=registry_url), verbosity=0)
    )
    agents = _build_agents(
        run_store,
        transport="http" if serve_live else "runtime",
        host=host,
        agent_base_port=agent_base_port,
    )
    started_agents: list[Agent] = []

    try:
        if serve_live:
            registry.start(background=True)
            for agent in agents:
                agent.start(background=True)
                started_agents.append(agent)
            await asyncio.sleep(0.8)

        for agent in agents:
            await registry.handle_register(agent.card)

        await _run_task_loop(agents, run_store)
        registry_agents: list[dict[str, Any]] = []
        for card in await registry.handle_discover(as_json=True):
            registry_agents.append(dict(card) if isinstance(card, dict) else card.to_dict())

        snapshot = _build_snapshot(store_path, run_store, registry_url=registry_url, registry_agents=registry_agents)
        dashboard_path.write_text(DevtoolsHtmlRenderer().render_dashboard(snapshot), encoding="utf-8")

        print(f"Run store: {store_path}")
        print(f"Dashboard HTML: {dashboard_path}")
        print()
        print("Try:")
        print(f"  protolink run list --store {store_path}")
        print(f"  protolink run replay dashboard_demo_1 --store {store_path}")
        if serve_live:
            print(f"  protolink dashboard --store {store_path} --registry-url {registry_url} --open")
            print()
            print(f"Live registry: {registry_url}")
            print(f"Live dashboard: http://{host}:{dashboard_port}")
            print(f"Live Studio: http://{host}:{dashboard_port}/studio")
            print("Press Ctrl-C to stop the demo agents, registry, dashboard, and any Studio project.")
            serve_dashboard(host=host, port=dashboard_port, registry_url=registry_url, store_path=store_path)
        else:
            print(f"  protolink dashboard --store {store_path} --open")
            print(f"  python examples/devtools_dashboard.py --output-dir {output_dir} --serve-live")
            print()
            print("Note: the static dashboard HTML includes the demo registry snapshot.")
            print("Note: static Studio supports visual editing and JSON import/export.")
            print("Note: serve the dashboard to generate Python or use Studio Run/Stop.")
            print("Note: live ping/chat actions require HTTP agents from --registry-url.")
    finally:
        for agent in started_agents:
            agent.stop()
        if serve_live:
            registry.stop()


def _build_agents(
    run_store: SQLiteRunStore,
    *,
    transport: Literal["http", "runtime"],
    host: str,
    agent_base_port: int,
) -> list[Agent]:
    """Create the provider-free agents used by the dashboard demo."""
    agent_specs: list[tuple[str, str, AgentRoleType, list[str], str]] = [
        (
            "planner_agent",
            "Plans task routing for a small autonomous team.",
            "orchestrator",
            ["planning", "routing"],
            "Plan accepted. Next step: route work to research and writing agents.",
        ),
        (
            "research_agent",
            "Collects concise facts for downstream agents.",
            "worker",
            ["research", "retrieval"],
            "Research summary ready. Key facts are structured for handoff.",
        ),
        (
            "writer_agent",
            "Turns task context into a final user-facing answer.",
            "worker",
            ["writing", "summary"],
            "Final response drafted from the collected context.",
        ),
    ]

    agents: list[Agent] = []
    for offset, (name, description, role, tags, response) in enumerate(agent_specs):
        url = f"http://{host}:{agent_base_port + offset}" if transport == "http" else f"runtime://dashboard-demo/{name}"
        agent_transport = HTTPTransport(url=url) if transport == "http" else None
        agents.append(
            Agent(
                AgentCard(
                    name=name,
                    description=description,
                    url=url,
                    transport=transport,
                    role=role,
                    tags=tags,
                    capabilities=AgentCapabilities(streaming=True, has_llm=True),
                ),
                transport=agent_transport,
                llm=create_llm("mock", default_response=response),
                run_store=run_store,
                verbosity=0,
            )
        )
    return agents


def _build_snapshot(
    store_path: Path,
    run_store: SQLiteRunStore,
    *,
    registry_url: str,
    registry_agents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a dashboard snapshot for the demo run store and registry."""
    return {
        "registry": {"url": registry_url, "agents": registry_agents, "error": None},
        "runs": {
            "store": str(store_path),
            "tasks": [record.to_dict() for record in run_store.list_task_records(limit=20)],
            "reports": [record.to_dict() for record in run_store.list_report_records(limit=20)],
            "error": None,
        },
        "studio": {
            "blueprint": default_studio_blueprint(),
            "catalog": studio_catalog(),
        },
    }


async def _run_task_loop(agents: list[Agent], run_store: SQLiteRunStore) -> None:
    """Run a small sequence of tasks and persist replayable reports."""
    prompts = [
        "Plan the work for a dashboard demo.",
        "Gather facts about run replay and registry inspection.",
        "Summarize the dashboard demo for a new Protolink user.",
        "Plan a follow-up task using the previous outputs.",
        "Collect one more concise runtime observation.",
        "Write the final dashboard status update.",
    ]

    for index, prompt in enumerate(prompts, start=1):
        agent = agents[(index - 1) % len(agents)]
        task = Task.create_infer(prompt=prompt)
        context = RunContext(
            run_id=f"dashboard_demo_{index}",
            session_id="dashboard_demo_session",
            trace_id="dashboard_demo_trace",
            agent_chain=["dashboard_demo", agent.card.name],
        )
        context.attach_to_task(task)

        recorder = RunRecorder(context=context)
        async for event in agent.handle_task_streaming(task):
            await recorder.record_task_event(event)

        run_store.save_task(task, context=context, agent_name=agent.card.name, metadata={"example": "dashboard"})
        report = recorder.to_report(final_task=task.to_dict(), metadata={"example": "dashboard", "step": index})
        run_store.save_report(report, agent_name=agent.card.name, metadata={"example": "dashboard"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a provider-free Protolink dashboard demo.")
    parser.add_argument(
        "--output-dir",
        default=str(Path(tempfile.gettempdir()) / "protolink-dashboard-demo"),
        help="Directory for generated files.",
    )
    parser.add_argument(
        "--serve-live",
        action="store_true",
        help="Start HTTP demo agents, a registry, and the dashboard so ping/chat actions are clickable.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host used for live demo services.")
    parser.add_argument("--dashboard-port", type=int, default=8877, help="Dashboard port for --serve-live.")
    parser.add_argument("--registry-port", type=int, default=9017, help="Registry port for --serve-live.")
    parser.add_argument("--agent-base-port", type=int, default=8117, help="First agent port for --serve-live.")
    args = parser.parse_args()
    asyncio.run(
        main(
            Path(args.output_dir),
            serve_live=args.serve_live,
            host=args.host,
            dashboard_port=args.dashboard_port,
            registry_port=args.registry_port,
            agent_base_port=args.agent_base_port,
        )
    )
