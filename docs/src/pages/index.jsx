import Link from "@docusaurus/Link";
import Layout from "@theme/Layout";
import useBaseUrl from "@docusaurus/useBaseUrl";
import clsx from "clsx";
import { useEffect, useMemo, useRef, useState } from "react";
import styles from "./index.module.css";

const pathways = [
  {
    eyebrow: "Start",
    title: "Create an agent",
    body: "Define an AgentCard, plug in an LLM or tools, and start a local or networked agent with minimal boilerplate.",
    to: "/docs/getting-started",
  },
  {
    eyebrow: "Protocol",
    title: "Understand the A2A core",
    body: "Work with AgentCard, Task, Message, Part, Artifact, and TaskState as the shared language between agents.",
    to: "/docs/concept",
  },
  {
    eyebrow: "Capabilities",
    title: "Add LLMs and tools",
    body: "Use API, server, or local models; expose native Python tools; and adapt MCP tools into the same agent surface.",
    to: "/docs/llm",
  },
  {
    eyebrow: "Systems",
    title: "Compose flows and meshes",
    body: "Build coordinators, workers, deterministic flows, registry-backed discovery, and multi-agent examples.",
    to: "/docs/examples",
  },
];

const agentShapes = [
  ["Tool-only", "Deterministic capabilities without an LLM."],
  ["LLM-only", "Reasoning, transformation, and conversation."],
  ["Hybrid", "LLM decisions with typed tool execution."],
  ["Coordinator", "Discovery, delegation, and multi-agent routing."],
];

const foundations = [
  [
    "Identity",
    "AgentCard declares name, URL, transport, skills, tags, formats, and security schemes.",
  ],
  [
    "Work exchange",
    "Tasks carry Messages, Parts, Artifacts, state, and metadata across local or remote boundaries.",
  ],
  [
    "Capability surface",
    "Native tools, MCP adapters, schemas, examples, LLMs, and peer agents become discoverable contracts.",
  ],
  [
    "Deployment path",
    "Start in-process with RuntimeTransport, then move the same agent to HTTP, SSE JSON-RPC, WebSocket, or gRPC.",
  ],
];

