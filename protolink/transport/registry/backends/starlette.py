import asyncio
from typing import Any

from protolink.models import AgentCard
from protolink.transport._deps import _require_starlette
from protolink.transport.registry.backends.base import RegistryBackendInterface


class StarletteRegistryBackend(RegistryBackendInterface):
    def __init__(self) -> None:
        from starlette.applications import Starlette

        self.app = Starlette()
        self._server_task: asyncio.Task | None = None
        self._server_instance: Any = None

    def setup_routes(self, transport: "HTTPRegistryTransport") -> None:  # noqa: F821
        """Register all HTTP routes on the Starlette application.

        This method wires the public HTTP API to the internal Registry transport handlers.
        Each route is registered via a dedicated helper for clarity and separation of concerns.
        """
        self._setup_register_routes(transport)
        self._setup_unregister_routes(transport)
        self._setup_discover_routes(transport)
        self._setup_status_routes(transport)

    def _setup_register_routes(self, transport: "HTTPRegistryTransport") -> None:  # noqa: F821
        """Register `/agents/` POST endpoint."""

        _, Request, JSONResponse, _ = _require_starlette()  # noqa: N806

        @self.app.route("/agents/", methods=["POST"])
        async def register_agent(request: Request) -> JSONResponse:
            if not transport._register_handler:
                raise RuntimeError("No register handler registered")

            card = AgentCard.from_json(await request.json())
            await transport._register_handler(card)
            return JSONResponse({"status": "registered"})

    def _setup_unregister_routes(self, transport: "HTTPRegistryTransport") -> None:  # noqa: F821
        """Register `/agents/` DELETE endpoint."""

        _, Request, JSONResponse, _ = _require_starlette()  # noqa: N806

        @self.app.route("/agents/", methods=["DELETE"])
        async def unregister_agent(request: Request) -> JSONResponse:
            if not transport._unregister_handler:
                raise RuntimeError("No unregister handler registered")

            agent_url = request.query_params.get("agent_url")
            if not agent_url:
                return JSONResponse({"error": "agent_url required"}, status_code=400)

            await transport._unregister_handler(agent_url)
            return JSONResponse({"status": "unregistered"})

    def _setup_discover_routes(self, transport: "HTTPRegistryTransport") -> None:  # noqa: F821
        """Register `/agents/` POST endpoint."""

        _, Request, JSONResponse, _ = _require_starlette()  # noqa: N806

        @self.app.route("/agents/", methods=["GET"])
        async def discover_agents(request: Request) -> JSONResponse:
            if not transport._discover_handler:
                raise RuntimeError("No register handler registered")

            filter_by = dict(request.query_params)
            cards = await transport._discover_handler(filter_by)
            return JSONResponse([c.to_json() for c in cards])

    def _setup_status_routes(self, transport: "HTTPRegistryTransport") -> None:  # noqa: F821
        """Register Registry status endpoint.

        GET /status returns registry status.
        """

        _, Request, _, HTMLResponse = _require_starlette()  # noqa: N806

        @self.app.route("/status", methods=["GET"])
        async def get_status(request: Request) -> HTMLResponse:
            if not transport._status_handler:
                raise RuntimeError("No status handler registered")

            result = transport._status_handler()
            return HTMLResponse(result)

    # ----------------------------------------------------------------------
    # ASGI Server Lifecycle
    # ----------------------------------------------------------------------

    async def start(self, host: str, port: int) -> None:
        import uvicorn

        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)

        self._server_instance = server
        self._server_task = asyncio.create_task(server.serve())

        while not server.started:
            await asyncio.sleep(0.02)

    async def stop(self) -> None:
        if self._server_instance:
            self._server_instance.should_exit = True

        if self._server_task:
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            finally:
                self._server_task = None
                self._server_instance = None
