# A2A Core and 1.0 Compatibility

ProtoLink is an **A2A-first runtime**. `AgentCard`, `Task`, `Message`, `Part`,
`Artifact`, task states, and discovery are first-class concepts throughout its
Python API, structured flows, agent delegation, storage, and observability.
ProtoLink then adds the execution substrate A2A leaves open: pluggable LLMs,
native and MCP tools, transports, registry services, state, policy,
authentication, logging, and telemetry.

## From native A2A 0.3 primitives to A2A 1.0

ProtoLink was originally built natively on the [A2A 0.3
specification](https://a2a-protocol.org/v0.3.0/specification/): `AgentCard`,
`Task`, `Message`, `Part`, `Artifact`, task states, and discovery became its
public Python objects and its internal runtime language. Here, **0.3 is the A2A
protocol version**, not the ProtoLink package version, and **native** means that
these primitives underpin the runtime itself rather than existing only in an
integration adapter.

That foundation gives local and remote agents one small, typed language for
identity, work, results, and lifecycle. Because it is independent of any model
provider or transport, the same simple `Agent` and `Task` API can support local
inference, native and MCP tools, deterministic flows, persistence, and remote
delegation. ProtoLink extended the A2A 0.3 model with execution semantics such
as inference instructions, tool actions, flow state, runtime context, and
events; those are ProtoLink runtime features, not additional A2A operations.

As A2A evolved to 1.0, its canonical cards, operations, and wire shapes evolved
too. ProtoLink keeps its established native runtime model and places A2A 1.0
interoperability at an explicit, versioned boundary. With `a2a=True`, a standard
peer discovers a canonical Agent Card and exchanges canonical messages, tasks,
parts, artifacts, and states through the implemented JSON-RPC operations.
ProtoLink translates that surface to the same executor used by its native API.
Compatibility therefore comes from explicit two-way translation and TCK
verification, not from claiming that the A2A 0.3-based runtime objects are
identical to the A2A 1.0 wire schema.

This design lets an A2A 1.0 peer communicate with a ProtoLink agent without
forcing application code, tools, LLMs, or flows to adopt a second API.

This page addresses the narrower question of canonical **A2A 1.0 wire
compatibility** for the implemented JSON-RPC surface. That is a property of the
versioned HTTP adapter and must be tested independently from the A2A-based
runtime architecture. The official
[A2A Technology Compatibility Kit
(TCK)](https://github.com/a2aproject/a2a-tck) is the source of evidence.

## Enable the A2A 1.0 boundary

ProtoLink's native A2A 0.3-based runtime primitives are always present.
Translation for the implemented A2A 1.0 JSON-RPC surface is an explicit HTTP
capability:

```python
from protolink import Agent, AgentCard

agent = Agent(
    card=AgentCard(
        name="planner",
        description="Builds execution plans",
        url="http://127.0.0.1:8000",
    ),
    transport="http",
    a2a=True,
)
```

The default `a2a=False` is the pre-0.6.6 behavior: HTTP serves ProtoLink's
native task, card, status, health, chat, and control endpoints, and outbound
calls use the native contract. `a2a=True` requires the exact HTTP transport and
adds both:

- **Inbound translation:** `GET /.well-known/agent-card.json` and `POST /`
  expose the implemented A2A 1.0 Agent Card and JSON-RPC operations.
- **Outbound translation:** the agent's existing `AgentClient` can discover and
  call a standard A2A 1.0 JSON-RPC peer.

The native endpoints stay mounted, so enabling A2A does not change
`handle_task(Task)`, registry/state APIs, status/chat utilities, or normal
ProtoLink-to-ProtoLink calls.

### Choose the outbound protocol

```python
from protolink import Task

task = Task.create_infer(prompt="Prepare a release plan")

# Default: prefer ProtoLink when the peer has a native card, otherwise discover A2A.
result = await agent.call_agent(peer_url, task, protocol="auto")

# Explicit choices skip the native-vs-A2A selection step.
result = await agent.call_agent(peer_url, task, protocol="protolink")
result = await agent.call_agent(peer_url, task, protocol="a2a")
```

`"auto"` probes the native ProtoLink card first. Only a definitive `404` or
`405` moves discovery to the standard A2A Agent Card, and the result is cached
for five minutes. This process-local protocol cache is bounded to 1,024 peers;
expired and oldest entries are removed. Authentication, connection, timeout,
and server errors are not treated as evidence that the peer uses another
protocol, avoiding an unsafe second task submission. Native remains preferred
when a peer exposes both surfaces because it preserves ProtoLink-specific task
and flow information.
An explicit `protocol="protolink"` call goes directly to the native task route.
An explicit `protocol="a2a"` call still fetches and validates the standard Agent
Card so ProtoLink can select its compatible JSON-RPC 1.0 interface; it only
skips the native-versus-A2A choice.

A standalone client uses the same opt-in:

```python
from protolink.client import AgentClient

client = AgentClient(
    transport="http",
    url="http://127.0.0.1:0",
    a2a=True,
)
card = await client.get_a2a_agent_card(peer_url)
result = await client.send_task(peer_url, task, protocol="a2a")
```

### Trust advertised interface URLs

The secure default is `a2a_allow_cross_origin=False`. Before sending a task or
credentials, ProtoLink requires the JSON-RPC interface advertised by the
standard Agent Card to use the same origin: scheme, hostname, and effective
port. A cross-origin card is rejected before its interface receives a request.

Some deployments intentionally publish discovery and execution on different
origins. Enable that behavior only when the advertised endpoint is explicitly
trusted:

```python
client = AgentClient(
    transport="http",
    url="https://discovery.example",
    a2a=True,
    a2a_allow_cross_origin=True,
)
```

`Agent(..., a2a_allow_cross_origin=True)` configures its outbound client in the
same way. The flag trusts a cross-origin interface advertised by the card; it
is not an origin allowlist, so keep the default unless the split-origin
deployment is under your control.

:::caution[Compatibility status]

This page describes an engineering harness, not a compatibility claim.
ProtoLink should only claim a passing A2A 1.0 binding after the official TCK
finishes successfully and its report is published. A passing internal transport
test, a working `Agent`, or a valid-looking Agent Card is not a substitute.

:::

The commands below pin the TCK to commit
[`5996b79f9cefa6fc390980e383e358a66fb9e49e`](https://github.com/a2aproject/a2a-tck/commit/5996b79f9cefa6fc390980e383e358a66fb9e49e).
Pinning makes local and CI results reproducible even while the upstream TCK
continues to evolve.

## What the TCK expects

Before running operation tests, the TCK fetches:

```text
http://127.0.0.1:9999/.well-known/agent-card.json
```

The A2A 1.0 card must declare at least one entry in `supportedInterfaces`.
This harness starts with only `JSONRPC`, keeping the first compatibility target
narrow and auditable. The TCK then sends JSON-RPC 2.0 requests with A2A method
names such as `SendMessage`, `GetTask`, `ListTasks`, and `CancelTask`. It also
checks canonical A2A data shapes, error mappings, version handling, and any
capabilities declared by the card. See the [A2A 1.0
specification](https://a2a-protocol.org/latest/specification/) for the normative
contract.

The adapter keeps at most **1,024 tasks** for **one hour** in the serving
`Agent` process. Expired and oldest inactive tasks are removed first; active
operations are protected from eviction. If every retained slot is active, a new
task is rejected instead of silently dropping live work. The index is still
in-memory and disappears on restart. A deployment that fans one logical agent
out across multiple worker processes must add a shared task router or store
before presenting those workers as one A2A interface.

Do not point the TCK at the legacy `/.well-known/agent.json` endpoint. A 404 at
`/.well-known/agent-card.json` means the A2A 1.0 binding is not ready yet; it
must not be worked around by weakening the preflight check.

## Implemented JSON-RPC scope

The 1.0 adapter currently implements:

- `SendMessage`, including blocking and `returnImmediately` execution modes.
- `GetTask`, `ListTasks`, and `CancelTask` over a process-local task index.
- Task visibility scoped to the request tenant and, when the HTTP agent uses a
  ProtoLink `Authenticator`, the authenticated principal.
- History limits, task filtering, descending status-time ordering, pagination,
  and the `includeArtifacts` list policy.
- Canonical card, task, message, part, artifact, enum, timestamp, and
  `google.rpc.ErrorInfo` JSON shapes.
- A2A version and HTTP content-type validation.

The card declares streaming, push notifications, and the extended card as
disabled. Calls to those operations return their standard A2A errors instead
of silently advertising or emulating unsupported capabilities.

## Translation and portability

ProtoLink keeps protocol translation at the boundary rather than changing its
runtime execution rules:

- An inbound A2A `ROLE_USER` text part remains a ProtoLink
  `Part(type="text")`, so custom handlers see canonical text. The adapter marks
  the task with `task.metadata["a2a_inbound"]`; when an LLM is configured, the
  default Agent engine recognizes that metadata and treats the text as an
  inference request.
- An outbound ProtoLink `infer` prompt becomes a standard A2A text part.
- Text, JSON data, raw/file content, URI content, messages, artifacts, task
  status, and supported security declarations have canonical translations.
- A2A servers assign their own task IDs. ProtoLink preserves the caller's local
  task ID and stores the remote ID, context, state, and status timestamp in
  namespaced task metadata for continuation and cancellation.
- `send_message()` returns a response `Message`. If an A2A peer completes with
  artifacts but no response message, use `send_task()` to receive and inspect
  the complete task rather than losing the artifacts behind the convenience
  API.

Some native ProtoLink semantics are intentionally not portable. `tool_call`
parts, `flow_state`, run budgets and context, registry/state control operations,
and arbitrary framework metadata have no universal A2A execution meaning.
Unknown part types can cross as structured data tagged with
`protolinkPartType`, but an arbitrary A2A peer is not required to understand
that extension. Use `protocol="protolink"` when two ProtoLink agents need the
full native contract; `"auto"` already makes that the preferred path.

### Outbound task IDs and cancellation

The local-to-remote task-ID mappings used for A2A continuation and cancellation
are process-local, bounded to **1,024 entries**, and expire after **one hour**.
Oldest entries are removed when the bound is exceeded. Restarting the process
or losing a mapping means the client can no longer safely cancel that remote
task by its local ProtoLink ID.

`cancel_task(..., reason=..., metadata=...)` translates both values through A2A
`CancelTask` metadata. The inbound adapter reconstructs the corresponding
ProtoLink cancellation request, including its reason and metadata.

A blocking outbound A2A `SendMessage` does not expose the server-assigned task
ID until its response is returned. Consequently, that operation cannot be
canceled through this client while the initial call is still blocked. In
`protocol="auto"`, ProtoLink first confirms that the peer is A2A and raises
`A2AClientError` when no mapping exists; it never guesses by sending the local
ID to ProtoLink's native cancellation route.

## Roadmap beyond 0.6.6

The following A2A 1.0 capabilities remain future work and are advertised as
disabled today:

- `SendStreamingMessage` and `SubscribeToTask` streaming operations.
- Task push-notification configuration and delivery.
- Extended authenticated Agent Cards.

Until those capabilities land with focused tests and TCK evidence, use
ProtoLink's native SSE, WebSocket, gRPC, or runtime streaming APIs where live
events are required.

## Run locally

The fixture uses a normal ProtoLink `Agent` with `transport="http", a2a=True`. Its
`handle_task()` implementation is deterministic and provider-free, so the TCK
does not need an API key or an LLM account.

From the ProtoLink repository root, install the HTTP dependencies and start the
fixture:

```bash
uv pip install -e ".[test,http]"
uv run python examples/a2a_tck_agent.py
```

Leave that process running. In a second terminal, verify the A2A 1.0 discovery
endpoint before cloning or running the TCK:

```bash
curl --fail --silent \
  http://127.0.0.1:9999/.well-known/agent-card.json \
  | python -m json.tool
```

Clone and pin the official TCK outside the ProtoLink checkout:

```bash
git clone https://github.com/a2aproject/a2a-tck.git /tmp/a2a-tck
git -C /tmp/a2a-tck checkout --detach \
  5996b79f9cefa6fc390980e383e358a66fb9e49e
cd /tmp/a2a-tck
uv sync --frozen
```

Run the mandatory JSON-RPC requirements first:

```bash
uv run ./run_tck.py \
  --sut-host http://127.0.0.1:9999 \
  --transport jsonrpc \
  --level must \
  -v
```

The TCK writes these artifacts under `/tmp/a2a-tck/reports/`:

- `compatibility.json` for machine-readable requirement results.
- `compatibility.html` for the human-readable compatibility report.
- `tck_report.html` for the underlying pytest report.
- `junitreport.xml` for CI systems.

Re-run one failure with full logs by passing pytest arguments after `--`:

```bash
uv run ./run_tck.py \
  --sut-host http://127.0.0.1:9999 \
  --transport jsonrpc \
  --level must \
  --verbose-log \
  -- -k "CORE-SEND-001" --tb=long
```

## Recorded baseline

On 14 July 2026, the command above at the pinned commit completed with:

```text
1 failed, 67 passed, 167 skipped, 30 deselected
```

The sole failure is the generic `CORE-SEND-003` requirement test. ProtoLink
returns the required JSON-RPC `ContentTypeNotSupportedError` (`-32005`) for the
unsupported media type, and the TCK's dedicated error-code test passes. At this
pin, however, the upstream [`CORE-SEND-003` requirement
entry](https://github.com/a2aproject/a2a-tck/blob/5996b79f9cefa6fc390980e383e358a66fb9e49e/tck/requirements/core_operations.py#L96-L122)
omits its `expected_error`. The [generic requirement
runner](https://github.com/a2aproject/a2a-tck/blob/5996b79f9cefa6fc390980e383e358a66fb9e49e/tests/compatibility/core_operations/test_requirements.py#L96-L113)
therefore treats the required error response as a failed operation.

This is an upstream defect in the pinned TCK, but the checked-in workflow is
deliberately left red: ProtoLink does not patch the conformance kit or convert
the failure into a pass. Re-run against a newer, explicitly pinned TCK commit
after upstream corrects the requirement entry, and record that new pin and
report before making a passing claim.

## Interpreting a result

A successful, unmodified `--transport jsonrpc --level must` run at an
explicitly recorded TCK commit supports a precise statement such as:

> ProtoLink passed the A2A 1.0 JSON-RPC MUST suite at TCK commit
> `<commit>`.

It does not demonstrate gRPC or HTTP+JSON compatibility, and it does not mean
that every SHOULD or MAY requirement was exercised. Run the unfiltered suite
and publish its exact report before making a broader claim.

## Manual CI probe

The `A2A TCK` GitHub Actions workflow is intentionally available only through
`workflow_dispatch`. It starts the same provider-free fixture, enforces the
1.0 Agent Card preflight, runs the pinned JSON-RPC MUST suite, and uploads the
logs and reports even after a failure. It is not a required pull-request check
and currently surfaces the known `CORE-SEND-003` failure described above. It
should not be represented as a compatibility badge until an unmodified,
explicitly pinned TCK report passes.