const moduleDefinitions = [
  {
    id: "auth",
    label: "Auth",
    detail: "security policy",
    badge: "AU",
    tone: "blue",
    options: [
      {
        id: "api-key",
        label: "API key",
        kind: "service",
        imports: ["from protolink.security import APIKeyAuth"],
        setup: ['auth = APIKeyAuth(valid_keys={"service-key": ["write"]})'],
        agentArg: "authenticator=auth",
      },
      {
        id: "bearer",
        label: "Bearer JWT",
        kind: "http",
        imports: ["from protolink.security import BearerTokenAuth"],
        setup: [
          'auth = BearerTokenAuth(secret="agent-secret", issuer="https://auth.example.com")',
        ],
        agentArg: "authenticator=auth",
      },
      {
        id: "basic",
        label: "Basic",
        kind: "http",
        imports: ["from protolink.security import BasicAuth"],
        setup: ['auth = BasicAuth(valid_credentials={"agent": "secret"})'],
        agentArg: "authenticator=auth",
      },
      {
        id: "oauth2",
        label: "OAuth2",
        kind: "delegation",
        imports: ["from protolink.security import OAuth2DelegationAuth"],
        setup: [
          "auth = OAuth2DelegationAuth(",
          '    exchange_endpoint="https://auth.example.com/exchange",',
          '    client_id="agent-client",',
          '    client_secret="secret",',
          ")",
        ],
        agentArg: "authenticator=auth",
      },
    ],
  },
  {
    id: "llm",
    label: "LLM",
    detail: "model provider",
    badge: "LM",
    tone: "green",
    options: [
      {
        id: "openai",
        label: "OpenAI",
        kind: "api",
        imports: ["from protolink.llms.api import OpenAILLM"],
        agentArg: 'llm=OpenAILLM(model="gpt-4o-mini")',
      },
      {
        id: "anthropic",
        label: "Anthropic",
        kind: "api",
        imports: ["from protolink.llms.api import AnthropicLLM"],
        agentArg: 'llm=AnthropicLLM(model="claude-3-5-sonnet-latest")',
      },
      {
        id: "gemini",
        label: "Gemini",
        kind: "api",
        imports: ["from protolink.llms.api import GeminiLLM"],
        agentArg: 'llm=GeminiLLM(model="gemini-1.5-pro")',
      },
      {
        id: "deepseek",
        label: "DeepSeek",
        kind: "api",
        imports: ["from protolink.llms.api import DeepSeekLLM"],
        agentArg: 'llm=DeepSeekLLM(model="deepseek-chat")',
      },
      {
        id: "grok",
        label: "Grok",
        kind: "api",
        imports: ["from protolink.llms.api import GrokLLM"],
        agentArg: 'llm=GrokLLM(model="grok-2")',
      },
      {
        id: "huggingface",
        label: "Hugging Face",
        kind: "api",
        imports: ["from protolink.llms.api import HuggingFaceLLM"],
        agentArg:
          'llm=HuggingFaceLLM(model="meta-llama/Llama-3.1-8B-Instruct")',
      },
      {
        id: "ollama",
        label: "Ollama",
        kind: "server",
        imports: ["from protolink.llms.server import OllamaLLM"],
        agentArg:
          'llm=OllamaLLM(base_url="http://localhost:11434", model="gemma4:e4b")',
      },
      {
        id: "lmstudio",
        label: "LM Studio",
        kind: "server",
        imports: ["from protolink.llms.server import LMStudioLLM"],
        agentArg: 'llm=LMStudioLLM(model="local-model")',
      },
      {
        id: "openai-compatible",
        label: "OpenAI-compatible",
        kind: "server",
        imports: ["from protolink.llms.server import OpenAICompatibleLLM"],
        agentArg:
          'llm=OpenAICompatibleLLM(base_url="http://localhost:1234/v1", model="local-model")',
      },
      {
        id: "llamacpp-server",
        label: "llama.cpp server",
        kind: "server",
        imports: ["from protolink.llms.server import LlamaCPPServerLLM"],
        agentArg:
          'llm=LlamaCPPServerLLM(base_url="http://localhost:8080", model="local-model")',
      },
      {
        id: "llamacpp-local",
        label: "llama.cpp local",
        kind: "local",
        imports: [
          "from protolink.llms.local.llamacpp_client import LlamaCPPLocalLLM",
        ],
        agentArg: 'llm=LlamaCPPLocalLLM(model="./models/model.gguf")',
      },
    ],
  },
  {
    id: "tools",
    label: "Tool",
    detail: "capability",
    badge: "TL",
    tone: "yellow",
    options: [
      {
        id: "native",
        label: "Native function",
        kind: "@agent.tool",
        after: [
          '@agent.tool(name="lookup_docs")',
          "async def lookup_docs(query: str) -> str:",
          '    return "source-cited answer"',
        ],
      },
      {
        id: "mcp-stdio",
        label: "MCP stdio",
        kind: "adapter",
        imports: ["from protolink.tools.adapters import MCPToolAdapter"],
        after: [
          'mcp_adapter = MCPToolAdapter(transport="stdio", command="python", args=["mcp_server.py"])',
          "for tool in mcp_adapter.get_tools():",
          "    agent.add_tool(tool)",
        ],
      },
      {
        id: "mcp-sse",
        label: "MCP SSE",
        kind: "adapter",
        imports: ["from protolink.tools.adapters import MCPToolAdapter"],
        after: [
          'mcp_adapter = MCPToolAdapter(transport="sse", url="https://api.example.com/mcp/sse")',
          "for tool in mcp_adapter.get_tools():",
          "    agent.add_tool(tool)",
        ],
      },
      {
        id: "tool-wrapper",
        label: "Tool wrapper",
        kind: "schema",
        imports: ["from protolink.tools import Tool"],
        setup: [
          "async def lookup_docs(query: str) -> str:",
          '    return "source-cited answer"',
        ],
        after: [
          "agent.add_tool(Tool(",
          '    name="lookup_docs",',
          '    description="Search project documentation.",',
          "    input_schema=None,",
          "    output_schema=None,",
          '    tags=["docs"],',
          "    func=lookup_docs,",
          "))",
        ],
      },
    ],
  },
  {
    id: "telemetry",
    label: "Telemetry",
    detail: "observability",
    badge: "TM",
    tone: "purple",
    options: [
      {
        id: "local",
        label: "Local trace",
        kind: "jsonl",
        imports: ["from protolink.telemetry import LocalTraceTelemetry"],
        agentArg: 'telemetry=LocalTraceTelemetry(path="traces.jsonl")',
      },
      {
        id: "langsmith",
        label: "LangSmith",
        kind: "hosted",
        imports: ["from protolink.telemetry import LangSmithTelemetry"],
        agentArg: 'telemetry=LangSmithTelemetry(project_name="assistant")',
      },
      {
        id: "langfuse",
        label: "Langfuse",
        kind: "hosted",
        imports: ["from protolink.telemetry import LangfuseTelemetry"],
        agentArg: "telemetry=LangfuseTelemetry()",
      },
      {
        id: "multi",
        label: "Multi",
        kind: "fan-out",
        imports: [
          "from protolink.telemetry import LocalTraceTelemetry, MultiTelemetry",
        ],
        agentArg:
          'telemetry=MultiTelemetry([LocalTraceTelemetry(path="traces.jsonl")])',
      },
    ],
  },
  {
    id: "storage",
    label: "Storage",
    detail: "state store",
    badge: "DB",
    tone: "orange",
    options: [
      {
        id: "sqlite",
        label: "SQLite",
        kind: "durable",
        imports: ["from protolink.storage import SQLiteStorage"],
        agentArg: 'storage=SQLiteStorage("agent.db", namespace="assistant")',
      },
      {
        id: "memory",
        label: "In-memory",
        kind: "ephemeral",
        imports: ["from protolink.storage import InMemoryStorage"],
        agentArg: "storage=InMemoryStorage()",
      },
      {
        id: "run-store",
        label: "SQLite run store",
        kind: "runs",
        imports: ["from protolink.storage import SQLiteRunStore"],
        setup: ['run_store = SQLiteRunStore("runs.db")'],
      },
    ],
  },
  {
    id: "registry",
    label: "Registry",
    detail: "discovery",
    badge: "RG",
    tone: "pink",
    options: [
      {
        id: "http-registry",
        label: "HTTP registry",
        kind: "remote",
        imports: ["from protolink.discovery import Registry"],
        agentArg:
          'registry=Registry(url="http://127.0.0.1:9000", transport="http")',
      },
      {
        id: "runtime-registry",
        label: "Runtime registry",
        kind: "local",
        imports: ["from protolink.discovery import Registry"],
        agentArg:
          'registry=Registry(url="runtime://registry", transport="runtime")',
      },
    ],
  },
  {
    id: "transport",
    label: "Transport",
    detail: "choose I/O",
    badge: "IO",
    tone: "cyan",
    options: [
      {
        id: "http",
        label: "HTTP",
        kind: "network",
        cardUrl: "http://127.0.0.1:8000",
        agentArg: 'transport="http"',
      },
      {
        id: "runtime",
        label: "Runtime",
        kind: "in-process",
        cardUrl: "runtime://assistant",
        agentArg: 'transport="runtime"',
      },
      {
        id: "websocket",
        label: "WebSockets",
        kind: "duplex",
        cardUrl: "ws://127.0.0.1:8000",
        agentArg: 'transport="websocket"',
      },
      {
        id: "grpc",
        label: "gRPC",
        kind: "rpc",
        cardUrl: "grpc://127.0.0.1:8000",
        agentArg: 'transport="grpc"',
      },
      {
        id: "jsonrpc",
        label: "JSON-RPC",
        kind: "sse",
        cardUrl: "http://127.0.0.1:8000",
        agentArg: 'transport="json-rpc"',
      },
    ],
  },
  {
    id: "logging",
    label: "Logging",
    detail: "events",
    badge: "LG",
    tone: "gray",
    options: [
      {
        id: "file-json",
        label: "File JSON",
        kind: "structured",
        imports: ["from protolink.logging import FileLogger"],
        agentArg: 'logger=FileLogger("agent_activity.log", extension="json")',
      },
      {
        id: "console",
        label: "Console",
        kind: "stdout",
        imports: ["from protolink.logging import ConsoleLogger"],
        agentArg: 'logger=ConsoleLogger(name="assistant")',
      },
      {
        id: "quiet",
        label: "Quiet",
        kind: "silent",
        imports: ["from protolink.logging import QuietLogger"],
        agentArg: "logger=QuietLogger()",
      },
    ],
  },
];

