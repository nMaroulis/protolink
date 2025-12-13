import asyncio
from typing import Any

from protolink.models import AgentCard
from protolink.transport.registry.backends.base import RegistryBackendInterface


class StarletteRegistryBackend(RegistryBackendInterface):
    def __init__(self) -> None:
        from starlette.applications import Starlette

        self.app = Starlette()
        self._server_task: asyncio.Task | None = None
        self._server_instance: Any = None

    def setup_routes(self, transport: "HTTPRegistryTransport") -> None:  # noqa: F821
        from starlette.requests import Request
        from starlette.responses import JSONResponse

        @self.app.route("/agents/", methods=["POST"])
        async def register_agent(request: Request):
            card = AgentCard.from_json(await request.json())
            await transport._register_local(card)
            return JSONResponse({"status": "registered"})

        @self.app.route("/agents/", methods=["DELETE"])
        async def unregister_agent(request: Request):
            agent_url = request.query_params.get("agent_url")
            if not agent_url:
                return JSONResponse({"error": "agent_url required"}, status_code=400)

            await transport._unregister_local(agent_url)
            return JSONResponse({"status": "unregistered"})

        @self.app.route("/agents/", methods=["GET"])
        async def discover_agents(request: Request):
            filter_by = dict(request.query_params)
            cards = await transport._discover_local(filter_by)
            return JSONResponse([c.to_json() for c in cards])

        @self.app.route("/.well-known/registry.json", methods=["GET"])
        async def registry_metadata(_: Request):
            return JSONResponse(
                {
                    "type": "protolink-registry",
                    "version": "0.1.0",
                }
            )

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
