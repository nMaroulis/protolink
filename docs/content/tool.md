import ApiSurface from '@site/src/components/ApiSurface';
import ApiReference, {
  ApiCallout,
  ApiField,
  ApiFields,
  ApiSection,
} from '@site/src/components/ApiReference';

# Tools

Tools extend agent capabilities with additional functions. They enable LLMs and agents to interact with external systems, execute code, access data, and perform specialized tasks that go beyond pure text generation.

## Overview

Protolink provides a flexible tool system with three approaches:

- **Built-in Tools**: Opt-in, dependency-free factories for common read-only and pure operations
- **Native Tools**: Python functions decorated directly on an agent
- **MCP Tools**: Tools from external MCP (Model Context Protocol) servers

All three tool sources use the same interface, making them interchangeable from the agent's perspective.

## Module Structure

The tools module is organized as follows:

```python
# Core interfaces and opt-in built-ins
from protolink.tools import (
    BaseTool,
    Tool,
    calculator,
    current_datetime,
    fetch_url,
    web_search,
)

# Tool adapters for external integrations  
from protolink.tools.adapters import MCPToolAdapter
```

| Module | Description |
|--------|-------------|
| `protolink.tools` | Core interfaces, native implementation, and public built-in factories |
| `protolink.tools.builtins` | Implementations for the dependency-free built-in tools |
| `protolink.tools.adapters` | Adapters for integrating external tool systems |

---

<ApiSurface
  eyebrow="Tool module"
  title="Tools"
  path="protolink.tools"
  description="The callable capability layer for native Python functions, MCP-backed tools, JSON schemas, examples, capability policies, and approval-aware action metadata."
  pills={[
    "Native decorators",
    "MCP adapters",
    "Schema inference",
    "Capability enforcement",
    "AgentSkill advertising",
  ]}
  cards={[
    {
      title: "Built-in tools",
      text: "Explicitly register dependency-free web search, safe URL fetch, calculator, and current-datetime tools.",
      code: "agent.add_tool(web_search())",
    },
    {
      title: "Base contract",
      text: "Tools are async callables with a name, description, input schema, output schema, tags, examples, and capabilities.",
      code: "BaseTool",
    },
    {
      title: "Native tools",
      text: "Register typed Python functions directly on an agent and let Protolink infer schemas.",
      code: "@agent.tool",
    },
    {
      title: "MCP tools",
      text: "Adapt tools from Model Context Protocol servers into the same runtime interface.",
      code: "MCPToolAdapter",
    },
    {
      title: "Policy hooks",
      text: "Attach capabilities and action builders so runtime policy can allow, deny, or request approval.",
      code: "capabilities",
    },
  ]}
/>

## BaseTool Protocol

All tools in ProtoLink conform structurally to `BaseTool`. It is a typing protocol rather than a concrete base class: any object with the advertised metadata and asynchronous call behavior can be registered, including native `Tool` instances and wrapped MCP tools.

### BaseTool