const plugModules = [...moduleDefinitions].sort((left, right) => {
  if (left.id === "transport") {
    return -1;
  }

  if (right.id === "transport") {
    return 1;
  }

  return 0;
});

const defaultModuleOptions = Object.fromEntries(
  plugModules.map((module) => [module.id, module.options[0].id]),
);
const initialActiveIds = ["transport"];

const pythonKeywords = new Set([
  "async",
  "def",
  "False",
  "for",
  "from",
  "import",
  "in",
  "None",
  "return",
  "True",
]);

function selectedModuleOption(module, selectedOptions) {
  return (
    module.options.find((option) => option.id === selectedOptions[module.id]) ??
    module.options[0]
  );
}

function selectedTransportOption(activeModules, selectedOptions) {
  const transportModule = plugModules.find(
    (module) => module.id === "transport",
  );

  if (
    !transportModule ||
    !activeModules.some((module) => module.id === "transport")
  ) {
    return {
      cardUrl: "runtime://assistant",
    };
  }

  return selectedModuleOption(transportModule, selectedOptions);
}

function tokenClassName(token, segment, endIndex) {
  if (token.startsWith("@")) {
    return styles.syntaxDecorator;
  }

  if (token.startsWith('"') || token.startsWith("'")) {
    return styles.syntaxString;
  }

  if (pythonKeywords.has(token)) {
    return styles.syntaxKeyword;
  }

  if (/^\d/.test(token)) {
    return styles.syntaxNumber;
  }

  if (/^[=]$/.test(token)) {
    return styles.syntaxOperator;
  }

  if (/^[()[\]{}.,:]$/.test(token)) {
    return styles.syntaxPunctuation;
  }

  const rest = segment.slice(endIndex);
  const nextNonSpace = rest.match(/\S/)?.[0];

  if (nextNonSpace === "=") {
    return styles.syntaxArgument;
  }

  if (/^[A-Z]/.test(token)) {
    return styles.syntaxClass;
  }

  if (nextNonSpace === "(") {
    return styles.syntaxFunction;
  }

  return styles.syntaxPlain;
}

