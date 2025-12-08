# Transports

Protolink supports multiple transports for agent communication.

## Supported Transports

- **HTTPTransport**
  - Uses HTTP/HTTPS for synchronous requests.
  - Backed by ASGI frameworks such as `starlette`/`httpx`/`uvicorn` or `fastapi`/`pydantic`/`uvicorn`.
  - Good default choice for web‑based agents and simple deployments.

- **WebSocketTransport**
  - Uses WebSocket for streaming requests and responses.
  - Built on top of libraries like `websockets` (and `httpx` for HTTP parts where applicable).
  - Useful when you need real‑time, bidirectional communication or token‑level streaming.

- **JSONRPCTransport** (TBD)
  - Planned JSON‑RPC based transport.
  - Intended for structured, RPC‑style interactions.

- **GRPCTransport** (TBD)
  - Planned gRPC transport.
  - Intended for high‑performance, strongly‑typed communication.

- **RuntimeTransport**
  - Simple **in‑process, in‑memory transport**.
  - Allows multiple agents to communicate within the same Python process.
  - Ideal for local development, testing, and tightly‑coupled agent systems.

## Choosing a Transport

Some rough guidelines:

- Use **RuntimeTransport** for local experiments, tests, or when all agents live in the same process.
- Use **HTTPTransport** when you want a simple, interoperable API surface (e.g. calling agents from other services or frontends).
- Use **WebSocketTransport** when you need streaming and interactive sessions.
- Plan for **JSONRPCTransport** or **GRPCTransport** if you need stricter schemas or higher performance across services.

