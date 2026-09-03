# Basic Example: One Complete Multi-Agent Notebook

Open [`basic_example.ipynb`](basic_example.ipynb) for a detailed introduction built around short, direct ProtoLink calls. Start a `Registry`, then WeatherAgent, then AlertAgent; discover peers, call tools, invoke agents, and explore the HTTP pages and APIs.

Both agents are ordinary `Agent` instances with tools, instructions, and an LLM; AlertAgent also enables conversation state. There is no `handle_task` override. The default HTTP transport, `MockLLM`, and small weather tool need no API key, model server, or external weather service. The alert tool returns demonstration output without sending an external notification.

## Quick Start

From the repository root, install the notebook and HTTP dependencies, then launch Jupyter:

```bash
python -m pip install -e '.[http,notebook]'
python -m jupyter lab examples/notebooks/basic_example/basic_example.ipynb
```

Choose the Python environment where you installed ProtoLink as the notebook kernel, then run the cells from top to bottom. Jupyter supports the notebook's top-level `await`.

**Run All includes cleanup.** Pause before the final cleanup cell to use the browser status and chat pages. Run cleanup when finished, and before rebuilding the example with different settings.

## What the Notebook Covers

- **Core API:** `Registry(...)`, `Agent(...)`, `start()`, `call_tool()`, `invoke()`, `call_agent()`, and `stop()`.
- **Discovery and state:** use the agent's existing `client` to inspect peers and manage conversation state.
- **HTTP:** open status and chat pages, send small JSON requests, and inspect the endpoint tables.
- **Plug-in components:** add a calculator, attach a reusable `Tool`, replace a weather tool implementation, and attach knowledge.
- **Configuration recipes:** change the transport, LLM, conversation storage, or run store with short examples.
- **Optional extensions:** see a declarative mock delegation example and reference snippets for streaming and cancellation.

`MockLLM` returns configured text. The optional delegation example scripts a peer call through the normal agent loop; its final mock text is fixed, rather than generated from the returned weather data. Choose a real LLM from the notebook's replacement recipes for open-ended conversations.

## Architecture and Default Addresses

```text
                       Registry :9010
                     /                \
          registers /                  \ registers
                   /                    \
          WeatherAgent :8010 <---- AlertAgent :8020
                    typed task delegation
```

The registry provides discovery; agent-to-agent tasks go to the discovered agent's address. With the default HTTP configuration, the browser pages are:

| Service | Status page | Chat page |
| --- | --- | --- |
| Registry | [localhost:9010/status](http://localhost:9010/status) | — |
| WeatherAgent | [localhost:8010/status](http://localhost:8010/status) | [localhost:8010/chat](http://localhost:8010/chat) |
| AlertAgent | [localhost:8020/status](http://localhost:8020/status) | [localhost:8020/chat](http://localhost:8020/chat) |

Change the URL values near the top of the notebook if these ports are occupied.

## Transport Choices

The notebook lists HTTP, SSE JSON-RPC, WebSocket, in-process runtime, and gRPC configurations. Change the agents' `TRANSPORT` and URLs together; the registry can stay on HTTP or use its own transport setting. Install the optional gRPC dependency with `python -m pip install -e '.[grpc]'` before selecting it.

Before a transport change, run cleanup, then update the settings and rerun from the top. Skip the two HTTP-only request cells for runtime, WebSocket, and gRPC agents. Browser pages work with HTTP and SSE; runtime opens no network ports. Streaming requires a transport that advertises streaming support, such as SSE JSON-RPC.

## HTTP Agent API Reference

The notebook includes a few direct JSON requests and an endpoint reference. The default HTTP agents expose:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/healthz` | Transport health probe |
| `GET` | `/readyz` | Readiness probe; currently uses the same transport health handler |
| `GET` | `/status` | HTML status page |
| `GET` | `/.well-known/agent.json` | Agent card and advertised capabilities |
| `GET` | `/chat` | HTML chat page |
| `POST` | `/chat` | Chat request for an agent with an LLM |
| `POST` | `/tasks/` | Submit a typed task |
| `POST` | `/tasks/cancel` | Request cancellation of a task |
| `POST` | `/state/describe` | Inspect conversation state |
| `POST` | `/state/compact` | Compact conversation state |
| `POST` | `/state/reset` | Reset conversation state |
| `POST` | `/llm/history/compact` | Compact LLM history |

The registry has its own discovery API and status page. Task, chat, and state requests go to the agents. Streaming and cancellation are covered as optional reference examples; a `/tasks/stream` endpoint is registered only for a transport with streaming support.

## Rerunning and Troubleshooting

- **Connection refused:** run the startup cells in order and leave the services running until after the HTTP exploration cells.
- **Address already in use:** run cleanup for this notebook's previous run or change the configured ports.
- **Import error:** install the extras in the selected notebook kernel's Python environment.
- **Changed transport or component:** run cleanup, update the configuration, and rerun from the top. Restart the kernel for a completely fresh session.
