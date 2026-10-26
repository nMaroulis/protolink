"""Embed a persistent agent team in FastAPI with private request dependencies.

Run ``python examples/application_runtime.py`` for an offline ASGI demonstration,
or ``uvicorn examples.application_runtime:create_app --factory`` to serve it.
Requires ``protolink[http]``. Mock providers script the consultations; replace
only ``model_for`` to use real providers with their native tool protocols.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Any, Literal
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from protolink import (
    Agent,
    AgentGroup,
    RunBudget,
    RunContext,
    SQLiteRunStore,
    Task,
    create_llm,
    current_request_context,
    request_context,
)
from protolink.discovery import Registry
from protolink.storage import SQLiteStorage


class RunRequest(BaseModel):
    """Validate application selections before accepting work."""

    session_id: str = Field(min_length=1)
    page: Literal["overview", "metrics"] = "overview"
    delay: float = Field(default=0.1, ge=0, le=5)


class PageService:
    """An application dependency; credentials never belong in RunContext."""

    def __init__(self) -> None:
        self.credential = "example-private-service-token"

    def read(self, page: str, *, delay: float = 0.1) -> dict[str, Any]:
        """Return only public application data, never the service credential."""
        time.sleep(delay)
        return {"page": page, "visits": 12 if page == "overview" else 7}


def read_page(delay: float = 0.1) -> dict[str, Any]:
    """Read the validated page through a blocking service call."""
    private = current_request_context()
    return private["service"].read(private["page"], delay=delay)


def total(values: list[float]) -> float:
    """Add the supplied values."""
    return sum(values)


def make_team(database: Path) -> tuple[AgentGroup, SQLiteRunStore]:
    """Declare ordinary agents; model factories run only when requests arrive."""
    suffix = uuid4().hex[:8]
    names = {role: f"{role}-{suffix}" for role in ("reader", "analyst", "coordinator")}
    store = SQLiteRunStore(database)

    def model_for(role: str):
        private = current_request_context()
        model = private["models"][role]
        if role == "reader":
            actions = [{"type": "tool_call", "tool": "read_page", "args": {"delay": private["delay"]}}]
        elif role == "analyst":
            actions = [{"type": "tool_call", "tool": "total", "args": {"values": [2, 3]}}]
        else:
            actions = [
                {"type": "agent_call", "agent": names[child], "action": "infer", "prompt": "Use your tool."}
                for child in ("reader", "analyst")
            ]
        # These final answers are scripted, not summaries generated from tool data.
        actions.append(f"{role} finished for {private['page']} using {model}.")
        return create_llm("mock", model=model, sequential_responses=actions)

    def agent(role: str, **kwargs: Any) -> Agent:
        return Agent(
            name=names[role],
            transport="runtime",
            llm_factory=lambda: model_for(role),
            system_prompt=f"You are the {role}. Use the available tools and specialists.",
            sync_execution="thread",
            max_sync_workers=2,
            expose_tool_results=True,
            state=["conversation"],
            storage=SQLiteStorage(str(database), namespace=role),
            run_store=store,
            verbosity=0,
            **kwargs,
        )

    reader = agent("reader", tools=[read_page])
    analyst = agent("analyst", tools=[total])
    coordinator = agent("coordinator", subagents=[reader, analyst])
    registry = Registry(transport="runtime", url=f"runtime://registry-{suffix}", verbosity=0)
    group = AgentGroup([reader, analyst, coordinator], registry=registry, own_registry=True)
    return group, store


def create_app(database: str | Path = "application.sqlite") -> FastAPI:
    """Own registry, readiness, active runs and shutdown in FastAPI's lifespan."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        group, store = make_team(Path(database))
        app.state.group, app.state.store = group, store
        app.state.service = PageService()
        app.state.models = {role: f"mock-{role}-v1" for role in ("reader", "analyst", "coordinator")}
        app.state.runs = {}
        async with group:
            yield

    app = FastAPI(lifespan=lifespan)

    @app.post("/runs")
    async def run(body: RunRequest):
        # Copy the whole team's choices at acceptance, before queued work starts.
        private = {
            "models": MappingProxyType(dict(app.state.models)),
            "service": app.state.service,
            "page": body.page,
            "delay": body.delay,
        }
        task = Task.create_infer(prompt="Consult both specialists about the selected page.")
        RunContext(session_id=body.session_id, budget=RunBudget(max_llm_calls=10)).attach_to_task(task)
        coordinator = next(a for a in app.state.group.agents.values() if a.subagents)
        with request_context(private, inherit=tuple(private)):
            handle = app.state.group.run(coordinator, task)
        app.state.runs[handle.context.run_id] = handle

        async def events():
            try:
                async for event in handle.events():
                    # Raw JSON action fragments belong to diagnostics. Display
                    # llm_final content as answer text; all activity stays typed.
                    if event.payload.get("llm_event_type") != "llm_chunk":
                        yield json.dumps(event.to_dict()) + "\n"
            finally:
                await handle.cancel("Client disconnected")
                await handle.result()
                app.state.runs.pop(handle.context.run_id, None)

        return StreamingResponse(
            events(), media_type="application/x-ndjson", headers={"X-Run-ID": handle.context.run_id}
        )

    @app.delete("/runs/{run_id}")
    async def cancel(run_id: str):
        handle = app.state.runs.get(run_id)
        if handle is None:
            raise HTTPException(404, "No active run with this ID")
        await handle.cancel("Application requested cancellation")
        return {"status": (await handle.result()).status}

    @app.get("/runs/{run_id}/evidence")
    async def evidence(run_id: str):
        report = app.state.store.get_report(run_id)
        if report is None:
            raise HTTPException(404, "No saved report with this ID")
        return [item.to_dict() for item in report.tool_evidence]

    return app


async def main() -> None:
    """Exercise the app without paid providers or listening network sockets."""
    with TemporaryDirectory() as directory:
        app = create_app(Path(directory) / "application.sqlite")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://example") as client:
                responses = await asyncio.gather(
                    client.post("/runs", json={"session_id": "alice", "page": "overview"}),
                    client.post("/runs", json={"session_id": "bob", "page": "metrics"}),
                )
                for response in responses:
                    response.raise_for_status()
                    run_id = response.headers["X-Run-ID"]
                    evidence = await client.get(f"/runs/{run_id}/evidence")
                    print(run_id, evidence.json())


if __name__ == "__main__":
    asyncio.run(main())
