"""Generate a local Protolink dashboard demo.

Run from the repository root:

    .venv/bin/python examples/devtools_dashboard.py

By default the demo writes to a temporary directory. Pass ``--output-dir`` to
keep the generated dashboard HTML and SQLite run store in a project-local path.

The example is provider-free. It creates a few mock-LLM agents, registers their
agent cards in an in-process registry, runs a small task loop, persists task
snapshots and run reports, and renders a dashboard snapshot that users can open
or serve with ``protolink dashboard``.
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

from protolink import Agent, AgentCard, RunContext, RunRecorder, SQLiteRunStore, Task, create_llm
from protolink.core.agent_card import AgentCapabilities
from protolink.discovery import Registry
from protolink.transport import RuntimeTransport
from protolink.types import AgentRoleType
from protolink.utils.renderers.devtools import DevtoolsHtmlRenderer


async def main(output_dir: Path) -> None:
    """Create a dashboard-ready registry snapshot and persisted run store."""
    output_dir.mkdir(parents=True, exist_ok=True)
    store_path = output_dir / "runs.db"
    dashboard_path = output_dir / "dashboard.html"

    run_store = SQLiteRunStore(store_path)
    registry = Registry(transport=RuntimeTransport(url="runtime://dashboard-demo-registry"), verbosity=0)
    agents = _build_agents(run_store)

    for agent in agents:
        await registry.handle_register(agent.card)

    await _run_task_loop(agents, run_store)
    registry_agents = await registry.handle_discover(as_json=True)

    snapshot = {
        "registry": {"url": "runtime://dashboard-demo-registry", "agents": registry_agents, "error": None},
        "runs": {
            "store": str(store_path),
            "tasks": [record.to_dict() for record in run_store.list_task_records(limit=20)],
            "reports": [record.to_dict() for record in run_store.list_report_records(limit=20)],
            "error": None,
        },
        "studio": {
            "blueprint": {
                "nodes": [
                    {"id": "planner", "kind": "agent", "label": "planner_agent", "x": 90, "y": 120},
                    {"id": "researcher", "kind": "agent", "label": "research_agent", "x": 330, "y": 80},
                    {"id": "writer", "kind": "agent", "label": "writer_agent", "x": 330, "y": 220},
                    {"id": "registry", "kind": "registry", "label": "runtime registry", "x": 580, "y": 150},
                ],
                "edges": [
                    {"from": "planner", "to": "researcher"},
                    {"from": "planner", "to": "writer"},
                    {"from": "researcher", "to": "registry"},
                    {"from": "writer", "to": "registry"},
                ],
            }
        },
    }
    dashboard_path.write_text(DevtoolsHtmlRenderer().render_dashboard(snapshot), encoding="utf-8")

    print(f"Run store: {store_path}")
    print(f"Dashboard HTML: {dashboard_path}")
    print()
    print("Try:")
    print(f"  protolink run list --store {store_path}")
    print(f"  protolink run replay dashboard_demo_1 --store {store_path}")
    print(f"  protolink dashboard --store {store_path} --open")
    print()
    print("Note: the static dashboard HTML includes the demo registry snapshot.")


def _build_agents(run_store: SQLiteRunStore) -> list[Agent]:
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
    for name, description, role, tags, response in agent_specs:
        agents.append(
            Agent(
                AgentCard(
                    name=name,
                    description=description,
                    url=f"runtime://dashboard-demo/{name}",
                    transport="runtime",
                    role=role,
                    tags=tags,
                    capabilities=AgentCapabilities(streaming=True, has_llm=True),
                ),
                llm=create_llm("mock", default_response=response),
                run_store=run_store,
                verbosity=0,
            )
        )
    return agents


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
    args = parser.parse_args()
    asyncio.run(main(Path(args.output_dir)))