function renderHighlightedLine(line, lineIndex) {
  const commentIndex = line.indexOf("#");
  const source = commentIndex >= 0 ? line.slice(0, commentIndex) : line;
  const comment = commentIndex >= 0 ? line.slice(commentIndex) : "";
  const tokens = [];
  const tokenPattern =
    /(@[A-Za-z_][\w.]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b[A-Za-z_]\w*\b|\b\d+(?:\.\d+)?\b|[=()[\]{}.,:])/g;
  let cursor = 0;
  let match;

  while ((match = tokenPattern.exec(source)) !== null) {
    const [token] = match;
    const start = match.index;
    const end = start + token.length;

    if (start > cursor) {
      tokens.push(source.slice(cursor, start));
    }

    tokens.push(
      <span
        className={tokenClassName(token, source, end)}
        key={`${lineIndex}-${start}`}
      >
        {token}
      </span>,
    );
    cursor = end;
  }

  if (cursor < source.length) {
    tokens.push(source.slice(cursor));
  }

  if (comment) {
    tokens.push(
      <span className={styles.syntaxComment} key={`${lineIndex}-comment`}>
        {comment}
      </span>,
    );
  }

  return tokens;
}

function renderHighlightedCode(code) {
  return code
    .split("\n")
    .flatMap((line, lineIndex, lines) => [
      ...renderHighlightedLine(line, lineIndex),
      lineIndex < lines.length - 1 ? "\n" : "",
    ]);
}

