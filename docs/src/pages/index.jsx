import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import useBaseUrl from '@docusaurus/useBaseUrl';
import clsx from 'clsx';
import styles from './index.module.css';

const pathways = [
  {
    eyebrow: 'Start',
    title: 'Create an agent',
    body: 'Define an AgentCard, plug in an LLM or tools, and start a local or networked agent with minimal boilerplate.',
    to: '/docs/getting-started',
  },
  {
    eyebrow: 'Protocol',
    title: 'Understand the A2A core',
    body: 'Work with AgentCard, Task, Message, Part, Artifact, and TaskState as the shared language between agents.',
    to: '/docs/concept',
  },
  {
    eyebrow: 'Capabilities',
    title: 'Add LLMs and tools',
    body: 'Use API, server, or local models; expose native Python tools; and adapt MCP tools into the same agent surface.',
    to: '/docs/llm',
  },
  {
    eyebrow: 'Systems',
    title: 'Compose flows and meshes',
    body: 'Build coordinators, workers, deterministic flows, registry-backed discovery, and multi-agent examples.',
    to: '/docs/examples',
  },
];

const agentShapes = [
  ['Tool-only', 'Deterministic capabilities without an LLM.'],
  ['LLM-only', 'Reasoning, transformation, and conversation.'],
  ['Hybrid', 'LLM decisions with typed tool execution.'],
  ['Coordinator', 'Discovery, delegation, and multi-agent routing.'],
];

const foundations = [
  ['Identity', 'AgentCard declares name, URL, transport, skills, tags, formats, and security schemes.'],
  ['Work exchange', 'Tasks carry Messages, Parts, Artifacts, state, and metadata across local or remote boundaries.'],
  ['Capability surface', 'Native tools, MCP adapters, schemas, examples, LLMs, and peer agents become discoverable contracts.'],
  ['Deployment path', 'Start in-process with RuntimeTransport, then move the same agent to HTTP, SSE JSON-RPC, or WebSocket.'],
];

function PathwayCard({pathway}) {
  return (
    <Link className={styles.pathwayCard} to={pathway.to}>
      <span>{pathway.eyebrow}</span>
      <h3>{pathway.title}</h3>
      <p>{pathway.body}</p>
    </Link>
  );
}

function AgentMesh({logo}) {
  return (
    <div className={styles.agentMesh} aria-label="ProtoLink agent mesh">
      <div className={clsx(styles.meshLine, styles.lineLlm)} />
      <div className={clsx(styles.meshLine, styles.lineTools)} />
      <div className={clsx(styles.meshLine, styles.lineRegistry)} />
      <div className={clsx(styles.meshLine, styles.lineTransport)} />

      <div className={clsx(styles.meshNode, styles.meshCenter)}>
        <img src={logo} alt="" />
        <strong>Agent</strong>
        <span>identity, lifecycle, task handling</span>
      </div>

      <div className={clsx(styles.meshNode, styles.meshLlm)}>
        <small>LLM</small>
        <strong>API, server, local</strong>
        <span>one action contract</span>
      </div>

      <div className={clsx(styles.meshNode, styles.meshTools)}>
        <small>Tools</small>
        <strong>Native + MCP</strong>
        <span>schemas and capabilities</span>
      </div>

      <div className={clsx(styles.meshNode, styles.meshRegistry)}>
        <small>Discovery</small>
        <strong>Registry</strong>
        <span>agent cards and indexes</span>
      </div>

      <div className={clsx(styles.meshNode, styles.meshTransport)}>
        <small>Transport</small>
        <strong>HTTP, SSE, WS, runtime</strong>
        <span>same agent contract</span>
      </div>

      <div className={styles.protocolRail}>
        <span>Task</span>
        <span>Message</span>
        <span>Part</span>
        <span>Artifact</span>
      </div>
    </div>
  );
}

export default function Home() {
  const logo = useBaseUrl('/img/logo_sm.png');

  return (
    <Layout
      title="A2A-native autonomous agent systems"
      description="ProtoLink documentation for autonomous agents, A2A protocol objects, LLMs, tools, transports, discovery, flows, and production-ready multi-agent systems.">
      <main className={styles.page}>
        <section className={styles.hero}>
          <div className={styles.heroInner}>
            <div className={styles.heroCopy}>
              <p className={styles.kicker}>A2A-native Python framework</p>
              <h1>Build autonomous agents that communicate through protocol-native tasks.</h1>
              <p className={styles.lede}>
                ProtoLink helps you build distributed, LLM-powered agent systems where every agent is an entity with identity, tools, optional memory, transport, discovery, and a clean task contract.
              </p>
              <p className={styles.positioning}>
                Focus on your agent logic - ProtoLink handles communication, authentication, LLM integration, and tool management for you.
              </p>
              <div className={styles.heroActions}>
                <Link className={clsx('button button--primary', styles.primaryButton)} to="/docs/getting-started">
                  Start building
                </Link>
                <Link className={clsx('button button--secondary', styles.secondaryButton)} to="/docs/concept">
                  Understand the model
                </Link>
                <Link className={styles.ghostLink} to="/docs/whitepaper">
                  Read the whitepaper
                </Link>
              </div>
            </div>
            <AgentMesh logo={logo} />
          </div>
        </section>

        <section className={styles.pathways} aria-labelledby="pathways">
          <div className={styles.sectionHeader}>
            <span>Documentation paths</span>
            <h2 id="pathways">Start from the part of the system you are building.</h2>
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
              An agent can receive work, initiate work, discover peers, expose capabilities, call its model, stream progress, and shut down cleanly. The model is one pluggable module inside that entity, alongside tools, transports, state, telemetry, authentication, logging, and policy.
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
            <h2>Build one agent, then let the same contracts scale to a system.</h2>
            <p>
              The docs cover the full surface: agents, clients, LLMs, tools, transports, registry discovery, state, storage, telemetry, structured flows, examples, and the runtime controls that make production behavior inspectable.
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
