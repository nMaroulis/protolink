import React, {useMemo, useState} from 'react';
import Link from '@docusaurus/Link';
import styles from './styles.module.css';

const surfaces = [
  {
    id: 'agent-runtime',
    label: 'Agent runtime',
    eyebrow: 'Core object',
    title: 'Agent as the autonomous runtime unit',
    accent: '#0a84ff',
    summary:
      'The Agent facade owns identity, lifecycle, execution, policy, tools, optional LLMs, state access, and peer communication through client/server boundaries.',
    modules: ['protolink.agents', 'protolink.core', 'protolink.models'],
    responsibilities: [
      'Owns AgentCard identity and advertised capabilities',
      'Starts and stops the embedded server runtime',
      'Executes tasks, tool calls, inference, cancellation, and reports',
      'Coordinates registry registration and discovery through RegistryClient',
    ],
    boundaries: [
      'Does not implement protocols directly',
      'Does not require a specific LLM provider',
      'Does not force a storage backend',
    ],
    docs: [
      ['Agent', '/docs/agent'],
      ['Runtime', '/docs/runtime'],
      ['Models', '/docs/models'],
    ],
  },
  {
    id: 'a2a-substrate',
    label: 'A2A substrate',
    eyebrow: 'Protocol layer',
    title: 'A2A primitives with ProtoLink extensions',
    accent: '#16a34a',
    summary:
      'AgentCard, Task, Message, Part, Artifact, and registry discovery give ProtoLink a protocol-native base while runtime controls extend the useful operating surface.',
    modules: ['protolink.core', 'protolink.discovery', 'protolink.types'],
    responsibilities: [
      'Defines portable task, message, artifact, and identity shapes',
      'Publishes and discovers AgentCards through the registry',
      'Adds run context, budgets, cancellation, policy, reports, and replay',
      'Keeps integration points inspectable instead of hidden behind orchestration magic',
    ],
    boundaries: [
      'A2A shapes stay independent of specific transports',
      'Runtime controls travel as explicit context and events',
      'Registry coordinates discovery without routing tasks',
    ],
    docs: [
      ['A2A core', '/docs/a2a'],
      ['Concept', '/docs/concept'],
      ['Registry', '/docs/registry'],
      ['Types', '/docs/types'],
    ],
  },
  {
    id: 'communication',
    label: 'Communication',
    eyebrow: 'Client and server',
    title: 'Intent-level APIs over swappable transports',
    accent: '#14b8a6',
    summary:
      'Clients express outgoing intent, servers expose incoming handlers, and transports provide the physical protocol and event-loop runtime.',
    modules: ['protolink.client', 'protolink.server', 'protolink.transport'],
    responsibilities: [
      'Turns operations into ClientRequestSpec definitions',
      'Mounts handlers as EndpointSpec routes',
      'Supports HTTP, WebSocket, SSE JSON-RPC, gRPC, and in-process runtime paths',
      'Separates protocol concerns from agent logic',
    ],
    boundaries: [
      'Agents call clients, not transport internals',
      'Servers bind handlers, not business logic',
      'Transport choice stays replaceable at construction time',
    ],
    docs: [
      ['Client', '/docs/client'],
      ['Server', '/docs/server'],
      ['Transport', '/docs/transport'],
    ],
  },
  {
    id: 'intelligence',
    label: 'LLMs and tools',
    eyebrow: 'Capability layer',
    title: 'Provider-optional reasoning and tool execution',
    accent: '#7c3aed',
    summary:
      'LLM adapters, history, metrics, structured parsing, and native or MCP-backed tools can be attached to agents without changing the communication substrate.',
    modules: ['protolink.llms', 'protolink.tools'],
    responsibilities: [
      'Normalizes inference and tool-call behavior across providers',
      'Keeps provider SDK dependencies optional',
      'Builds tool schemas and execution boundaries',
      'Tracks history, context manifests, compaction, and usage metrics when enabled',
    ],
    boundaries: [
      'Agents can run without an LLM',
      'Tools are explicit modules, not prompt-only affordances',
      'Metrics extensions do not mutate prompts or history implicitly',
    ],
    docs: [
      ['LLM', '/docs/llm'],
      ['Tool', '/docs/tool'],
      ['LLM Usage', '/docs/llm_examples'],
    ],
  },
  {
    id: 'state-storage',
    label: 'State and storage',
    eyebrow: 'Persistence layer',
    title: 'State modules, storage backends, and run records',
    accent: '#ca8a04',
    summary:
      'State modules make persistence explicit, storage backends keep runtime data replaceable, and run stores provide durable execution records for inspection.',
    modules: ['protolink.state', 'protolink.storage', 'protolink.core.report'],
    responsibilities: [
      'Persists conversation, task, flow, and tool state by selected mode',
      'Provides memory and SQLite storage implementations',
      'Records task snapshots and RunReport payloads with replayable event timelines',
      'Supports durable registry entries when storage is configured',
    ],
    boundaries: [
      'State is opt-in by module',
      'Storage remains behind a generic interface',
      'Run reporting is separate from agent business logic',
    ],
    docs: [
      ['State', '/docs/state'],
      ['Storage', '/docs/storage'],
      ['Runtime', '/docs/runtime'],
    ],
  },
  {
    id: 'operations',
    label: 'Operations',
    eyebrow: 'Inspection layer',
    title: 'CLI, dashboard, telemetry, logging, and security',
    accent: '#db2777',
    summary:
      'ProtoLink includes practical runtime visibility: a CLI, local dashboard, registry and run inspection, telemetry adapters, logs, and authentication primitives.',
    modules: [
      'protolink.cli',
      'protolink.devtools',
      'protolink.telemetry',
      'protolink.logging',
      'protolink.security',
    ],
    responsibilities: [
      'Surfaces local doctor checks and dashboard views',
      'Projects registry and run-store state into browser tooling',
      'Connects telemetry to local, Langfuse, LangSmith, or multiplexed sinks',
      'Supports authentication and request security hooks',
    ],
    boundaries: [
      'Developer tools observe runtime state instead of replacing it',
      'Telemetry providers remain optional',
      'Security hooks sit at transport boundaries',
    ],
    docs: [
      ['CLI', '/docs/cli'],
      ['Developer Tools', '/docs/devtools'],
      ['Telemetry', '/docs/telemetry'],
      ['Authentication', '/docs/authentication'],
    ],
  },
  {
    id: 'examples',
    label: 'Examples',
    eyebrow: 'Learning path',
    title: 'Runnable systems and structured flow patterns',
    accent: '#2563eb',
    summary:
      'Examples show the same primitives in motion, from basic agents and registries to ticket booking, code assistants, replayable communication experiments, runtime policies, and structured flows.',
    modules: ['examples', 'examples/ticket_booking', 'examples/code_assistant', 'examples/ai_courtroom', 'examples/structured_flows'],
    responsibilities: [
      'Demonstrates registry-backed multi-agent systems',
      'Shows graph, pipeline, router, parallel, and tool-call flows',
      'Provides focused examples for runtime agents, WebSocket, MCP, and cancellation',
      'Studies how direct communication and topology affect observable group decisions',
      'Gives practical project shapes to adapt',
    ],
    boundaries: [
      'Examples are usage patterns, not hidden framework requirements',
      'Flows are deterministic Task-to-Task orchestration helpers',
      'Application logic stays outside the core runtime modules',
    ],
    docs: [
      ['Examples', '/docs/examples'],
      ['Flows', '/docs/flows'],
      ['Ticket Booking', '/docs/ticket_booking_example'],
      ['Code Assistant', '/docs/code_assistant_example'],
      ['AI Courtroom', '/docs/ai_courtroom_example'],
    ],
  },
];

