# A2A Core and 1.0 Compatibility

ProtoLink is an **A2A-first runtime**. `AgentCard`, `Task`, `Message`, `Part`,
`Artifact`, task states, and discovery are first-class concepts throughout its
Python API, structured flows, agent delegation, storage, and observability.
ProtoLink then adds the execution substrate A2A leaves open: pluggable LLMs,
native and MCP tools, transports, registry services, state, policy,
authentication, logging, and telemetry.

This page addresses the narrower question of canonical **A2A 1.0 wire
compatibility**. That is a property of the versioned HTTP adapter and must be
tested independently from the A2A-based runtime architecture. The official
[A2A Technology Compatibility Kit
(TCK)](https://github.com/a2aproject/a2a-tck) is the source of evidence.

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

The adapter keeps its A2A task index in the serving `Agent` process. This is a
deliberately small default for ProtoLink's one-process HTTP server. A deployment
that fans one logical agent out across multiple worker processes must add a
shared task router or store before presenting those workers as one A2A
interface.

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

## Run locally

The fixture uses a normal ProtoLink `Agent` with `transport="http"`. Its
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

On 13 July 2026, the command above at the pinned commit completed with:

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