function PathwayCard({ pathway }) {
  return (
    <Link className={styles.pathwayCard} to={pathway.to}>
      <span>{pathway.eyebrow}</span>
      <h3>{pathway.title}</h3>
      <p>{pathway.body}</p>
    </Link>
  );
}

function buildAgentCode(activeModules, selectedOptions) {
  const imports = new Set(["from protolink import Agent, AgentCard"]);
  const setupLines = [];
  const transportOption = selectedTransportOption(
    activeModules,
    selectedOptions,
  );
  const constructorArgs = [
    `card=AgentCard(name="assistant", description="Composable protocol task agent", url="${transportOption.cardUrl}")`,
  ];
  const afterLines = [];

  activeModules.forEach((module) => {
    const resolvedModule = selectedModuleOption(module, selectedOptions);

    resolvedModule.imports?.forEach((line) => imports.add(line));
    resolvedModule.setup?.forEach((line) => setupLines.push(line));

    if (resolvedModule.agentArg) {
      constructorArgs.push(resolvedModule.agentArg);
    }

    resolvedModule.after?.forEach((line) => afterLines.push(line));
  });

  return [
    ...Array.from(imports),
    ...(setupLines.length ? ["", ...setupLines] : []),
    "",
    "agent = Agent(",
    ...constructorArgs.map((arg) => `    ${arg},`),
    ")",
    ...(afterLines.length ? ["", ...afterLines] : []),
    "",
    "agent.start()",
  ].join("\n");
}

