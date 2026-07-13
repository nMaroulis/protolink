# ProtoLink

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/protolink)](https://pypi.org/project/protolink/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/nmaroulis/protolink)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

<div align="center">
  <img src="https://raw.githubusercontent.com/nMaroulis/protolink/main/docs/assets/banner.png" alt="ProtoLink logo" width="60%">
</div>

ProtoLink is a lightweight Python runtime for building agent meshes. Start with several agents in one process, then keep the same `Agent`, `Task`, and `Message` contracts when moving to HTTP, SSE JSON-RPC, WebSocket, or gRPC.

> **Simple by default. Explicit when it matters.**

Agents express intent. Clients and servers handle communication. Transports handle protocols. ProtoLink keeps those boundaries separate while providing the infer loop, tools, delegation, lifecycle, runtime policy, and observability around them.

[Get started](https://nmaroulis.github.io/protolink/docs/getting-started/) · [Concept](https://nmaroulis.github.io/protolink/docs/concept/) · [API docs](https://nmaroulis.github.io/protolink/docs/) · [Examples](https://nmaroulis.github.io/protolink/docs/examples/)

## Run a provider-free agent mesh

This example needs no account, API key, model provider, registry, or network port. Install the base package, save the code as `mesh.py`, and run it:

```bash
uv add protolink
uv run python mesh.py
```

```python
import asyncio

from protolink import Agent, AgentCard, Message, Task
from protolink.client import AgentClient


class Specialist(Agent):
    def __init__(self, name: str, answer: str) -> None:
        super().__init__(
            AgentCard(
                name=name,
                description=f"{name.title()} specialist",
                url=f"runtime://{name}",
            ),
            transport="runtime",
            verbosity=0,
        )
        self.answer = answer

    async def handle_task(self, task: Task) -> Task:
        return task.complete(f"{self.card.name}: {self.answer}")


class Planner(Agent):
    async def handle_task(self, task: Task) -> Task:
        request = str(task.get_last_part_content())
        replies = await asyncio.gather(
            self.call_agent(
                "runtime://researcher",
                Task.create(Message.user(request)),
            ),
            self.call_agent(
                "runtime://reviewer",
                Task.create(Message.user(request)),
            ),
        )
        summary = "\n".join(str(reply.get_last_part_content()) for reply in replies)
        return task.complete(f"Plan for {request}:\n{summary}")


async def main() -> None:
    agents = [
        Specialist("researcher", "collect the evidence"),
        Specialist("reviewer", "check the risky assumptions"),
        Planner(
            AgentCard(
                name="planner",
                description="Coordinates specialists",
                url="runtime://planner",
            ),
            transport="runtime",
            verbosity=0,
        ),
    ]

    for agent in agents:
        agent.start(background=True)

    try:
        client = AgentClient("runtime", url="runtime://client")
        result = await client.send_task(
            "runtime://planner",
            Task.create(Message.user("ship v1")),
        )
        print(result.get_last_part_content())
    finally:
        for agent in reversed(agents):
            agent.stop()


asyncio.run(main())
```

Output:

```text
Plan for ship v1:
researcher: collect the evidence
reviewer: check the risky assumptions
```

The runtime transport applies the normal task serialization boundary without opening sockets. To deploy the same agent logic, give each card a network URL and select a network transport; the task handlers stay unchanged. For a complete runnable copy, see [`examples/provider_free_mesh.py`](https://github.com/nMaroulis/protolink/blob/main/examples/provider_free_mesh.py). The [transport guide](https://nmaroulis.github.io/protolink/docs/transport/) covers deployment choices and lifecycle details.

## Progressive control

The common path stays small. Pass a registered transport name and ProtoLink constructs it from the card URL with bounded defaults:

```python
from protolink import Agent, AgentCard

card = AgentCard(
    name="assistant",
    description="General-purpose assistant",
    url="http://127.0.0.1:8000",
)
agent = Agent(card=card, transport="http")
```

When the boundary needs TLS, resource limits, retries, keepalive settings, or protocol-specific options, construct the transport yourself and pass it to the same API:

```python
from protolink import (
    Agent,
    RetryPolicy,
    TLSConfig,
    TransportConfig,
    TransportLimits,
)
from protolink.transport import HTTPTransport

transport = HTTPTransport(
    url=card.url,
    tls=TLSConfig(
        certfile="certs/agent.pem",
        keyfile="certs/agent-key.pem",
        cafile="certs/ca.pem",
    ),
    config=TransportConfig(
        limits=TransportLimits(max_concurrent_requests=200),
        retry=RetryPolicy(max_attempts=3),
    ),
)
agent = Agent(card=card, transport=transport)
```

`AgentClient` and `Registry` follow the same rule: pass a string for the built-in defaults or a concrete transport object for full control. The facade does not change as deployment requirements grow. Read the [progressive-control design](https://nmaroulis.github.io/protolink/docs/concept/#api-design-progressive-control) and [production transport configuration](https://nmaroulis.github.io/protolink/docs/transport/#production-configuration).

## Design philosophy

- **Intent over mechanism** — agent logic works with typed tasks and messages, not sockets or wire formats.
- **Progressive control** — aliases keep the common path short; explicit objects expose every operational boundary.
- **Explicit execution** — tool calls, delegation, state changes, policy decisions, approvals, and results remain inspectable.
- **Local first, distributed when needed** — use in-process transport for fast iteration, then move the same contracts onto network transports.
- **Composable, not mandatory** — LLMs, native tools, MCP tools, storage, state, telemetry, registries, and flows are independent modules.

The result is one stable runtime shape instead of separate beginner and production APIs.

## The infer loop

For LLM-backed agents, the infer loop is the heart of ProtoLink:

1. The model proposes one next action.
2. ProtoLink parses and validates it.
3. The runtime executes a tool call, agent delegation, or final response.
4. The structured result is added to the task context.
5. The loop repeats until completion or a configured bound is reached.

Providers with native tool calling use it. Smaller or local models can use the JSON fallback. The surrounding task, tool, and delegation contracts stay the same, while runtime events make each action observable. See [LLMs and inference](https://nmaroulis.github.io/protolink/docs/llm/) and the [runtime control layer](https://nmaroulis.github.io/protolink/docs/runtime/).

## Built to stay inspectable

ProtoLink includes dependency-free local tracing. Attach `LocalTraceTelemetry`, run a task, and replay the captured spans without an external service:

```python
from protolink import Agent, AgentCard, LocalTraceTelemetry, Task, create_llm

telemetry = LocalTraceTelemetry(path="traces.jsonl")
agent = Agent(
    AgentCard(name="debug", description="Debug agent", url="runtime://debug"),
    transport="runtime",
    llm=create_llm("mock", default_response="done"),
    telemetry=telemetry,
    verbosity=0,
)

result = agent.sync.invoke("Trace this task")
trace = telemetry.recorder.replay()[-1]
```

The same public runtime contracts power cancellation, budgets, policy decisions, approval previews, run reports, replay, redaction, and the local dashboard.

## Explore the runtime

| Area | Start here |
| --- | --- |
| Agents, lifecycle, tools, and delegation | [Agent](https://nmaroulis.github.io/protolink/docs/agent/) |
| In-process, HTTP, SSE JSON-RPC, WebSocket, and gRPC | [Transport](https://nmaroulis.github.io/protolink/docs/transport/) |
| Models, infer loop, context, and history | [LLM](https://nmaroulis.github.io/protolink/docs/llm/) |
| Native Python tools and MCP adapters | [Tools](https://nmaroulis.github.io/protolink/docs/tool/) |
| Pipeline, parallel, router, and graph execution | [Flows](https://nmaroulis.github.io/protolink/docs/flows/) |
| Context, budgets, policy, approvals, events, and replay | [Runtime](https://nmaroulis.github.io/protolink/docs/runtime/) |
| Conversation state and durable run storage | [State](https://nmaroulis.github.io/protolink/docs/state/) · [Storage](https://nmaroulis.github.io/protolink/docs/storage/) |
| TLS, credentials, and authenticators | [Authentication](https://nmaroulis.github.io/protolink/docs/authentication/) |
| Local traces and runtime inspection | [Telemetry](https://nmaroulis.github.io/protolink/docs/telemetry/) · [Developer tools](https://nmaroulis.github.io/protolink/docs/devtools/) |

The CLI can also create a provider-free starter:

```bash
protolink init agent
uv run python agent.py
```

Inspect a run store and registry through the local dashboard:

```bash
protolink dashboard --store runs.db --registry-url http://127.0.0.1:9010 --open
```

## A2A 1.0 adapter and TCK verification

HTTP agents expose a dedicated A2A 1.0 JSON-RPC adapter, measured with the official [A2A Technology Compatibility Kit](https://github.com/a2aproject/a2a-tck). The [compatibility page](https://nmaroulis.github.io/protolink/docs/a2a/) records the exact binding, pinned TCK commit, commands, current result, and remaining limitation; this README does not make a broader compliance claim.

The runtime, transport, tool, flow, and observability APIs remain independently usable while that verification work is in progress.

## More examples

- [Provider-free runtime mesh](https://github.com/nMaroulis/protolink/blob/main/examples/provider_free_mesh.py)
- [HTTP agent communication](https://github.com/nMaroulis/protolink/blob/main/examples/http_agents.py)
- [Production transport configuration](https://github.com/nMaroulis/protolink/blob/main/examples/transport_production.py)
- [Runtime policy and approvals](https://github.com/nMaroulis/protolink/blob/main/examples/runtime_policy_and_approvals.py)
- [Task cancellation](https://github.com/nMaroulis/protolink/blob/main/examples/task_cancellation.py)
- [Structured flows](https://github.com/nMaroulis/protolink/tree/main/examples/structured_flows)
- [All examples](https://nmaroulis.github.io/protolink/docs/examples/)

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](https://github.com/nMaroulis/protolink/blob/main/CONTRIBUTING.md) and the [development guide](https://nmaroulis.github.io/protolink/docs/development/).

ProtoLink is available under the [MIT License](https://github.com/nMaroulis/protolink/blob/main/LICENSE).
