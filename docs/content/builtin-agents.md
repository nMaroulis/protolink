# Built-in Agents

Built-in agents are small, configurable classes using the standard [Agent API](agent.md). Developers
choose their models, instructions, tools, backends, policies, and application interfaces. The presets
reuse Agent's execution loop, invocation, streaming, state, storage, and transport behavior.

| Agent | Built-in behavior | Import |
| --- | --- | --- |
| [`Assistant`](#assistant) | Clock/calculator plus optional calendar, email, and user feedback | `from protolink import Assistant` |
| [`CodeAssistant`](#codeassistant) | Shell, Git, calculator, and optional user feedback | `from protolink import CodeAssistant` |
| [`EchoAgent`](#echoagent) | Currently inherits Agent unchanged | `from protolink.agents.builtins import EchoAgent` |

All three are exported from `protolink.agents.builtins`. The complete tool catalog, backend setup,
authentication requirements, and individual tool APIs are in [Built-in Tools](builtin-tools.md).

:::info[More agents are coming]

More built-in agents are coming. Future additions will stay small and configurable, using the same
Agent API and reusable tools so developers can adapt them to their own applications.

:::

## Quick start

```python
from protolink import Assistant, CodeAssistant, create_llm

assistant = Assistant(llm=create_llm("mock", default_response="Ready"))
print(await assistant.invoke("Hello"))

coder = CodeAssistant(cwd=".")  # No model is needed for direct tool calls.
result = await coder.call_tool("calculator", expression="(18 + 6) / 3")
```

Use `invoke()` for general conversation; `ask()` retains the existing knowledge/RAG contract.
Supply a separate model instance to concurrently running agents when the model retains mutable state.
Construction registers tools and validates configuration without contacting accounts or starting a server.

## Assistant

```python
from protolink import Assistant
from protolink.tools import Gmail, GoogleCalendar

assistant = Assistant(
    llm=model,  # Optional for direct call_tool usage.
    calendar=GoogleCalendar(token),  # Omit a service to exclude its tools.
    email=Gmail(token, sender="me@example.com"),
    ask_user=handle_question,  # Optional async user-feedback callback.
    allow_write=True,  # Calendar creation and email drafts.
    allow_send=True,  # Separately opt into email delivery.
    approval_handler=approve,  # Normal Agent approval callback.
    state=["conversation"],
)
```

`model`, `handle_question`, `approve`, and `token` are application-supplied dependencies.
Choose Google, Microsoft, IMAP/SMTP, or your own service adapters from the
[backend catalog](builtin-tools.md#calendar-and-email-backends). Clock and calculator
are always included. Reads and user questions are allowed by the preset's default policy; calendar
creation, drafts, and delivery require approval. Both write flags default to `False`. Omitting an
approval handler leaves approval-gated calls blocked by the existing runtime; it never auto-approves.
Question answers clarify intent; they do not authorize a write.

Pass a custom `card=AgentCard(...)` for a different name/URL. Other constructor keywords pass directly
to `Agent`, including `policy`, `system_prompt`, `transport`, `knowledge`, `storage`, and `run_store`.
A supplied policy replaces the preset policy. New capabilities are denied by the preset's default policy;
explicitly configure them when adding more tools.

## CodeAssistant

```python
from protolink import CodeAssistant

coder = CodeAssistant(
    llm=model,
    cwd="/absolute/workspace",
    env={"PATH": "/usr/bin:/bin"},
    ask_user=handle_question,
    allow_git_write=True,
    approval_handler=approve,
)
print(await coder.invoke("Inspect the changes and run the relevant tests."))
```

The preset includes `run_shell`, `git`, and `calculator`, plus `ask_user` when a callback is supplied.
Git reads and questions are allowed; shell commands and Git writes require approval. Git writes also
need `allow_git_write=True` (default `False`). Shell execution can mutate host resources even when
Git writes are disabled. A working directory does not provide filesystem or network isolation.

`env=None` supplies only `PATH=os.defpath`; it does not copy the parent environment. Configure
credentials and author identity explicitly when needed. Tool factories offer timeout, output-limit,
executable, and backend settings; replace a preset's tool with a configured factory for those options.
See [shell, Git, and user interaction](builtin-tools.md#shell-and-git-tools).

## EchoAgent

`EchoAgent` currently inherits `Agent` without overrides. It adds no tools, default prompt, policy,
or echo implementation; its constructor and behavior are those of `Agent`.

```python
from protolink import AgentCard
from protolink.agents.builtins import EchoAgent

agent = EchoAgent(AgentCard(name="example", description="Application-defined behavior", url="runtime://example"))
```

## Customization and restoration

`Assistant` and `CodeAssistant` are optional starting points. Register additional tools with
`add_tool()`, replace a tool with a configured factory, or compose the same capabilities directly on
an ordinary `Agent`. Their default policies deny capabilities beyond the preset, so explicitly update
the policy when adding capabilities. A supplied policy replaces the preset policy.

Both accept `card` to change identity and standard Agent keyword options such as `system_prompt`,
`approval_handler`, `transport`, `state`, `storage`, and `run_store`. Configure callbacks in your own
application. User feedback clarifies intent; approval remains a separate policy decision.

Configured backends, credentials, and callbacks are not serialized. Restore configurations through
`Agent.from_dict/from_yaml`, then re-register the configured tools and policies as needed. The
[Tool catalog](builtin-tools.md#registration-and-policy) explains the parameterless/configured distinction.

## Offline example

```bash
python examples/builtin_assistants.py
```

[`builtin_assistants.py`](https://github.com/nMaroulis/protolink/blob/main/examples/builtin_assistants.py)
exercises Assistant and CodeAssistant, including model question/answer continuation, shell/Git,
calendar/email, clock, and calculator. It uses a temporary repository, a mock model, and in-memory
services. Its automatic approval callback is specific to the demo. See the
[tool examples](builtin-tools.md#examples) for the general-purpose tools and concrete service backends.
