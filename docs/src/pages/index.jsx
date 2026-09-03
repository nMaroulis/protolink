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
    id: "tls",
    label: "TLS",
    detail: "transport security",
    badge: "TS",
    tone: "blue",
    options: [
      {
        id: "server-tls",
        label: "TLS",
        kind: "encrypted",
        imports: ["from protolink import TLSConfig"],
        setup: [
          "tls = TLSConfig(",
          '    certfile="certs/agent.pem",',
          '    keyfile="certs/agent-key.pem",',
          '    cafile="certs/ca.pem",',
          ")",
        ],
      },
      {
        id: "mutual-tls",
        label: "Mutual TLS",
        kind: "peer identity",
        imports: ["from protolink import TLSConfig"],
        setup: [
          "tls = TLSConfig(",
          '    certfile="certs/agent.pem",',
          '    keyfile="certs/agent-key.pem",',
          '    cafile="certs/ca.pem",',
          "    require_client_cert=True,",
          ")",
        ],
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
        id: "callable",
        label: "Existing function",
        kind: "add_tool",
        setup: [
          "def lookup_docs(query: str) -> str:",
          '    """Search project documentation."""',
          '    return "source-cited answer"',
        ],
        after: ["agent.add_tool(lookup_docs)"],
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
    id: "rag",
    label: "RAG",
    detail: "grounded knowledge",
    badge: "KB",
    tone: "teal",
    options: [
      {
        id: "memory",
        label: "In-memory knowledge",
        kind: "local",
        imports: ["from protolink import create_knowledge"],
        setup: [
          "knowledge = create_knowledge(",
          '    "memory",',
          '    name="product_docs",',
          '    description="product manuals and troubleshooting guides",',
          '    sources=["docs/"],',
          ")",
        ],
        agentArg: "knowledge=knowledge",
      },
      {
        id: "sqlite",
        label: "SQLite knowledge",
        kind: "persistent",
        imports: ["from protolink import create_knowledge"],
        setup: [
          "knowledge = create_knowledge(",
          '    "sqlite",',
          '    path="knowledge.db",',
          '    namespace="production",',
          '    name="product_docs",',
          '    sources=["docs/"],',
          ")",
        ],
        agentArg: "knowledge=knowledge",
      },
      {
        id: "custom",
        label: "Existing retriever",
        kind: "adapter",
        imports: ["from protolink import Knowledge"],
        setup: [
          "async def search_company_docs(query: str, *, k: int = 5, where=None):",
          "    return await company_search(query, limit=k, filters=where)",
          "",
          "knowledge = Knowledge.from_callable(",
          "    search_company_docs,",
          '    name="company_docs",',
          '    description="private company documentation",',
          ")",
        ],
        agentArg: "knowledge=knowledge",
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
        secureCardUrl: "https://127.0.0.1:8000",
        transportClass: "HTTPTransport",
        agentArg: 'transport="http"',
      },
      {
        id: "runtime",
        label: "Runtime",
        kind: "in-process",
        cardUrl: "runtime://assistant",
        transportClass: "RuntimeTransport",
        agentArg: 'transport="runtime"',
      },
      {
        id: "websocket",
        label: "WebSockets",
        kind: "duplex",
        cardUrl: "ws://127.0.0.1:8000",
        secureCardUrl: "wss://127.0.0.1:8000",
        transportClass: "WebSocketTransport",
        agentArg: 'transport="websocket"',
      },
      {
        id: "grpc",
        label: "gRPC",
        kind: "rpc",
        cardUrl: "grpc://127.0.0.1:8000",
        secureCardUrl: "grpcs://127.0.0.1:8000",
        transportClass: "GRPCTransport",
        agentArg: 'transport="grpc"',
      },
      {
        id: "jsonrpc",
        label: "JSON-RPC",
        kind: "sse",
        cardUrl: "http://127.0.0.1:8000",
        secureCardUrl: "https://127.0.0.1:8000",
        transportClass: "SSEJSONRPCTransport",
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
  {
    id: "resilience",
    label: "Resilience",
    detail: "limits and retries",
    badge: "RS",
    tone: "blue",
    options: [
      {
        id: "production",
        label: "Production",
        kind: "bounded",
        imports: [
          "from protolink import RetryPolicy, TransportConfig, TransportLimits",
        ],
        setup: [
          "transport_config = TransportConfig(",
          "    limits=TransportLimits(",
          "        max_concurrent_requests=200,",
          "        max_concurrent_streams=50,",
          "    ),",
          "    retry=RetryPolicy(max_attempts=3),",
          ")",
        ],
      },
      {
        id: "limits-only",
        label: "Limits only",
        kind: "no retries",
        imports: ["from protolink import TransportConfig, TransportLimits"],
        setup: [
          "transport_config = TransportConfig(",
          "    limits=TransportLimits(",
          "        max_request_bytes=8 * 1024 * 1024,",
          "        max_concurrent_requests=100,",
          "    ),",
          ")",
        ],
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
      transportClass: "RuntimeTransport",
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

function tokenizeHighlightedLine(line, lineIndex) {
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
      tokens.push({
        className: null,
        key: `${lineIndex}-${cursor}`,
        text: source.slice(cursor, start),
      });
    }

    tokens.push({
      className: tokenClassName(token, source, end),
      key: `${lineIndex}-${start}`,
      text: token,
    });
    cursor = end;
  }

  if (cursor < source.length) {
    tokens.push({
      className: null,
      key: `${lineIndex}-${cursor}`,
      text: source.slice(cursor),
    });
  }

  if (comment) {
    tokens.push({
      className: styles.syntaxComment,
      key: `${lineIndex}-comment`,
      text: comment,
    });
  }

  return tokens;
}

function renderTokenText(token, key, text) {
  if (!text) {
    return null;
  }

  return token.className ? (
    <span className={token.className} key={key}>
      {text}
    </span>
  ) : (
    <span key={key}>{text}</span>
  );
}

function renderHighlightedLine(line, lineIndex, caretColumn) {
  const tokens = tokenizeHighlightedLine(line, lineIndex);
  const output = [];
  let column = 0;
  let caretRendered = false;
  const renderCaret = (key) => (
    <span className={styles.editorCaret} key={key} />
  );

  tokens.forEach((token) => {
    const tokenStart = column;
    const tokenEnd = tokenStart + token.text.length;

    if (
      caretColumn !== null &&
      !caretRendered &&
      caretColumn >= tokenStart &&
      caretColumn <= tokenEnd
    ) {
      const splitAt = caretColumn - tokenStart;
      output.push(
        renderTokenText(token, `${token.key}-before`, token.text.slice(0, splitAt)),
      );
      output.push(renderCaret(`${lineIndex}-caret`));
      output.push(
        renderTokenText(token, `${token.key}-after`, token.text.slice(splitAt)),
      );
      caretRendered = true;
    } else {
      output.push(renderTokenText(token, token.key, token.text));
    }

    column = tokenEnd;
  });

  if (caretColumn !== null && !caretRendered) {
    output.push(renderCaret(`${lineIndex}-caret`));
  }

  return output;
}

function caretPositionForCode(code, caretOffset) {
  const safeOffset = Math.max(0, Math.min(caretOffset, code.length));
  const prefix = code.slice(0, safeOffset);
  const lines = prefix.split("\n");

  return {
    column: lines[lines.length - 1].length,
    line: lines.length - 1,
  };
}

function renderHighlightedCode(code, caretOffset) {
  const caretPosition = caretPositionForCode(code, caretOffset);

  return code
    .split("\n")
    .flatMap((line, lineIndex, lines) => [
      ...renderHighlightedLine(
        line,
        lineIndex,
        lineIndex === caretPosition.line ? caretPosition.column : null,
      ),
      lineIndex < lines.length - 1 ? "\n" : "",
    ]);
}

function diffCodeLines(fromCode, toCode) {
  const fromLines = fromCode ? fromCode.split("\n") : [];
  const toLines = toCode ? toCode.split("\n") : [];
  const table = Array.from({ length: fromLines.length + 1 }, () =>
    Array(toLines.length + 1).fill(0),
  );

  for (let fromIndex = fromLines.length - 1; fromIndex >= 0; fromIndex -= 1) {
    for (let toIndex = toLines.length - 1; toIndex >= 0; toIndex -= 1) {
      table[fromIndex][toIndex] =
        fromLines[fromIndex] === toLines[toIndex]
          ? table[fromIndex + 1][toIndex + 1] + 1
          : Math.max(
              table[fromIndex + 1][toIndex],
              table[fromIndex][toIndex + 1],
            );
    }
  }

  const edits = [];
  let fromIndex = 0;
  let toIndex = 0;

  while (fromIndex < fromLines.length && toIndex < toLines.length) {
    if (fromLines[fromIndex] === toLines[toIndex]) {
      edits.push({ type: "equal", line: fromLines[fromIndex] });
      fromIndex += 1;
      toIndex += 1;
    } else if (table[fromIndex + 1][toIndex] >= table[fromIndex][toIndex + 1]) {
      edits.push({ type: "delete", line: fromLines[fromIndex] });
      fromIndex += 1;
    } else {
      edits.push({ type: "insert", line: toLines[toIndex] });
      toIndex += 1;
    }
  }

  while (fromIndex < fromLines.length) {
    edits.push({ type: "delete", line: fromLines[fromIndex] });
    fromIndex += 1;
  }

  while (toIndex < toLines.length) {
    edits.push({ type: "insert", line: toLines[toIndex] });
    toIndex += 1;
  }

  return edits;
}

function codeOffsetFromLinePosition(lines, lineIndex, column) {
  if (!lines.length) {
    return 0;
  }

  const safeLineIndex = Math.max(0, Math.min(lineIndex, lines.length - 1));
  const safeColumn = Math.max(
    0,
    Math.min(column, lines[safeLineIndex]?.length ?? 0),
  );
  let offset = 0;

  for (let index = 0; index < safeLineIndex; index += 1) {
    offset += lines[index].length + 1;
  }

  return offset + safeColumn;
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
  const tlsEnabled =
    activeModules.some((module) => module.id === "tls") &&
    Boolean(transportOption.secureCardUrl);
  const resilienceEnabled = activeModules.some(
    (module) => module.id === "resilience",
  );
  const advancedTransport = tlsEnabled || resilienceEnabled;
  const cardUrl = tlsEnabled
    ? transportOption.secureCardUrl
    : transportOption.cardUrl;
  const constructorArgs = [
    `card=AgentCard(name="assistant", description="Composable protocol task agent", url="${cardUrl}")`,
  ];
  const afterLines = [];

  activeModules.forEach((module) => {
    if (module.id === "tls" && !tlsEnabled) {
      return;
    }
    const resolvedModule = selectedModuleOption(module, selectedOptions);

    resolvedModule.imports?.forEach((line) => imports.add(line));
    resolvedModule.setup?.forEach((line) => setupLines.push(line));

    if (
      resolvedModule.agentArg &&
      !(advancedTransport && module.id === "transport")
    ) {
      constructorArgs.push(resolvedModule.agentArg);
    }

    resolvedModule.after?.forEach((line) => afterLines.push(line));
  });

  if (advancedTransport) {
    imports.add(
      `from protolink.transport import ${transportOption.transportClass}`,
    );
    setupLines.push(
      `transport = ${transportOption.transportClass}(`,
      `    url="${cardUrl}",`,
      ...(tlsEnabled ? ["    tls=tls,"] : []),
      ...(resilienceEnabled ? ["    config=transport_config,"] : []),
      ")",
    );
    constructorArgs.push("transport=transport");
  }

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
  const [streamedCode, setStreamedCode] = useState("");
  const [caretOffset, setCaretOffset] = useState(0);
  const displayedCodeRef = useRef("");
  const animationRunRef = useRef(0);
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
    let cancelled = false;
    const runId = animationRunRef.current + 1;
    animationRunRef.current = runId;
    const isCurrentRun = () => !cancelled && animationRunRef.current === runId;
    const commit = (lines, lineIndex, column) => {
      const nextCode = lines.join("\n");
      const nextCaretOffset = codeOffsetFromLinePosition(
        lines,
        lineIndex,
        column,
      );
      displayedCodeRef.current = nextCode;
      setStreamedCode(nextCode);
      setCaretOffset(nextCaretOffset);
    };
    const pause = (duration = 18) =>
      new Promise((resolve) => {
        window.setTimeout(resolve, duration);
      });

    async function animateLineEdit() {
      if (displayedCodeRef.current === code) {
        return;
      }

      const edits = diffCodeLines(displayedCodeRef.current, code);
      const lines = displayedCodeRef.current
        ? displayedCodeRef.current.split("\n")
        : [];
      let cursor = 0;

      for (const edit of edits) {
        if (!isCurrentRun()) {
          return;
        }

        if (edit.type === "equal") {
          cursor += 1;
          continue;
        }

        if (edit.type === "delete") {
          const originalLine = lines[cursor] ?? "";
          const chunkSize = Math.max(1, Math.ceil(originalLine.length / 28));

          for (
            let length = originalLine.length - chunkSize;
            length >= 0;
            length -= chunkSize
          ) {
            if (!isCurrentRun()) {
              return;
            }
            lines[cursor] = originalLine.slice(0, Math.max(0, length));
            commit(lines, cursor, lines[cursor].length);
            await pause(14);
          }

          lines.splice(cursor, 1);
          commit(lines, Math.min(cursor, lines.length - 1), 0);
          await pause(34);
          continue;
        }

        lines.splice(cursor, 0, "");
        commit(lines, cursor, 0);
        await pause(edit.line ? 18 : 34);

        if (edit.line) {
          const chunkSize = Math.max(1, Math.ceil(edit.line.length / 30));
          for (
            let length = chunkSize;
            length <= edit.line.length;
            length += chunkSize
          ) {
            if (!isCurrentRun()) {
              return;
            }
            lines[cursor] = edit.line.slice(
              0,
              Math.min(edit.line.length, length),
            );
            commit(lines, cursor, lines[cursor].length);
            await pause();
          }
        }

        lines[cursor] = edit.line;
        commit(lines, cursor, edit.line.length);
        cursor += 1;
        await pause(28);
      }

      if (isCurrentRun() && displayedCodeRef.current !== code) {
        displayedCodeRef.current = code;
        setStreamedCode(code);
        setCaretOffset(code.length);
      }
    }

    animateLineEdit();

    return () => {
      cancelled = true;
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
            <code>{renderHighlightedCode(streamedCode, caretOffset)}</code>
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
      title="A2A-first autonomous agent systems"
      description="ProtoLink documentation for autonomous agents, A2A protocol objects, LLMs, tools, transports, discovery, flows, and production-ready multi-agent systems."
    >
      <main className={styles.page}>
        <section className={styles.hero}>
          <div className={styles.heroInner}>
            <div className={styles.heroCopy}>
              <p className={styles.kicker}>A2A-first Python framework</p>
              <h1>
                Build autonomous agents that communicate through A2A-derived
                tasks.
              </h1>
              <p className={styles.lede}>
                ProtoLink helps you build distributed, LLM-powered agent systems
                where every agent is an entity with identity, tools, optional
                grounded knowledge, transport, discovery, and a clean task
                contract.
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
              RAG, transports, registry discovery, state, storage, telemetry,
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