const flowSteps = [
  {
    id: 'identity',
    label: 'Identity',
    title: 'AgentCard declares who an agent is',
    summary:
      'Every agent starts with an AgentCard. It carries the name, URL, capabilities, skills, tags, and metadata that other agents can discover.',
    path: 'AgentCard -> Registry -> discoverable peers',
    docs: [
      ['Models', '/docs/models'],
      ['Registry', '/docs/registry'],
    ],
  },
  {
    id: 'startup',
    label: 'Startup',
    title: 'Lifecycle starts server and registration paths',
    summary:
      'Agent startup begins its server runtime and, when a registry client is configured, registers the AgentCard and optionally starts the heartbeat loop.',
    path: 'Agent.start() -> AgentServer.start() -> RegistryClient.register()',
    docs: [
      ['Agent', '/docs/agent'],
      ['Server', '/docs/server'],
    ],
  },
  {
    id: 'discovery',
    label: 'Discovery',
    title: 'Registry lookup stays transport-backed',
    summary:
      'Discovery calls go through RegistryClient, become transport requests, and return AgentCards from the registry store after filtering and TTL pruning.',
    path: 'Agent.discover_agents() -> RegistryClient.discover() -> Registry.handle_discover()',
    docs: [
      ['Registry', '/docs/registry'],
      ['Client', '/docs/client'],
    ],
  },
  {
    id: 'task',
    label: 'Task flow',
    title: 'Tasks move through client, transport, and server',
    summary:
      'A caller sends a Task through AgentClient. The transport delivers it to AgentServer, which delegates execution back to the receiving Agent.',
    path: 'AgentClient.send_task() -> Transport.send() -> AgentServer -> handle_task()',
    docs: [
      ['Transport', '/docs/transport'],
      ['Runtime', '/docs/runtime'],
    ],
  },
  {
    id: 'control',
    label: 'Control',
    title: 'Runtime control is explicit and inspectable',
    summary:
      'RunContext, budgets, policy decisions, cancellation requests, semantic events, reports, and replay all live in visible runtime contracts.',
    path: 'RunContext + Policy + Cancellation -> RunEvent -> RunReport',
    docs: [
      ['Runtime', '/docs/runtime'],
      ['Telemetry', '/docs/telemetry'],
    ],
  },
  {
    id: 'observe',
    label: 'Observe',
    title: 'Operations read from registry and run stores',
    summary:
      'The CLI and dashboard project live registry state, run-store task snapshots, stored run reports, and agent status probes into tools for local development and debugging.',
    path: 'Registry state + SQLiteRunStore -> CLI and dashboard',
    docs: [
      ['CLI', '/docs/cli'],
      ['Developer Tools', '/docs/devtools'],
    ],
  },
];