function PluggableAgent({ logo }) {
  const [activeIds, setActiveIds] = useState(initialActiveIds);
  const [focusedModuleId, setFocusedModuleId] = useState("transport");
  const [selectedOptions, setSelectedOptions] = useState(defaultModuleOptions);
  const [streamedCode, setStreamedCode] = useState(() =>
    buildAgentCode(
      plugModules.filter((module) => initialActiveIds.includes(module.id)),
      defaultModuleOptions,
    ),
  );
  const streamTimer = useRef();
  const focusedModule =
    plugModules.find((module) => module.id === focusedModuleId) ??
    plugModules[0];
  const focusedOption = selectedModuleOption(focusedModule, selectedOptions);
  const activeModules = useMemo(
    () => plugModules.filter((module) => activeIds.includes(module.id)),
    [activeIds],
  );
  const code = useMemo(
    () => buildAgentCode(activeModules, selectedOptions),
    [activeModules, selectedOptions],
  );

  useEffect(() => {
    if (streamTimer.current) {
      window.clearInterval(streamTimer.current);
    }

    let index = 0;
    const step = Math.max(3, Math.ceil(code.length / 120));
    setStreamedCode("");

    streamTimer.current = window.setInterval(() => {
      index = Math.min(code.length, index + step);
      setStreamedCode(code.slice(0, index));

      if (index >= code.length) {
        window.clearInterval(streamTimer.current);
      }
    }, 16);

    return () => {
      if (streamTimer.current) {
        window.clearInterval(streamTimer.current);
      }
    };
  }, [code]);

  function toggleModule(id = focusedModuleId) {
    setActiveIds((current) =>
      current.includes(id)
        ? current.filter((activeId) => activeId !== id)
        : [...current, id],
    );
  }

  function chooseModule(id) {
    setFocusedModuleId(id);
  }

  function chooseOption(optionId) {
    setSelectedOptions((current) => ({
      ...current,
      [focusedModule.id]: optionId,
    }));
    setActiveIds((current) =>
      current.includes(focusedModule.id)
        ? current
        : [...current, focusedModule.id],
    );
  }

  return (
    <div
      className={styles.composerShell}
      aria-label="Pluggable ProtoLink agent module builder"
    >
      <div className={styles.composerTopbar}>
        <div className={styles.terminalDots} aria-hidden="true">
          <i />
          <i />
          <i />
        </div>
        <span>~/protolink/compose</span>
        <strong>
          {activeModules.length
            ? `${activeModules.length} module${activeModules.length === 1 ? "" : "s"}`
            : "base agent"}
        </strong>
      </div>

      <div className={styles.composerBody}>
        <aside className={styles.moduleExplorer} aria-label="Agent modules">
          <div className={styles.agentBadge}>
            <img src={logo} alt="" />
            <div>
              <strong>agent.py</strong>
              <span>{activeModules.length ? "configured" : "clean slate"}</span>
            </div>
          </div>

          <div className={styles.moduleList}>
            {plugModules.map((module) => {
              const active = activeIds.includes(module.id);
              const focused = module.id === focusedModule.id;
              const option = selectedModuleOption(module, selectedOptions);

              return (
                <button
                  aria-current={focused ? "true" : undefined}
                  aria-pressed={active}
                  className={clsx(
                    styles.moduleEntry,
                    focused && styles.moduleEntryFocused,
                    active && styles.moduleEntryActive,
                  )}
                  data-tone={module.tone}
                  key={module.id}
                  onClick={() => chooseModule(module.id)}
                  type="button"
                >
                  <span className={styles.moduleBullet} />
                  <span className={styles.moduleEntryText}>
                    <strong>{module.label}</strong>
                    <small>{option.label}</small>
                  </span>
                  <span className={styles.moduleFile}>.py</span>
                </button>
              );
            })}
          </div>
        </aside>

        <section
          className={styles.optionInspector}
          data-tone={focusedModule.tone}
          aria-live="polite"
        >
          <div className={styles.optionHeader}>
            <div>
              <span>module/{focusedModule.id}</span>
              <strong>{focusedModule.label}</strong>
              <small>{focusedModule.detail}</small>
            </div>
            <button
              className={clsx(
                styles.powerButton,
                activeIds.includes(focusedModule.id) &&
                  styles.powerButtonActive,
              )}
              onClick={() => toggleModule()}
              type="button"
            >
              {activeIds.includes(focusedModule.id) ? "on" : "off"}
            </button>
          </div>

          <div className={styles.optionStack}>
            {focusedModule.options.map((option, index) => {
              const selected = option.id === focusedOption.id;

              return (
                <button
                  aria-pressed={selected}
                  className={clsx(
                    styles.optionCommand,
                    selected && styles.optionCommandActive,
                  )}
                  key={option.id}
                  onClick={() => chooseOption(option.id)}
                  type="button"
                >
                  <span className={styles.optionLine}>
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className={styles.optionName}>{option.label}</span>
                  <span className={styles.optionKind}>{option.kind}</span>
                </button>
              );
            })}
          </div>
        </section>

        <section
          className={styles.codeEditor}
          aria-label="Generated ProtoLink agent code"
        >
          <div className={styles.editorTitlebar}>
            <span>composition.py</span>
            <strong>
              {focusedModule.label}: {focusedOption.label}
            </strong>
          </div>
          <pre>
            <code>
              {renderHighlightedCode(streamedCode)}
              <span className={styles.editorCaret} />
            </code>
          </pre>
        </section>
      </div>
    </div>
  );
}

