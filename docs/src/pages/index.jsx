import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import useBaseUrl from '@docusaurus/useBaseUrl';
import clsx from 'clsx';
import styles from './index.module.css';

const lanes = [
  {
    eyebrow: 'Start',
    title: 'Build your first agent',
    body: 'Install ProtoLink, define an AgentCard, attach tools or an LLM, and run it locally or over HTTP.',
    to: '/docs/getting-started',
  },
  {
    eyebrow: 'Runtime',
    title: 'Control execution',
    body: 'Use run contexts, budgets, cancellation, reports, replay, and approval checkpoints as public contracts.',
    to: '/docs/runtime',
  },
  {
    eyebrow: 'Integrate',
    title: 'Connect models and tools',
    body: 'Wire LLM providers, native tools, MCP adapters, transports, registries, telemetry, and storage modules.',
    to: '/docs/llm',
  },
  {
    eyebrow: 'Operate',
    title: 'Inspect live systems',
    body: 'Use the CLI, doctor checks, dashboard, traces, and run-store views for local debugging and production readiness.',
    to: '/docs/devtools',
  },
];

const pillars = [
  ['A2A protocol core', 'Task, Message, Part, Artifact, and AgentCard stay at the center.'],
  ['Composable runtime', 'Agents, flows, tools, transports, policies, and telemetry remain independently replaceable.'],
  ['Deterministic control', 'Budgets, approvals, cancellation, reports, and replay make behavior inspectable.'],
];

function LaneCard({lane}) {
  return (
    <Link className={styles.laneCard} to={lane.to}>
      <span>{lane.eyebrow}</span>
      <h3>{lane.title}</h3>
      <p>{lane.body}</p>
    </Link>
  );
}

function RuntimeMap() {
  return (
    <div className={styles.runtimeMap} aria-label="ProtoLink runtime map">
      <div className={styles.mapHeader}>
        <span>Runtime path</span>
        <code>Task -&gt; Agent -&gt; Action -&gt; Report</code>
      </div>
      <div className={styles.mapGrid}>
        <div className={styles.mapNode}>
          <strong>Client</strong>
          <span>Typed requests and streaming events</span>
        </div>
        <div className={styles.mapNode}>
          <strong>Transport</strong>
          <span>HTTP, SSE JSON-RPC, WebSocket, runtime</span>
        </div>
        <div className={clsx(styles.mapNode, styles.mapNodeAccent)}>
          <strong>Agent</strong>
          <span>LLM loop, tools, state, policy</span>
        </div>
        <div className={styles.mapNode}>
          <strong>Run control</strong>
          <span>Budgets, cancellation, approval gates</span>
        </div>
        <div className={styles.mapNode}>
          <strong>Observability</strong>
          <span>Events, telemetry, reports, replay</span>
        </div>
      </div>
    </div>
  );
}

export default function Home() {
  const logo = useBaseUrl('/img/logo.png');

  return (
    <Layout
      title="Professional agent runtime documentation"
      description="ProtoLink documentation for A2A-native agent systems, runtime control, transports, LLMs, tools, and operations.">
      <main className={styles.page}>
        <section className={styles.hero}>
          <div className={styles.heroInner}>
            <div className={styles.heroCopy}>
              <p className={styles.kicker}>ProtoLink documentation</p>
              <h1>A professional runtime substrate for A2A-native agent systems.</h1>
              <p className={styles.lede}>
                ProtoLink turns agents, tools, transports, policies, state, telemetry, and run control into a coherent Python runtime that stays inspectable from local prototypes to production meshes.
              </p>
              <div className={styles.heroActions}>
                <Link className={clsx('button button--primary', styles.primaryButton)} to="/docs/getting-started">
                  Start building
                </Link>
                <Link className={clsx('button button--secondary', styles.secondaryButton)} to="/docs/whitepaper">
                  Read the whitepaper
                </Link>
              </div>
            </div>
            <div className={styles.heroVisual}>
              <img src={logo} alt="ProtoLink logo" />
              <div className={styles.signalPanel}>
                <span>Current focus</span>
                <strong>agent runtime, control plane, and interoperable transports</strong>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.lanes} aria-labelledby="pathways">
          <div className={styles.sectionHeader}>
            <span>Documentation paths</span>
            <h2 id="pathways">Choose the surface you are working on.</h2>
          </div>
          <div className={styles.laneGrid}>
            {lanes.map((lane) => (
              <LaneCard key={lane.title} lane={lane} />
            ))}
          </div>
        </section>

        <section className={styles.systemSection}>
          <div>
            <div className={styles.sectionHeader}>
              <span>System model</span>
              <h2>One runtime, many deployment shapes.</h2>
            </div>
            <p>
              The docs keep the protocol model visible while drilling into the implementation surfaces that matter: agents, LLM inference, tool execution, transport conformance, state, storage, telemetry, and release discipline.
            </p>
            <div className={styles.pillars}>
              {pillars.map(([title, body]) => (
                <div className={styles.pillar} key={title}>
                  <strong>{title}</strong>
                  <span>{body}</span>
                </div>
              ))}
            </div>
          </div>
          <RuntimeMap />
        </section>

        <section className={styles.referenceBand}>
          <div>
            <span>Reference depth</span>
            <h2>The complete documentation corpus is live in Docusaurus.</h2>
            <p>
              All existing pages remain available, with Docusaurus admonitions, tabs, Mermaid diagrams, themed code blocks, sidebars, local assets, and a docs-first information architecture.
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