const quickLinks = [
  ['First agent', '/docs/getting-started'],
  ['A2A core', '/docs/a2a'],
  ['Registry', '/docs/registry'],
  ['Transport', '/docs/transport'],
  ['Runtime control', '/docs/runtime'],
  ['Dashboard', '/docs/devtools'],
];

function LinkList({items}) {
  return (
    <div className={styles.linkList}>
      {items.map(([label, to]) => (
        <Link key={to} to={to}>
          {label}
        </Link>
      ))}
    </div>
  );
}

export default function ProjectMap() {
  const [surfaceId, setSurfaceId] = useState(surfaces[0].id);
  const [flowId, setFlowId] = useState(flowSteps[0].id);

  const activeSurface = useMemo(
    () => surfaces.find((surface) => surface.id === surfaceId) ?? surfaces[0],
    [surfaceId],
  );
  const activeFlow = useMemo(
    () => flowSteps.find((step) => step.id === flowId) ?? flowSteps[0],
    [flowId],
  );

  return (
    <div className={styles.projectMap}>
      <section className={styles.hero} aria-labelledby="project-map-title">
        <div className={styles.heroCopy}>
          <span className={styles.eyebrow}>Project overview</span>
          <h1 id="project-map-title">ProtoLink Project Map</h1>
          <p>
            An interactive index of the framework: A2A primitives, agent runtime,
            transports, registry discovery, state, tools, LLMs, and operational surfaces.
          </p>
          <LinkList items={quickLinks} />
        </div>
        <div className={styles.diagram} aria-label="High-level ProtoLink runtime diagram">
          <div className={`${styles.diagramNode} ${styles.diagramNodeAgent}`}>Agent</div>
          <div className={styles.diagramRail} />
          <div className={styles.diagramSplit}>
            <span>Client</span>
            <span>Server</span>
          </div>
          <div className={styles.diagramRail} />
          <div className={`${styles.diagramNode} ${styles.diagramNodeTransport}`}>Transport</div>
          <div className={styles.diagramFooter}>
            <span>A2A</span>
            <span>Registry</span>
            <span>Runtime</span>
          </div>
        </div>
      </section>

      <section className={styles.surfaceExplorer} aria-labelledby="surface-title">
        <div className={styles.sectionHeader}>
          <span className={styles.eyebrow}>Explore by surface</span>
          <h2 id="surface-title">Where each part of the project fits</h2>
        </div>

        <div className={styles.segmented} role="tablist" aria-label="Project surfaces">
          {surfaces.map((surface) => (
            <button
              key={surface.id}
              type="button"
              role="tab"
              aria-selected={surface.id === activeSurface.id}
              className={surface.id === activeSurface.id ? styles.segmentActive : styles.segment}
              onClick={() => setSurfaceId(surface.id)}
            >
              {surface.label}
            </button>
          ))}
        </div>

        <article
          className={styles.surfaceDetail}
          style={{'--project-map-accent': activeSurface.accent}}
          aria-live="polite"
        >
          <div className={styles.detailMain}>
            <span className={styles.detailEyebrow}>{activeSurface.eyebrow}</span>
            <h3>{activeSurface.title}</h3>
            <p>{activeSurface.summary}</p>
            <LinkList items={activeSurface.docs} />
          </div>

          <div className={styles.detailColumns}>
            <div className={styles.detailGroup}>
              <strong>Modules</strong>
              <div className={styles.codeStack}>
                {activeSurface.modules.map((moduleName) => (
                  <code key={moduleName}>{moduleName}</code>
                ))}
              </div>
            </div>

            <div className={styles.detailGroup}>
              <strong>Responsibilities</strong>
              <ul>
                {activeSurface.responsibilities.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>

            <div className={styles.detailGroup}>
              <strong>Boundaries</strong>
              <ul>
                {activeSurface.boundaries.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </div>
        </article>
      </section>

      <section className={styles.flowExplorer} aria-labelledby="flow-title">
        <div className={styles.sectionHeader}>
          <span className={styles.eyebrow}>Runtime signal flow</span>
          <h2 id="flow-title">Follow one system from identity to operations</h2>
        </div>

        <div className={styles.flowGrid}>
          <div className={styles.flowRail} role="tablist" aria-label="Runtime signal flow">
            {flowSteps.map((step, index) => (
              <button
                key={step.id}
                type="button"
                role="tab"
                aria-selected={step.id === activeFlow.id}
                className={step.id === activeFlow.id ? styles.flowStepActive : styles.flowStep}
                onClick={() => setFlowId(step.id)}
              >
                <span>{String(index + 1).padStart(2, '0')}</span>
                <strong>{step.label}</strong>
              </button>
            ))}
          </div>

          <article className={styles.flowDetail} aria-live="polite">
            <span className={styles.eyebrow}>Selected path</span>
            <h3>{activeFlow.title}</h3>
            <p>{activeFlow.summary}</p>
            <code>{activeFlow.path}</code>
            <LinkList items={activeFlow.docs} />
          </article>
        </div>
      </section>
    </div>
  );
}