<ApiReference
  kind="protocol"
  path="protolink.tools.BaseTool"
  signature={`class BaseTool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any] | None
    output_schema: Any | None
    tags: list[str] | None
    examples: list[Any] | None
    capabilities: Collection[str] | None

    async __call__(**kwargs) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/base.py#L5"
>

The protocol is the smallest contract understood by Agent registration and execution. Metadata describes the tool to models, discovery clients, and policy; `__call__()` performs the actual operation.

<ApiSection title="Attributes">
  <ApiFields ariaLabel="BaseTool protocol attributes">
    <ApiField name="name" type="str">
      Stable identifier used in model tool declarations, task parts, registry skills, policy actions, and <code>agent.call_tool()</code>. Names should be unique within one Agent because registering the same name replaces the runtime tool.
    </ApiField>
    <ApiField name="description" type="str">
      Human-readable purpose shown to the model and copied to the advertised <code>AgentSkill</code>. Explain when to call the tool, not only what its Python function is named.
    </ApiField>
    <ApiField name="input_schema" type="dict[str, Any] | None">
      JSON Schema for accepted keyword arguments. Agent execution validates model-provided arguments against this schema before the callable runs.
    </ApiField>
    <ApiField name="output_schema" type="Any | None">
      Optional schema describing the returned value. It is advertised to callers but does not currently validate the runtime result.
    </ApiField>
    <ApiField name="tags" type="list[str] | None">
      Discovery and presentation labels copied to the Agent's skill card.
    </ApiField>
    <ApiField name="examples" type="list[Any] | None">
      Representative calls or values copied to <code>AgentSkill.examples</code>. They guide clients and models but are not executed automatically.
    </ApiField>
    <ApiField name="capabilities" type="Collection[str] | None">
      Authority strings merged into the <code>RunAction</code> evaluated immediately before execution. Capabilities become enforceable only when the call passes through Agent policy.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Call">
  <ApiFields ariaLabel="BaseTool call contract">
    <ApiField name="**kwargs" type="Any">
      Keyword arguments matching <code>input_schema</code>. Positional invocation is outside the protocol.
    </ApiField>
    <ApiField name="return" type="Any">
      Tool-specific result. Implementations may return any JSON-compatible or application value.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Runtime boundary">
  Calling a tool object directly bypasses Agent authorization and approvals. Register it and use <code>agent.call_tool()</code> or <code>agent.sync.call_tool()</code> for those controls. Use task execution for the full cancellation, telemetry, budget, and persistence lifecycle.
</ApiCallout>

</ApiReference>

### Tool

<ApiReference
  kind="dataclass"
  path="protolink.tools.Tool"
  signature={`class Tool(
    name: str,
    description: str,
    input_schema: dict[str, Any] | None,
    output_schema: Any | None,
    tags: list[str] | None,
    func: Callable[..., Any],
    args: dict[str, Any] | None = None,
    examples: list[Any] | None = None,
    capabilities: Collection[str] | None = None,
    action_builder: ActionBuilder | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/tool.py#L17"
>

Adapt a synchronous or asynchronous Python callable to the `BaseTool` contract. Construction inspects the callable signature and resolved type hints, infers any missing schemas, normalizes explicit schemas, and converts missing tags, examples, and capabilities into empty collections.

For ordinary functions, use `agent.add_tool(func)` or `@agent.tool` to infer name, description, and schemas. Use `Tool.from_callable(func, ...)` for a reusable definition with explicit metadata overrides, and the constructor when restoring or assembling a complete tool definition.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Tool constructor parameters">
    <ApiField name="name" type="str" required>
      Stable runtime and advertised identifier.
    </ApiField>
    <ApiField name="description" type="str" required>
      Purpose presented to models and discovery clients.
    </ApiField>
    <ApiField name="input_schema" type="dict[str, Any] | None" required>
      Explicit JSON Schema or legacy field map. Pass <code>None</code> to infer an object schema from <code>func</code>'s parameters and type annotations.
    </ApiField>
    <ApiField name="output_schema" type="Any | None" required>
      Explicit result schema, or <code>None</code> to infer one from the callable's return annotation.
    </ApiField>
    <ApiField name="tags" type="list[str] | None" required>
      Discovery labels. <code>None</code> becomes an empty list.
    </ApiField>
    <ApiField name="func" type="Callable[..., Any]" required>
      Wrapped Python function. Synchronous return values are accepted; awaitable results are awaited automatically.
    </ApiField>
    <ApiField name="args" type="dict[str, Any] | None" defaultValue="None">
      Legacy metadata retained on the dataclass. Runtime invocation uses arguments passed to <code>__call__()</code>, not this mapping.
    </ApiField>
    <ApiField name="examples" type="list[Any] | None" defaultValue="None">
      Advertised examples. <code>None</code> becomes an empty list.
    </ApiField>
    <ApiField name="capabilities" type="Collection[str] | None" defaultValue="None">
      Required policy capabilities. Empty values are removed and duplicates are discarded while preserving first occurrence.
    </ApiField>
    <ApiField name="action_builder" type="ActionBuilder | None" defaultValue="None">
      Optional sync or async callback that receives validated arguments and the active <code>RunContext</code>, then returns a customized <code>RunAction</code> with preview artifacts or metadata.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Tool errors">
    <ApiField name="ValueError | TypeError">
      Callable inspection, type-hint resolution, or explicit schema normalization can fail during construction.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### Tool.from_callable

<ApiReference
  kind="classmethod"
  path="protolink.tools.Tool.from_callable"
  signature={`Tool.from_callable(
    func: Callable[..., Any],
    *,
    name: str | None = None,
    description: str | None = None,
    input_schema: dict[str, Any] | None = None,
    output_schema: Any | None = None,
    tags: list[str] | None = None,
    examples: list[Any] | None = None,
    capabilities: Collection[str] | None = None,
    action_builder: ActionBuilder | None = None,
) -> Tool`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/tool.py"
>

Create a reusable tool from a synchronous or asynchronous callable. The default name is the function name, or the class name for a callable object. The default description is its cleaned docstring, falling back to <code>Call &lt;name&gt;.</code>. Explicit metadata takes precedence; missing input and output schemas use the same type-hint inference as the constructor. <code>agent.add_tool(func)</code> calls this factory automatically for ordinary callables; use it explicitly when adding metadata overrides or sharing a preconfigured tool.

<ApiSection title="Parameters"><ApiFields ariaLabel="Tool from_callable parameters">
  <ApiField name="func" type="Callable[..., Any]" required>Original callable retained as <code>tool.func</code>. The factory does not replace or execute it.</ApiField>
  <ApiField name="name, description" type="str | None" defaultValue="None">Optional public metadata overrides. All arguments after <code>func</code> are keyword-only.</ApiField>
  <ApiField name="input_schema, output_schema, tags, examples, capabilities, action_builder">The same schema, discovery, permission, and preview metadata accepted by the explicit constructor.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Returns"><ApiFields ariaLabel="Tool from_callable return value">
  <ApiField name="tool" type="Tool">A tool ready for <code>agent.add_tool()</code>, with inferred schemas and unchanged validation behavior.</ApiField>
</ApiFields></ApiSection>

<ApiSection title="Raises"><ApiFields ariaLabel="Tool from_callable errors">
  <ApiField name="TypeError">The input is not callable, its signature cannot be inspected, or its explicit or inferred name is not a string.</ApiField>
  <ApiField name="ValueError">The tool name is empty or whitespace-only, or signature inspection or explicit schema normalization fails.</ApiField>
</ApiFields></ApiSection>

</ApiReference>

```python
from protolink import Tool

def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b

add_tool = Tool.from_callable(add, tags=["math"])
agent.add_tool(add_tool)
# The same definition can also be registered on another agent.
```

### Tool.validate_args

<ApiReference
  kind="method"
  path="protolink.tools.Tool.validate_args"
  signature={`validate_args(
    kwargs: dict[str, Any] | None,
) -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/tool.py#L76"
>

Validate proposed keyword arguments with the normalized input schema, wrapped callable signature, and resolved type hints. Custom execution paths can call this method to perform the same coercion as `Tool.__call__()` before preparing policy metadata.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Tool validate_args parameters">
    <ApiField name="kwargs" type="dict[str, Any] | None" required>
      Untrusted argument mapping. <code>None</code> becomes an empty dictionary, and the supplied mapping is copied before coercion.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Tool validate_args return value">
    <ApiField name="arguments" type="dict[str, Any]">
      Validated mapping containing any safe scalar conversions or reconstructed annotated objects.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Tool validate_args errors">
    <ApiField name="ValueError">
      Schema violations, missing or unexpected fields, incompatible values, and annotation-validation failures.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### Tool.__call__

<ApiReference
  kind="async method"
  path="protolink.tools.Tool.__call__"
  signature={`async __call__(
    **kwargs: Any,
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/tool.py#L85"
>

Validate keyword arguments and invoke the wrapped Python callable. A synchronous result is returned from the coroutine immediately; an awaitable result is awaited before returning.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Tool call parameters">
    <ApiField name="**kwargs" type="Any">
      Values accepted by the generated or explicit input schema and the callable signature.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Tool call return value">
    <ApiField name="result" type="Any">
      Direct or awaited result from <code>func</code>. <code>output_schema</code> advertises this value but is not enforced here.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Tool call errors">
    <ApiField name="ValueError">
      Argument validation fails before user code executes.
    </ApiField>
    <ApiField name="callable error">
      Exceptions from the wrapped function propagate unchanged.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Direct invocation">
  This method does not apply Agent policy or task controls by itself. Those surround the call in <code>Agent.call_tool_in_context()</code> and the task engine.
</ApiCallout>

</ApiReference>

### Tool.prepare_action

<ApiReference
  kind="async method"
  path="protolink.tools.Tool.prepare_action"
  signature={`async prepare_action(
    arguments: dict[str, Any],
    context: RunContext,
) -> RunAction`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/tool.py#L98"
>

Build the runtime action evaluated before this tool executes. Without a custom builder, the action has kind `tool.call`, the tool name and description, validated arguments as payload, and the tool's declared capability set.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Tool prepare_action parameters">
    <ApiField name="arguments" type="dict[str, Any]" required>
      Already validated keyword arguments proposed for execution.
    </ApiField>
    <ApiField name="context" type="RunContext" required>
      Active run identity, permissions, session, cancellation, and budget context supplied to a custom builder.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Tool prepare_action return value">
    <ApiField name="action" type="RunAction">
      Domain-neutral policy action. A sync or async custom builder may add metadata or preview artifacts, but the tool's required capabilities are merged back into the result.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="Tool prepare_action errors">
    <ApiField name="TypeError">
      The configured <code>action_builder</code> does not return <code>RunAction</code>.
    </ApiField>
    <ApiField name="builder error">
      Exceptions raised by the application builder propagate to the execution layer.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

All tools are async callables from the caller's perspective and accept keyword arguments matching their input schema:

```python
# Tools are invoked with keyword arguments
result = await tool(location="Tokyo", units="celsius")
```

---

## Built-in Tools

ProtoLink includes four dependency-free tool factories for common agent tasks:

- `web_search()` creates `web_search`, which requires `network.read` and returns normalized ranked source snippets.
- `fetch_url()` creates `fetch_url`, which requires `network.read` and returns bounded readable text from one public URL.
- `calculator()` creates `calculator`, a pure bounded arithmetic evaluator with no protected capability.
- `current_datetime()` creates `current_datetime`, a timezone-aware clock tool with no protected capability.

Factories return fresh native `Tool` instances. Nothing is enabled automatically: register only the capabilities an agent needs.

```python
from protolink import Agent, AgentCard, CapabilityPolicy
from protolink.tools import calculator, current_datetime, fetch_url, web_search

agent = Agent(
    card=AgentCard(
        name="researcher",
        description="Finds and summarizes public information",
        url="runtime://researcher",
    ),
    transport="runtime",
    policy=CapabilityPolicy(
        {"network.read": "allow"},
        default_effect="deny",
    ),
)

agent.add_tool(web_search())
agent.add_tool(fetch_url())
agent.add_tool(calculator())
agent.add_tool(current_datetime())
```

Registered tools participate in schema validation, runtime policy, and AgentSkill advertising. When the inference loop invokes one during a task, the task's cancellation, telemetry, and tool-call budget controls apply as well. `network.read` identifies the authority required by `web_search` and `fetch_url`; `calculator` and `current_datetime` declare no protected capability.

:::warning[Default policy and direct calls]

The default `CapabilityPolicy` is allow-by-default for backward compatibility. Declaring `network.read` makes authority visible and configurable, but does not deny it by itself. Pass a restrictive policy when network access should be denied or approval-gated.

Calling a `Tool` object directly, such as `await web_search()(query="...")`, invokes the tool without the Agent and therefore bypasses Agent policy and approval. Use `agent.call_tool(...)` for Agent validation and policy, or let the inference loop invoke a registered tool when the task's full runtime controls should apply.

Agent dict/YAML serialization preserves each built-in's stable identity and the declarative rules, default effect, and name of ProtoLink's first-party `CapabilityPolicy`. Custom policy implementations and approval callbacks are executable application objects and are not embedded; pass them explicitly when restoring, for example `Agent.from_yaml("agent.yaml", policy=custom_policy, approval_handler=approve)`. An explicit policy override takes precedence over serialized first-party policy data.

:::

### Web Search

`web_search()` has one normalized result contract across three explicit engines:

- `engine="brave"` is the default. It uses the [Brave Search API](https://api-dashboard.search.brave.com/api-reference/web/search/get) and reads `BRAVE_SEARCH_API_KEY` from the environment only when invoked. The key is not captured by the Tool, stored in Agent configuration, or required merely to import or register the factory.
- `engine="duckduckgo"` needs no API key or additional dependency. It reads DuckDuckGo's published [non-JavaScript HTML search](https://duckduckgo.com/duckduckgo-help-pages/features/non-javascript) as a best-effort interface.
- `engine="wikipedia"` needs no API key or additional dependency. It uses English Wikipedia's documented [REST page-search API](https://www.mediawiki.org/wiki/API:REST_API/Reference#Search_pages), which is the reliable keyless choice for encyclopedia and factual discovery. It supports `freshness="any"` only.

Engine selection is per call and there is no silent fallback. A missing Brave key therefore remains a clear configuration error instead of unexpectedly sending the query to another provider.

```bash
export BRAVE_SEARCH_API_KEY="your-key"
```

```python
result = await agent.call_tool(
    "web_search",
    query="Python 3.14 release notes",
    max_results=5,
)

keyless_result = await agent.call_tool(
    "web_search",
    query="What is the capital of Greece?",
    engine="wikipedia",
)

best_effort_result = await agent.call_tool(
    "web_search",
    query="Python structured concurrency",
    engine="duckduckgo",
    freshness="month",
)
```

For a complete Agent-path CLI, see [`examples/builtin_web_search.py`](https://github.com/nMaroulis/protolink/blob/main/examples/builtin_web_search.py). It registers the built-in with an explicit `network.read` policy, supports all three engines, and prints the normalized JSON result:

```bash
# Keyless search through Wikipedia's documented API (example default)
python examples/builtin_web_search.py "What is the capital of Greece?"

# Documented Brave API
export BRAVE_SEARCH_API_KEY="your-key"
python examples/builtin_web_search.py "Python structured concurrency" --engine brave

# Keyless, best-effort DuckDuckGo HTML search
python examples/builtin_web_search.py "Python structured concurrency" --engine duckduckgo
```

Running the example without a query only prints its CLI help, so it is safe to inspect without credentials or a network request.

<ApiReference
  kind="factory"
  path="protolink.tools.web_search"
  signature={`web_search() -> Tool`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/builtins/web.py#L766"
>

Create a fresh `Tool` named `web_search`. The factory does not make a request and does not read the Brave credential; provider selection and credential lookup happen only when the returned tool is invoked.

<ApiSection title="Returns">
  <ApiFields ariaLabel="web_search factory return value">
    <ApiField name="tool" type="Tool">
      A native tool tagged <code>builtin</code>, <code>web</code>, <code>search</code>, and <code>read-only</code>, with the <code>network.read</code> capability and a bounded provider-neutral output schema.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Generated tool call">
  <ApiFields ariaLabel="web_search generated tool arguments">
    <ApiField name="query" type="str" required>
      Search text after surrounding whitespace is removed. It must contain 1–400 characters and no more than 50 whitespace-separated words.
    </ApiField>
    <ApiField name="max_results" type="int" defaultValue="5">
      Maximum normalized results returned to the model. Accepted range: 1–10.
    </ApiField>
    <ApiField name="freshness" type={'"any" | "day" | "week" | "month" | "year"'} defaultValue={'"any"'}>
      Optional result-age filter. Wikipedia accepts only <code>"any"</code>; requesting another value with that engine raises <code>ValueError</code>.
    </ApiField>
    <ApiField name="engine" type={'"brave" | "duckduckgo" | "wikipedia"'} defaultValue={'"brave"'}>
      Explicit provider. Brave requires <code>BRAVE_SEARCH_API_KEY</code>; DuckDuckGo and Wikipedia are keyless and never selected as a silent fallback.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns from invocation">
  <ApiFields ariaLabel="web_search generated tool result">
    <ApiField name="result" type="dict[str, Any]">
      Contains the normalized query, selected provider, ranked result objects, <code>more_results_available</code>, and <code>untrusted_content=True</code>. Each result includes title, URL, snippet, and an explicit sponsored marker.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="web_search errors">
    <ApiField name="ValueError">
      Invalid query length, word count, result limit, freshness, provider selection, or missing Brave credential.
    </ApiField>
    <ApiField name="RuntimeError">
      Provider response, content, challenge, HTTP, decoding, or bounded-transfer failures.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

The tool normalizes all three engines into provider-neutral JSON-compatible data and bounds the result count and text placed into model context. Every result includes `sponsored`; Brave and Wikipedia results use `False`, while recognized DuckDuckGo advertisements stay in provider order with `sponsored=True`. Every engine uses a fixed HTTPS endpoint with DNS validation, a 2,000,000-byte response limit, a 10-second transport deadline, and no redirects. Wikipedia excerpts are converted from bounded provider markup to plain text. DuckDuckGo organic redirect links are decoded locally and validated; sponsored click URLs remain intact. Results also include the selected `provider`, `more_results_available`, and the explicit marker `untrusted_content=True`.

DuckDuckGo's HTML page is a human-facing interface rather than a versioned developer API. It can change markup, rate-limit automated requests, or return a human-verification challenge. ProtoLink does not spoof a browser, suppress or discard recognized advertising, retry a challenge, or attempt to bypass one; it raises a clear error that points to Wikipedia as the keyless alternative. Applications distributing a DuckDuckGo-backed integration should review DuckDuckGo's [URL-parameter and partnership guidance](https://duckduckgo.com/duckduckgo-help-pages/settings/params). Use Wikipedia for reliable keyless encyclopedia search or Brave when a documented, general-web provider contract is required. With every engine, search queries leave the process, and titles, URLs, snippets, and page content are untrusted external data. Do not treat search output as instructions, executable content, or proof that a claim is correct.

### URL Fetch

`fetch_url()` retrieves bounded textual content from a public HTTP or HTTPS URL. It rejects credentials in URLs, non-HTTP schemes, and private, loopback, link-local, reserved, or otherwise non-public targets. Redirect destinations are resolved and validated again before they are followed. Responses are subject to redirect, timeout, byte, character, and supported-text-content limits; the result reports when extracted text was truncated.

```python
page = await agent.call_tool("fetch_url", url="https://example.com/")
```

<ApiReference
  kind="factory"
  path="protolink.tools.fetch_url"
  signature={`fetch_url() -> Tool`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/builtins/web.py#L831"
>

Create a fresh `Tool` named `fetch_url`. Construction is side-effect free; DNS resolution and network access begin only when the returned tool is invoked.

<ApiSection title="Returns">
  <ApiFields ariaLabel="fetch_url factory return value">
    <ApiField name="tool" type="Tool">
      A native read-only web tool with the <code>network.read</code> capability, public-destination validation, bounded redirects and bytes, and an explicit output schema.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Generated tool call">
  <ApiFields ariaLabel="fetch_url generated tool arguments">
    <ApiField name="url" type="str" required>
      Public HTTP or HTTPS URL of at most 2,048 characters. Embedded credentials, nonstandard ports, unsafe address ranges, HTTPS downgrades, and non-public redirect targets are rejected.
    </ApiField>
    <ApiField name="max_chars" type="int" defaultValue="12000">
      Maximum readable text characters returned after download and decoding. Accepted range: 1–50,000; transfer bytes are bounded separately.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns from invocation">
  <ApiFields ariaLabel="fetch_url generated tool result">
    <ApiField name="result" type="dict[str, Any]">
      Final validated URL, HTTP status, normalized content type, extracted title, bounded text, truncation flag, and <code>untrusted_content=True</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="fetch_url errors">
    <ApiField name="ValueError">
      Invalid URL shape, scheme, credentials, port, address, redirect destination, or character limit.
    </ApiField>
    <ApiField name="RuntimeError">
      HTTP, redirect, timeout, response-size, content-type, charset, or HTML-decoding failures.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

After each destination is DNS-validated, the transfer is limited to 1,000,000 bytes, four validated redirects, and a 10-second transport deadline for each request or redirect before the `max_chars` return bound is applied. DNS lookup uses the host operating system's resolver and is not included in that transport deadline. These restrictions reduce accidental server-side request forgery and context exhaustion; they do not make remote content trustworthy. Treat returned text as untrusted input and keep application-specific authorization at the Agent policy boundary.

### Calculator and Current Datetime

`calculator()` evaluates a deliberately small arithmetic grammar rather than Python code. It never uses `eval`, rejects names and function calls, and enforces expression-complexity, exponent, magnitude, and finite-result limits.

`current_datetime()` returns structured current-time data for the requested timezone. UTC works without a host timezone database; other IANA zones use the system database, or the `tzdata` package when a host does not provide one. Invalid or unavailable timezone identifiers raise a clear tool error rather than silently falling back to local machine time.

```python
calculation = await calculator()(expression="(18 + 6) / 3")
now = await current_datetime()(timezone="Europe/Zurich")
```

#### calculator

<ApiReference
  kind="factory"
  path="protolink.tools.calculator"
  signature={`calculator() -> Tool`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/builtins/calculator.py#L104"
>

Create a fresh pure arithmetic tool. The returned callable parses a restricted Python expression AST; it never uses `eval` and cannot resolve names, attributes, calls, booleans, or complex values.

<ApiSection title="Generated tool call">
  <ApiFields ariaLabel="calculator generated tool arguments">
    <ApiField name="expression" type="str" required>
      Arithmetic expression of 1–256 characters using numbers, parentheses, unary signs, and <code>+</code>, <code>-</code>, <code>*</code>, <code>/</code>, <code>//</code>, <code>%</code>, or <code>**</code>. Syntax-tree size, exponent size, numeric magnitude, and finite-result limits prevent resource-heavy evaluation.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="calculator result">
    <ApiField name="result" type="dict[str, int | float | str]">
      The trimmed original <code>expression</code> and its finite numeric <code>result</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="calculator errors">
    <ApiField name="ValueError">
      Empty or invalid arithmetic, unsupported syntax, division by zero, oversized powers or values, excessive complexity, and non-finite results.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### current_datetime

<ApiReference
  kind="factory"
  path="protolink.tools.current_datetime"
  signature={`current_datetime() -> Tool`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/builtins/clock.py#L67"
>

Create a fresh timezone-aware clock tool. UTC requires no external service or timezone database; other IANA identifiers are resolved through the host database or the optional `tzdata` package.

<ApiSection title="Generated tool call">
  <ApiFields ariaLabel="current_datetime generated tool arguments">
    <ApiField name="timezone" type="str" defaultValue={'"UTC"'}>
      IANA timezone name of at most 100 characters. The tool never silently substitutes host-local time for an unknown zone.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="current_datetime result">
    <ApiField name="result" type="dict[str, Any]">
      Requested timezone, ISO-8601 timestamp, date, time, weekday, UTC offset, and Unix timestamp.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="current_datetime errors">
    <ApiField name="ValueError">
      Empty, oversized, unknown, or unavailable timezone identifiers.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

---

## Native Tools

**Native tools** are regular Python callables that you register on an agent. They are exposed over the transport so that other agents (or clients) can invoke them.

### Registering Native Tools

Pass an existing function to `agent.add_tool()` or decorate a function with `@agent.tool`. Both infer the public name, cleaned docstring, and schemas from the callable:

```python
from protolink import Agent, AgentCard

agent_card = AgentCard(
    url="runtime://calculator",
    name="calculator_agent", 
    description="Agent with math tools"
)
agent = Agent(card=agent_card, transport="runtime", verbosity=0)

def add(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b

agent.add_tool(add)


@agent.tool()
async def multiply(a: float, b: float) -> float:
    """Multiply two numbers and return the result."""
    return a * b

print(agent.sync.call_tool("add", a=2, b=3))  # 5

# Inferred Schemas:
# input_schema: {
#     "type": "object",
#     "properties": {
#         "a": {"type": "integer"},
#         "b": {"type": "integer"}
#     },
#     "required": ["a", "b"],
#     "additionalProperties": False
# }
# output_schema: {"type": "integer"}
```

Synchronous functions, asynchronous functions, bound methods, and callable objects can all be passed directly to `add_tool()`. To reuse `add` on another agent, call `other_agent.add_tool(add)`. Registration inspects the callable without executing it; the registered wrapper is available as `agent.tools["add"]`.

Existing `Tool`, built-in, MCP, and custom tool objects retain their metadata and behavior when passed to `add_tool()`. For explicit schemas, tags, capabilities, or approval previews, create a configured `Tool.from_callable(add, ...)` first. See [Agent.add_tool](agent.md#agentadd_tool) for replacement rules.

### Agent.tool

<ApiReference
  kind="method"
  path="protolink.agents.Agent.tool"
  signature={`tool(
    name: str | ToolCallableT | None = None,
    description: str | None = None,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    examples: list[Any] | None = None,
    capabilities: list[str] | tuple[str, ...] | set[str] | None = None,
    action_builder: ActionBuilder | None = None,
) -> ToolCallableT | Callable[[ToolCallableT], ToolCallableT]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/agents/mixins.py#L783"
>

Wrap a Python callable in `Tool`, register it immediately on this Agent, and synchronize the corresponding advertised `AgentSkill`. The decorated name remains bound to the original function and retains its type signature, while the runtime wrapper is available through `agent.tools[name]`. `ToolCallableT` represents the decorated callable's type. Bare decoration, empty parentheses, explicit keywords, and the existing `@agent.tool("name", "description")` form are supported.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="Agent tool decorator parameters">
    <ApiField name="name" type="str | ToolCallableT | None" defaultValue="None">
      Stable public identifier, inferred from the function name when omitted. Bare decoration passes the callable here. Reusing an existing runtime name replaces the tool and its matching skill.
    </ApiField>
    <ApiField name="description" type="str | None" defaultValue="None">
      Selection guidance shown to the LLM and discovery clients. Defaults to the cleaned docstring, or <code>Call &lt;name&gt;.</code> when the function has none. Include the operation's purpose, prerequisites, and relevant side effects in your docstring or explicit description.
    </ApiField>
    <ApiField name="input_schema" type="dict[str, Any] | None" defaultValue="None">
      Explicit JSON Schema or legacy field map. <code>None</code> infers a schema from the decorated function's signature and type hints.
    </ApiField>
    <ApiField name="output_schema" type="dict[str, Any] | None" defaultValue="None">
      Explicit result schema. <code>None</code> infers it from the return annotation; it is advertised but does not validate the returned runtime value.
    </ApiField>
    <ApiField name="tags" type="list[str] | None" defaultValue="None">
      Discovery labels copied to the generated <code>AgentSkill</code>.
    </ApiField>
    <ApiField name="examples" type="list[Any] | None" defaultValue="None">
      Representative examples copied to the skill card.
    </ApiField>
    <ApiField name="capabilities" type="list[str] | tuple[str, ...] | set[str] | None" defaultValue="None">
      Authority required before Agent execution. The wrapper normalizes non-empty values and merges them into every prepared action.
    </ApiField>
    <ApiField name="action_builder" type="ActionBuilder | None" defaultValue="None">
      Optional sync or async builder for action metadata and approval-preview artifacts. It runs after argument validation and before policy evaluation.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="Agent tool decorator return value">
    <ApiField name="function or decorator" type="ToolCallableT | Callable[[ToolCallableT], ToolCallableT]">
      Bare decoration returns the original function; the configured form returns a decorator that registers and returns it unchanged. Direct Python calls bypass Agent authorization and approvals.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Registration timing">
  Registration occurs when Python evaluates the decorated function definition, not when the tool is first called. In <code>skills="auto"</code> mode the Agent card is updated at the same time.
</ApiCallout>

</ApiReference>

### JSON Schema and Runtime Validation

Tool schemas are first-class JSON Schema objects. Native tools infer nested schemas from Python type hints, dataclasses, enums, typed dictionaries, and Pydantic models. Before execution, Protolink validates and lightly coerces tool arguments against the schema, then applies Python annotation validation where available.

```python
from pydantic import BaseModel, Field

class BookingRequest(BaseModel):
    location: str
    guests: int = Field(gt=0)

@agent.tool(
    name="book_hotel",
    description="Book a hotel",
    examples=[{"booking": {"location": "Athens", "guests": 2}}],
)
async def book_hotel(booking: BookingRequest) -> dict[str, str]:
    return {"location": booking.location, "status": "confirmed"}
```

The inferred input schema is a JSON Schema object with a nested `booking` property. Runtime calls such as `{"booking": {"location": "Athens", "guests": "2"}}` are coerced before the function receives a `BookingRequest` instance. Missing required fields, unexpected fields, invalid enums, and incompatible scalar values return a structured tool error instead of reaching user code.

### Schema helper API

The helpers below are public for applications that build custom tool wrappers or want to inspect exactly what `Tool` will infer.

#### normalize_schema

<ApiReference
  kind="function"
  path="protolink.tools.normalize_schema"
  signature={`normalize_schema(
    schema: Any,
    title: str | None = None,
) -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/schema.py#L206"
>

Normalize a full JSON Schema, a Pydantic model, a Python annotation, or a legacy `{field: type}` map into one JSON Schema dictionary. Object schemas receive stable defaults for `properties`, `required`, and `additionalProperties`, and local `$ref` definitions are inlined for provider portability.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="normalize_schema parameters">
    <ApiField name="schema" type="Any" required>
      Supported schema representation. <code>None</code> becomes an empty closed object schema; dictionaries that already look like JSON Schema are copied before normalization.
    </ApiField>
    <ApiField name="title" type="str | None" defaultValue="None">
      Optional title written onto the returned top-level schema.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="normalize_schema return value">
    <ApiField name="schema" type="dict[str, Any]">
      New normalized schema dictionary. The input dictionary is not mutated.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### infer_input_schema

<ApiReference
  kind="function"
  path="protolink.tools.infer_input_schema"
  signature={`infer_input_schema(
    func: Callable[..., Any],
    *,
    title: str,
) -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/schema.py#L266"
>

Inspect a callable and build a closed object schema for its named parameters. `self`, `cls`, `*args`, and `**kwargs` are omitted; parameters without Python defaults become required and parameters with defaults include that value in their property schema.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="infer_input_schema parameters">
    <ApiField name="func" type="Callable[..., Any]" required>
      Function whose signature and resolved type hints describe tool input.
    </ApiField>
    <ApiField name="title" type="str" required>
      Required schema title, normally derived from the tool name.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="infer_input_schema return value">
    <ApiField name="schema" type="dict[str, Any]">
      JSON Schema object with <code>additionalProperties=False</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### infer_output_schema

<ApiReference
  kind="function"
  path="protolink.tools.infer_output_schema"
  signature={`infer_output_schema(
    func: Callable[..., Any],
    *,
    title: str,
) -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/schema.py#L299"
>

Convert a callable's resolved return annotation to JSON Schema. Missing or unresolvable annotations produce a permissive schema rather than inspecting or executing the function.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="infer_output_schema parameters">
    <ApiField name="func" type="Callable[..., Any]" required>
      Callable whose return type should be advertised.
    </ApiField>
    <ApiField name="title" type="str" required>
      Title added to the returned schema.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="infer_output_schema return value">
    <ApiField name="schema" type="dict[str, Any]">
      JSON Schema describing the annotated return value.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

#### validate_tool_args

<ApiReference
  kind="function"
  path="protolink.tools.validate_tool_args"
  signature={`validate_tool_args(
    args: dict[str, Any] | None,
    input_schema: dict[str, Any] | None,
    *,
    type_hints: dict[str, Any] | None = None,
    signature: inspect.Signature | None = None,
) -> dict[str, Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/schema.py#L478"
>

Validate and coerce untrusted keyword arguments before tool code runs. JSON Schema validation happens first, Python signature checks catch missing and unexpected fields next, and resolved annotations can finally reconstruct typed values through Pydantic `TypeAdapter`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="validate_tool_args parameters">
    <ApiField name="args" type="dict[str, Any] | None" required>
      Proposed arguments. <code>None</code> is normalized to an empty dictionary and the caller's mapping is copied.
    </ApiField>
    <ApiField name="input_schema" type="dict[str, Any] | None" required>
      Schema used for structural validation and conservative coercion of strings, numbers, booleans, arrays, and nested objects.
    </ApiField>
    <ApiField name="type_hints" type="dict[str, Any] | None" defaultValue="None">
      Resolved annotations keyed by parameter name. When supplied, matching values are validated and reconstructed after schema checks.
    </ApiField>
    <ApiField name="signature" type="inspect.Signature | None" defaultValue="None">
      Callable signature used to detect required and unexpected keyword fields. A callable accepting <code>**kwargs</code> permits additional names.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="validate_tool_args return value">
    <ApiField name="arguments" type="dict[str, Any]">
      New validated mapping, potentially containing coerced scalars or reconstructed annotated objects.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="validate_tool_args errors">
    <ApiField name="ValueError">
      Schema violations, missing fields, unexpected fields, incompatible scalar values, invalid enums or constants, and annotation-validation failures.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### Capabilities And Approval

Declare capabilities for operations that should participate in runtime policy. Capability names are extensible strings rather than a fixed coding or filesystem taxonomy.

```python
from protolink import Agent, ApprovalDecision, CapabilityPolicy

async def approve(request, context):
    return ApprovalDecision(approved=True, request_id=request.request_id)

agent = Agent(
    card,
    policy=CapabilityPolicy({"records.write": "require_approval"}),
    approval_handler=approve,
)

@agent.tool(
    name="publish_record",
    description="Publish one record",
    capabilities=["records.write"],
)
async def publish_record(record_id: str) -> dict[str, str]:
    return {"record_id": record_id, "status": "published"}
```

Policy is evaluated after argument validation and immediately before the callable runs. See [Runtime](runtime.md#capability-policy) for wildcard rules, `RunContext.permissions`, approval handlers, and preview artifacts.

Use `agent.call_tool_in_context(name, context, **arguments)` to supply explicit per-run permissions and approval context. `agent.call_tool()` and `agent.sync.call_tool()` create a fresh context and return the raw result. These direct calls do not register a task or create its lifecycle, telemetry, and persistence records; use `run_task(Task.create_tool_call(...))` when the full task boundary is needed.

### Tool Cancellation

Tools invoked by a running task participate in that task's live cancellation automatically. Protolink checks the token before authorization, before calling the tool, and after the awaited result returns. It also cancels the owning task, so an async tool normally receives `asyncio.CancelledError` at its current `await` point.

```python
@agent.tool(name="build_report", description="Build a report in stages")
async def build_report() -> str:
    data = await load_data()
    report = await render_report(data)
    await commit_report(report)
    return "committed"
```

Cancellation can interrupt the first two awaits, but it cannot undo a commit that an external system already accepted. Side-effecting tools should therefore delay irreversible commits, use transactional APIs, or forward cancellation to a subprocess or remote service that supports it.

Synchronous Python tools cannot be forcibly stopped safely. If they run on the event-loop thread, the cancellation request is processed only after they return. If an application moves them to a worker thread, the event loop remains responsive but the thread itself may continue. These limits are why Protolink defines cancellation as best-effort rather than a rollback guarantee.

### When to Use Native Tools

Native tools are ideal for:

- **Business logic**: Domain-specific operations like order processing, data validation
- **Data access**: Database queries, API calls, file operations
- **Computation**: Complex calculations, data transformations
- **System integration**: Interacting with internal services

---

## Tool Tags

Tools can be categorized using tags for better organization and discovery:

```python
@agent.tool(
    name="calculate", 
    description="Performs arithmetic calculations", 
    tags=["math", "utility"]
)
async def calculate(operation: str, a: float, b: float) -> float:
    """Perform basic arithmetic operations."""
    if operation == "add":
        return a + b
    elif operation == "subtract":
        return a - b
    elif operation == "multiply":
        return a * b
    elif operation == "divide":
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b
    else:
        raise ValueError(f"Unsupported operation: {operation}")


@agent.tool(
    name="search_documents", 
    description="Search internal documents", 
    tags=["search", "documents", "rag"]
)
async def search_documents(query: str, limit: int = 10) -> list[dict]:
    """Search the document database."""
    # Implementation here
    pass
```

Tags are automatically propagated to the agent's skills and can be used for:

- **Filtering**: Find tools by category
- **Discovery**: Help users understand available capabilities
- **Organization**: Group related tools together

---

## MCP Tools

Protolink integrates seamlessly with **MCP (Model Context Protocol)** servers, allowing you to use tools from external MCP-compatible services as if they were native tools.

### What is MCP?

The [Model Context Protocol](https://modelcontextprotocol.io/) is an open standard for connecting AI assistants to external tools and data sources. MCP servers can be:

- Local Python scripts running as subprocesses
- Remote web services exposing SSE endpoints
- Third-party tool providers

### MCPToolAdapter

The `MCPToolAdapter` class connects to MCP servers and exposes their tools as callables compatible with Protolink's `BaseTool` protocol.

#### Supported Transports

| Transport | Description | Use Case |
|-----------|-------------|----------|
| `stdio` | Local subprocess via stdin/stdout | Local Python/Node.js MCP servers |
| `sse` | Server-Sent Events over HTTP | Remote MCP web services |

#### Constructor

<ApiReference
  kind="class"
  path="protolink.tools.adapters.MCPToolAdapter"
  signature={`class MCPToolAdapter(
    transport: str = "stdio",
    *,
    command: str | None = None,
    args: list[str] | None = None,
    url: str | None = None,
    headers: dict[str, str] | None = None,
)`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/adapters/mcp_adapter.py#L96"
>

Store the connection configuration for an MCP server and provide discovery and wrapping helpers. Construction does not open a subprocess, network connection, or MCP session; each discovery or invocation operation creates and initializes a session for that operation.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="MCPToolAdapter constructor parameters">
    <ApiField name="transport" type="str" defaultValue={'"stdio"'}>
      MCP client transport. Supported values are <code>"stdio"</code> for a local subprocess and <code>"sse"</code> for a remote Server-Sent Events endpoint.
    </ApiField>
    <ApiField name="command" type="str | None" defaultValue="None">
      Executable launched for <code>stdio</code>, such as <code>"python"</code>, <code>"node"</code>, or an MCP server binary. It is required when the first stdio operation runs.
    </ApiField>
    <ApiField name="args" type="list[str] | None" defaultValue="None">
      Arguments passed unchanged to the stdio command. <code>None</code> becomes an empty list.
    </ApiField>
    <ApiField name="url" type="str | None" defaultValue="None">
      SSE endpoint required when the first <code>sse</code> operation runs.
    </ApiField>
    <ApiField name="headers" type="dict[str, str] | None" defaultValue="None">
      Headers forwarded by the SSE client, commonly for authentication. <code>None</code> becomes an empty dictionary.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="MCPToolAdapter errors">
    <ApiField name="ImportError">
      Importing <code>protolink.tools.adapters</code> fails when the optional MCP dependency is unavailable. Install <code>protolink[mcp]</code>.
    </ApiField>
    <ApiField name="ValueError">
      Discovery or invocation raises for an unknown transport, missing stdio command, or missing SSE URL. Configuration is validated lazily, not by the constructor.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Session lifetime">
  The current adapter does not keep one MCP session open across calls. It caches discovered metadata, but each uncached discovery or tool invocation opens, initializes, and closes its own stdio or SSE session.
</ApiCallout>

</ApiReference>

---

### Connecting to MCP Servers

#### Local MCP Server (stdio)

Connect to a local MCP server running as a Python script:

```python
from protolink.tools.adapters import MCPToolAdapter

# Connect to a local MCP server
adapter = MCPToolAdapter(
    transport="stdio",
    command="python",
    args=["path/to/mcp_server.py"]
)

# Or with a Node.js server
adapter = MCPToolAdapter(
    transport="stdio",
    command="node",
    args=["path/to/mcp_server.js"]
)
```

#### Remote MCP Server (SSE)

Connect to a remote MCP server over HTTP:

```python
from protolink.tools.adapters import MCPToolAdapter

# Connect to a remote MCP server
adapter = MCPToolAdapter(
    transport="sse",
    url="http://localhost:8080/sse"
)

# With authentication
adapter = MCPToolAdapter(
    transport="sse",
    url="https://api.example.com/mcp/sse",
    headers={"Authorization": "Bearer your-api-token"}
)
```

---

### Discovering Tools

#### list_tools()

Retrieve all available tools from the MCP server as dictionaries:

```python
tools = adapter.list_tools()

for tool in tools:
    print(f"Tool: {tool['name']}")
    print(f"  Description: {tool['description']}")
    print(f"  Input Schema: {tool['input_schema']}")
    print(f"  Input Types: {tool['input_types']}")
    print(f"  Callable: {tool['callable']}")
```

The returned dictionaries contain the MCP name, description, input schema, shallow Python input-type mapping, an output placeholder, and a synchronous callable. See [`MCPToolAdapter.list_tools`](#mcptooladapterlist_tools) for the exact result contract, caching behavior, and event-loop limitation.

#### get_tools()

Retrieve all tools as `BaseTool`-compatible objects:

```python
base_tools = adapter.get_tools()

for tool in base_tools:
    print(f"{tool.name}: {tool.description}")
    print(f"  Input Schema: {tool.input_schema}")
    # e.g., {"type": "object", "properties": {"location": {"type": "string"}}}
```

**Returns** a list of native Protolink `Tool` instances. Each tool:

- Has `name`, `description`, `input_schema` populated from the MCP server
- Has `tags=["mcp"]` to identify it as an MCP-sourced tool
- Can be directly registered on a Protolink agent via `agent.add_tool()`

#### print_tools()

Display all available tools in a human-readable format:

```python
adapter.print_tools()
```

**Output:**
```
🛠 Available MCP Tools:

🔹 Name       : add
   Description: Add two integers.
   Input Schema: {'properties': {'a': {'type': 'integer'}, 'b': {'type': 'integer'}}, ...}
   Input Types : {'a': <class 'int'>, 'b': <class 'int'>}

🔹 Name       : greet
   Description: Greet a person by name.
   Input Schema: {'properties': {'name': {'type': 'string'}}, ...}
   Input Types : {'name': <class 'str'>}
```

---

### Invoking Tools

There are multiple ways to invoke MCP tools, depending on whether you need synchronous or asynchronous execution:

#### Method 1: get_callable() - Synchronous Callable

Get a **synchronous** callable for a specific tool. Best for quick scripts and non-async contexts:

```python
# Get the synchronous callable
add = adapter.get_callable("add")

# Invoke with keyword arguments (no await needed)
result = add(a=5, b=7)
print(result)  # "12"
```

:::note[Sync vs Async]

`get_callable()` returns a synchronous function that uses `asyncio.run()` internally. This is simple but cannot be used inside an existing async context (it would cause a nested event loop error).

:::
#### Method 2: get_tools() - Native Protolink Tools (Async)

Get all tools as native Protolink `Tool` objects with **async** `__call__` methods:

```python
import asyncio

# Get all tools as native Tool objects
tools = adapter.get_tools()

# Find a specific tool
multiply = next(t for t in tools if t.name == "multiply")

# Invoke asynchronously
result = asyncio.run(multiply(a=5, b=7))
print(result)  # "35"
```

This is the **recommended approach** for:
- Registering tools on Protolink agents
- Using tools in async contexts
- Avoiding nested event loop issues

:::tip[Agent Integration]

`get_tools()` returns `Tool` objects that can be directly registered via `agent.add_tool(tool)`. The agent's async runtime will properly await tool calls.

:::
#### Method 3: wrap_tool() - Single BaseTool Instance

Wrap a specific tool as a `BaseTool`-compatible object:

```python
# Wrap the tool
add_tool = adapter.wrap_tool("add")

# Access metadata
print(add_tool.name)         # "add"
print(add_tool.description)  # "Add two integers."
print(add_tool.input_schema) # {"type": "object", "properties": {"a": {"type": "integer"}}, ...}

# Invoke asynchronously
import asyncio
result = asyncio.run(add_tool(a=5, b=7))
print(result)  # "12"
```

#### Method 4: Via list_tools() Callable

Use the **synchronous** callable directly from the tool dictionary:

```python
tools = adapter.list_tools()

# Find the tool you want
add_tool = next(t for t in tools if t['name'] == 'add')

# Invoke it (synchronous)
result = add_tool['callable'](a=5, b=7)
print(result)  # "12"
```

:::warning[Sync Callable Limitation]

The `callable` in `list_tools()` is synchronous and cannot be used inside an async context. For async usage, use `get_tools()` instead.

:::
---

### Registering MCP Tools on Agents

Once you have MCP tools, you can register them on a Protolink agent:

```python
from protolink.agents import Agent
from protolink.models import AgentCard
from protolink.tools.adapters import MCPToolAdapter

# Create the agent
agent_card = AgentCard(
    url="http://localhost:8020",
    name="mcp_agent", 
    description="Agent with MCP tools"
)
agent = Agent(card=agent_card, transport="http")

# Connect to MCP server
adapter = MCPToolAdapter(
    transport="stdio",
    command="python",
    args=["mcp_server.py"]
)

# Get all tools as native Protolink Tool objects
mcp_tools = adapter.get_tools()

# Register each tool with the agent
for tool in mcp_tools:
    agent.add_tool(tool)
```

:::tip[Native Tool Integration]

`get_tools()` returns native Protolink `Tool` objects with `tags=["mcp"]`, making them fully compatible with the agent system. No additional wrapping is needed.

:::
---

### Complete Example

Here's a complete example showing how to create an MCP server and use it with Protolink:

#### MCP Server (mcp_server.py)

```python
from mcp.server.fastmcp import FastMCP

# Create the MCP server
mcp = FastMCP(
    name="math-tools",
    instructions="Simple MCP server with math tools"
)

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b

@mcp.tool()
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b

@mcp.tool()
def greet(name: str) -> str:
    """Greet a person by name."""
    return f"Hello, {name}! 👋"

if __name__ == "__main__":
    mcp.run()
```

#### Protolink Client

```python
from protolink.tools.adapters import MCPToolAdapter

# Connect to the MCP server
adapter = MCPToolAdapter(
    transport="stdio",
    command="python",
    args=["mcp_server.py"]
)

# Discover available tools
print("Available tools:")
adapter.print_tools()

# Get tools as BaseTool objects
tools = adapter.get_tools()
print(f"\nFound {len(tools)} tools")

# Use the add tool
add = adapter.get_callable("add")
result = add(a=10, b=20)
print(f"\n10 + 20 = {result}")

# Use the greet tool
greet = adapter.get_callable("greet")
message = greet(name="World")
print(f"\n{message}")
```

**Output:**
```
Available tools:

🛠 Available MCP Tools:

🔹 Name       : add
   Description: Add two integers.
   ...

🔹 Name       : multiply
   Description: Multiply two integers.
   ...

🔹 Name       : greet
   Description: Greet a person by name.
   ...

Found 3 tools

10 + 20 = 30

Hello, World! 👋
```

---

## MCPToolAdapter API Reference

### MCPToolAdapter.list_tools

<ApiReference
  kind="method"
  path="protolink.tools.adapters.MCPToolAdapter.list_tools"
  signature={`list_tools(
    *,
    refresh: bool = False,
) -> list[dict]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/adapters/mcp_adapter.py#L283"
>

Discover tools synchronously and return metadata dictionaries. The first call opens an MCP session and caches the resulting list; later calls return the cached list object unless `refresh=True`.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="MCPToolAdapter list_tools parameters">
    <ApiField name="refresh" type="bool" defaultValue="False">
      Bypass cached discovery and replace it with a fresh server response.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="MCPToolAdapter list_tools result">
    <ApiField name="name" type="str">
      MCP tool identifier.
    </ApiField>
    <ApiField name="description" type="str">
      Server-provided description, normalized to an empty string when absent.
    </ApiField>
    <ApiField name="input_schema" type="dict[str, Any]">
      Original MCP <code>inputSchema</code>, or an empty dictionary.
    </ApiField>
    <ApiField name="input_types" type="dict[str, type]">
      Shallow mapping from top-level JSON Schema types to Python classes for display and introspection. Unsupported shapes become <code>Any</code>.
    </ApiField>
    <ApiField name="output" type="None">
      Reserved placeholder; the current adapter does not expose MCP output schemas.
    </ApiField>
    <ApiField name="callable" type="Callable[..., Any]">
      Synchronous closure for this tool. It uses <code>asyncio.run()</code> and opens a new MCP session per invocation.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="MCPToolAdapter list_tools errors">
    <ApiField name="RuntimeError">
      Calling this synchronous method inside an active event loop fails because it uses <code>asyncio.run()</code>.
    </ApiField>
    <ApiField name="MCP or transport error">
      Subprocess startup, SSE connection, initialization, protocol, and discovery failures propagate.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Mutable cache">
  The returned list and its dictionaries are the cached objects, not defensive copies. Treat them as read-only or use <code>refresh=True</code> to replace mutated cache state.
</ApiCallout>

</ApiReference>

### MCPToolAdapter.get_tool

<ApiReference
  kind="method"
  path="protolink.tools.adapters.MCPToolAdapter.get_tool"
  signature={`get_tool(
    tool_name: str,
) -> dict | None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/adapters/mcp_adapter.py#L336"
>

Find one discovered metadata dictionary by exact name. This is a linear search over `list_tools()` and therefore uses its cache and synchronous event-loop constraints.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="MCPToolAdapter get_tool parameters">
    <ApiField name="tool_name" type="str" required>
      Exact case-sensitive MCP tool name.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="MCPToolAdapter get_tool return value">
    <ApiField name="tool" type="dict | None">
      Cached metadata dictionary when found; otherwise <code>None</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### MCPToolAdapter.get_tools

<ApiReference
  kind="method"
  path="protolink.tools.adapters.MCPToolAdapter.get_tools"
  signature={`get_tools() -> list[Tool]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/adapters/mcp_adapter.py#L359"
>

Convert every discovered MCP definition into a native asynchronous `Tool`. Each call constructs a new wrapper list, while discovery metadata can come from the adapter cache.

<ApiSection title="Returns">
  <ApiFields ariaLabel="MCPToolAdapter get_tools return value">
    <ApiField name="tools" type="list[Tool]">
      Native tools with the MCP name, description, input schema, <code>output_schema=None</code>, and <code>tags=["mcp"]</code>. Their async callables open a fresh MCP session for each invocation.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Recommended for Agent">
  Register these wrappers with <code>agent.add_tool()</code>. Their asynchronous call path is compatible with Agent execution and does not nest <code>asyncio.run()</code>.
</ApiCallout>

</ApiReference>

### MCPToolAdapter.get_callable

<ApiReference
  kind="method"
  path="protolink.tools.adapters.MCPToolAdapter.get_callable"
  signature={`get_callable(
    tool_name: str,
) -> Callable[..., Any]`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/adapters/mcp_adapter.py#L455"
>

Create a synchronous closure that invokes the named MCP tool. The name is not checked against discovery at construction; the MCP server validates it when the closure runs.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="MCPToolAdapter get_callable parameters">
    <ApiField name="tool_name" type="str" required>
      Tool identifier sent to <code>session.call_tool()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="MCPToolAdapter get_callable return value">
    <ApiField name="callable" type="Callable[..., Any]">
      Keyword-only synchronous wrapper returning the first text content item when present, otherwise <code>None</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiCallout label="Event loops">
  The closure uses <code>asyncio.run()</code>. Do not call it from an asynchronous handler or notebook cell with an active event loop; use <code>get_tools()</code> there.
</ApiCallout>

</ApiReference>

### MCPToolAdapter.wrap_tool

<ApiReference
  kind="method"
  path="protolink.tools.adapters.MCPToolAdapter.wrap_tool"
  signature={`wrap_tool(
    tool_name: str,
) -> MCPToolAdapter`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/adapters/mcp_adapter.py#L543"
>

Discover one tool and return a new adapter configured to act as that asynchronous `BaseTool`. Connection settings and the metadata cache are shared by reference with the parent at wrapping time.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="MCPToolAdapter wrap_tool parameters">
    <ApiField name="tool_name" type="str" required>
      Exact tool name that must already be discoverable from the MCP server.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="MCPToolAdapter wrap_tool return value">
    <ApiField name="wrapped" type="MCPToolAdapter">
      New adapter with <code>name</code>, <code>description</code>, and <code>input_schema</code> populated. <code>output_schema</code> and <code>tags</code> remain <code>None</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="MCPToolAdapter wrap_tool errors">
    <ApiField name="ValueError">
      No discovered tool has the requested name.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### MCPToolAdapter.__call__

<ApiReference
  kind="async method"
  path="protolink.tools.adapters.MCPToolAdapter.__call__"
  signature={`async __call__(
    **kwargs,
) -> Any`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/adapters/mcp_adapter.py#L510"
>

Invoke the MCP tool represented by a wrapped adapter. A plain connection adapter has an empty `name` and cannot be called directly.

<ApiSection title="Parameters">
  <ApiFields ariaLabel="MCPToolAdapter call parameters">
    <ApiField name="**kwargs" type="Any">
      Arguments sent unchanged to the MCP server. This adapter path does not run ProtoLink's native <code>Tool.validate_args()</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Returns">
  <ApiFields ariaLabel="MCPToolAdapter call return value">
    <ApiField name="result" type="Any">
      Text from the first MCP content item when it has a <code>text</code> attribute; otherwise <code>None</code>.
    </ApiField>
  </ApiFields>
</ApiSection>

<ApiSection title="Raises">
  <ApiFields ariaLabel="MCPToolAdapter call errors">
    <ApiField name="ValueError">
      The adapter does not wrap a named tool.
    </ApiField>
    <ApiField name="MCP or transport error">
      Session and remote tool failures propagate.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

### MCPToolAdapter.print_tools

<ApiReference
  kind="method"
  path="protolink.tools.adapters.MCPToolAdapter.print_tools"
  signature={`print_tools() -> None`}
  source="https://github.com/nMaroulis/protolink/blob/main/protolink/tools/adapters/mcp_adapter.py#L599"
>

Print cached or freshly discovered names, descriptions, input schemas, and shallow Python input types to standard output.

<ApiSection title="Returns">
  <ApiFields ariaLabel="MCPToolAdapter print_tools return value">
    <ApiField name="None" type="None">
      Output is written for human inspection; no formatted string is returned.
    </ApiField>
  </ApiFields>
</ApiSection>

</ApiReference>

---

## Best Practices

### Built-in Tools

1. **Register selectively**: Built-ins are opt-in; add only the tools an agent needs.
2. **Configure policy**: Use `CapabilityPolicy` to allow, deny, or approval-gate `network.read` explicitly.
3. **Treat external data as untrusted**: Search results and fetched pages can contain incorrect or adversarial text.
4. **Use the Agent execution path**: Direct Tool calls are convenient for low-level tests but bypass Agent runtime controls.

### Tool Design

1. **Clear descriptions**: Write descriptions that help the LLM understand when to use each tool
2. **Typed parameters**: Use type hints for all parameters
3. **Error handling**: Raise clear exceptions for invalid inputs
4. **Single responsibility**: Each tool should do one thing well

### MCP Integration

1. **Connection reuse**: Create one `MCPToolAdapter` and reuse it for multiple tool calls
2. **Caching**: Use `list_tools()` without `refresh=True` to leverage caching
3. **Error handling**: Wrap tool calls in try/except for network failures
4. **Transport choice**: Use `stdio` for local servers, `sse` for remote services

### Agent Registration

1. **Selective registration**: Only register tools the agent actually needs
2. **Descriptive names**: Use clear, action-oriented names like `search_documents` not `do_search`
3. **Tag organization**: Use consistent tagging for related tools

---

## See Also

- [Agent Documentation](agent.md) - How agents use tools
- [LLM Documentation](llm.md) - How LLMs invoke tools via `infer()`
- [MCP Specification](https://modelcontextprotocol.io/) - Model Context Protocol details