export default function Home() {
  const logo = useBaseUrl("/img/logo_sm.png");

  return (
    <Layout
      title="A2A-native autonomous agent systems"
      description="ProtoLink documentation for autonomous agents, A2A protocol objects, LLMs, tools, transports, discovery, flows, and production-ready multi-agent systems."
    >
      <main className={styles.page}>
        <section className={styles.hero}>
          <div className={styles.heroInner}>
            <div className={styles.heroCopy}>
              <p className={styles.kicker}>A2A-native Python framework</p>
              <h1>
                Build autonomous agents that communicate through protocol-native
                tasks.
              </h1>
              <p className={styles.lede}>
                ProtoLink helps you build distributed, LLM-powered agent systems
                where every agent is an entity with identity, tools, optional
                memory, transport, discovery, and a clean task contract.
              </p>
              <p className={styles.positioning}>
                Focus on your agent logic, let Protolink handle communication,
                LLM & Tool integration, authentication, telemetry, logging and
                storage for you.
              </p>
              <div className={styles.heroActions}>
                <Link
                  className={clsx(
                    "button button--primary",
                    styles.primaryButton,
                  )}
                  to="/docs/getting-started"
                >
                  Start building
                </Link>
                <Link
                  className={clsx(
                    "button button--secondary",
                    styles.secondaryButton,
                  )}
                  to="/docs/concept"
                >
                  Understand the model
                </Link>
                <Link className={styles.ghostLink} to="/docs/whitepaper">
                  Read the whitepaper
                </Link>
              </div>
            </div>
            <div className={styles.heroComposer}>
              <div className={styles.composerCue}>
                <span className={styles.cueArrows} aria-hidden="true">
                  <i />
                  <i />
                </span>
                <span className={styles.cueLabel}>Try it here</span>
                <strong>
                  Choose a module, pick an implementation, and watch the agent
                  code assemble.
                </strong>
                <span className={styles.cueArrows} aria-hidden="true">
                  <i />
                  <i />
                </span>
              </div>
              <PluggableAgent logo={logo} />
            </div>
          </div>
        </section>

        <section className={styles.pathways} aria-labelledby="pathways">
          <div className={styles.sectionHeader}>
            <span>Documentation paths</span>
            <h2 id="pathways">
              Start from the part of the system you are building.
            </h2>
          </div>
          <div className={styles.pathwayGrid}>
            {pathways.map((pathway) => (
              <PathwayCard key={pathway.title} pathway={pathway} />
            ))}
          </div>
        </section>

        <section className={styles.agentSection}>
          <div>
            <div className={styles.sectionHeader}>
              <span>Design thesis</span>
              <h2>Agents are entities, not functions.</h2>
            </div>
            <p>
              An agent can receive work, initiate work, discover peers, expose
              capabilities, call its model, stream progress, and shut down
              cleanly. The model is one pluggable module inside that entity,
              alongside tools, transports, state, telemetry, authentication,
              logging, and policy.
            </p>
          </div>
          <div className={styles.shapeGrid}>
            {agentShapes.map(([title, body]) => (
              <div className={styles.shapeCard} key={title}>
                <strong>{title}</strong>
                <span>{body}</span>
              </div>
            ))}
          </div>
        </section>

        <section className={styles.foundationSection}>
          <div className={styles.sectionHeader}>
            <span>What stays stable</span>
            <h2>A small protocol core, surrounded by swappable modules.</h2>
          </div>
          <div className={styles.foundationGrid}>
            {foundations.map(([title, body]) => (
              <div className={styles.foundationCard} key={title}>
                <strong>{title}</strong>
                <p>{body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className={styles.referenceBand}>
          <div>
            <span>From prototype to mesh</span>
            <h2>
              Build one agent, then let the same contracts scale to a system.
            </h2>
            <p>
              The docs cover the full surface: agents, clients, LLMs, tools,
              transports, registry discovery, state, storage, telemetry,
              structured flows, examples, and the runtime controls that make
              production behavior inspectable.
            </p>
          </div>
          <Link className={styles.referenceLink} to="/docs">
            Open the docs index
          </Link>
        </section>
      </main>
    </Layout>
  );
}
