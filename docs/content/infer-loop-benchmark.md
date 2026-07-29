---
title: Infer-loop benchmark
sidebar_label: Benchmark
description: Measure whether a ProtoLink prompt or infer-loop change improves correctness, reliability, and latency.
keywords:
  - infer loop
  - benchmark
  - agent routing
  - delegation
  - Ollama
  - prompt regression
---

import ApiSurface from '@site/src/components/ApiSurface';
import useBaseUrl from '@docusaurus/useBaseUrl';

# Infer-loop benchmark

This benchmark is a repeatable health check for ProtoLink's infer loop. Run the
same task suite before and after a prompt or code change to see whether Agents
complete more tasks correctly—and whether they do it faster.

The infer loop turns each model response into one validated next action: **finish
with an answer**, **call a local tool**, or **delegate work to another Agent**.
It must also decide which of those action modes fits the request, which
capability to use, and—when delegation is appropriate—which discovered Agent
should receive the work. This repository benchmark lets you change that loop or
its prompts and answer a practical question with comparable evidence:

> Did the model complete more tasks correctly, recover less often, and finish
> faster than it did before?

<ApiSurface
  eyebrow="Project regression harness"
  title="Turn infer-loop changes into comparable evidence"
  ariaLabel="Infer-loop benchmark overview"
  path="benchmarks/infer_loop"
  description="Run generated tasks through the real AgentClient → Agent → LLM path, validate every action against deterministic evidence, and export correctness and timing results."
  pills={[
    "12-case smoke",
    "40-case core",
    "200-case full",
    "semantic routing",
    "Ollama-first",
    "JSON + CSV evidence",
  ]}
  cards={[
    {
      title: "Execute",
      text: "Send real infer tasks through an in-process multi-agent mesh.",
      code: "AgentClient.send_infer_task()",
    },
    {
      title: "Prove",
      text: "Check the final answer, independent execution ledger, runtime trace, and protocol path.",
      code: "oracle + ledger + trace",
    },
    {
      title: "Measure",
      text: "Keep correctness separate from first-try reliability, latency, and cache-sensitive repeats.",
      code: "STRICT · FIRST TRY · timing",
    },
    {
      title: "Compare",
      text: "Match a candidate run to a saved baseline and identify fixed or regressed cases.",
      code: "--baseline summary.json",
    },
  ]}
  note="The harness lives outside the installable protolink package on purpose: it is source-checkout development tooling, not public runtime API or a dependency shipped to users."
/>

<div className="doc-button-row">
  <a className="doc-button primary" href="#quick-start">Run a smoke check</a>
  <a className="doc-button" href="#compare-before-and-after">Compare a baseline</a>
  <a className="doc-button" href="#how-one-case-works">See how validation works</a>
</div>

:::tip[The short version]

Use `smoke` while editing, `core` for routine before/after comparisons, and
`full` for a fixed 200-case baseline. Treat `STRICT` as the headline
correctness score and compare timing only between controlled runs on the same
machine. Use the `routing_choice` category when you specifically want to test
whether the model can choose between a direct answer, a local tool, delegated
tool execution, and delegated inference without being told implementation
names.

:::

## How one case works

The task catalog, synthetic specialist data, receipts, and validation oracle
are deterministic for a given seed. The provider and model are not guaranteed
to be deterministic, even with temperature zero. The benchmark controls the
world around the model so that its decisions can be judged exactly.

```mermaid
flowchart LR
    A["Generated case<br/>+ hidden oracle"] --> B["AgentClient<br/>send_infer_task()"]
    B --> C["Coordinator Agent"]
    C --> D{"LLM proposes<br/>a typed action"}
    D -->|"final"| E["Task result"]
    D -->|"local tool"| F["Deterministic<br/>local tool"]
    D -->|"delegate"| G{"Choose a discovered<br/>specialist Agent"}
    G --> H1["Authoritative<br/>specialist"]
    G --> H2["Plausible<br/>decoy specialist"]
    F --> H["Observation<br/>+ opaque receipt"]
    H1 --> H
    H2 --> H
    H --> C
    C -. "action evidence" .-> I["Independent ledger<br/>+ local trace"]
    E --> J["Validator"]
    I --> J
    J --> K["Strict · functional<br/>or failure"]
```

The real ProtoLink path and the controlled benchmark world have different
jobs:

| Part | What happens in the benchmark |
| --- | --- |
| **Real runtime path** | `AgentClient`, `Task`, coordinator `Agent`, provider adapter, LLM infer loop, tool registry, delegation, runtime events, and telemetry execute normally. |
| **Controlled specialists** | `workspace_agent`, `travel_agent`, and `oracle_agent` return deterministic closed-world values. |
| **Overlapping decoys** | `workspace_archive_agent` and `travel_planning_agent` advertise overlapping tool names and schemas. They make the model identify the authoritative target instead of relying on unique-tool inference. |
| **Controlled tools** | Coordinator and specialist tools do no external work; they return repeatable results and opaque `BENCH-...` receipts. |
| **In-process transport** | `RuntimeTransport` exercises task serialization, registry discovery, Agents, and tools without adding network variability. |
| **Independent judge** | A hidden oracle knows the exact final text and expected action sequence. The execution ledger and local trace prove what actually ran. |

### A concrete multi-step case

<div className="doc-quote-card">
  <div className="quote-mark">↳</div>
  <div className="quote-body">
    First delegate <code>travel_agent.get_weather</code>. Then call
    <code>travel_agent.quote_hotel</code> and pass the exact weather receipt
    from step one. Return both values and both receipts in the requested format.
  </div>
  <div className="quote-source">Representative generated benchmark instruction</div>
</div>

The model sees the instruction and typed capabilities, but it does **not** see
the receipt that the specialist will generate.

1. The coordinator must select the correct Agent, tool, and typed arguments.
2. The specialist returns an authoritative observation such as a temperature
   and an opaque `BENCH-WX-...` receipt.
3. The coordinator must copy that exact receipt into the dependent hotel call.
4. The final answer must exactly match the hidden oracle.
5. The ledger and trace must show those two successful actions in the correct
   order.

Inventing a plausible answer, fabricating a receipt, or merely claiming that an
Agent was called cannot pass these checks.

### A routing-choice case proves the decision itself

Directed delegation cases deliberately tell the coordinator which Agent and
tool to call. They isolate action formatting, typed arguments, dispatch, result
handling, and exact final output. Routing-choice cases ask a harder and
different question: can the model infer the correct route from the task and
the discovered capability descriptions?

For example, a routing-choice request has this shape:

<div className="doc-quote-card">
  <div className="quote-mark">?</div>
  <div className="quote-body">
    For <code>REQ-...</code>, obtain the authoritative current source digest
    for <code>router.py</code> using the available specialists. An archived
    snapshot is not acceptable. Return exactly
    <code>digest=&lt;reported digest&gt;;receipt=&lt;reported receipt&gt;</code>.
  </div>
  <div className="quote-source">Representative semantic-routing instruction</div>
</div>

The request does not contain `workspace_agent` or `read_file`. The coordinator
must derive both from the runtime affordances. It also sees
`workspace_archive_agent`, which advertises the same tool name and compatible
arguments but describes archived, non-authoritative data.

The decoy is intentionally stronger than a tool that simply throws an error.
For the controlled benchmark inputs it can return the same deterministic value
and receipt as the authoritative specialist. Consequently, checking only the
final answer would incorrectly award a pass to the wrong route. ProtoLink's
independent ledger and trace still record the selected Agent name, so the
attempt fails the routing proof even when its final text is indistinguishable
from the oracle:

```text
Expected target: workspace_agent
Observed target: workspace_archive_agent
Final text:      exactly correct
Outcome:         failed — execution ledger and trace do not match
```

This design separates **answer correctness** from **decision correctness**. A
routing-choice pass demonstrates all of the following:

1. The model chose the appropriate action mode: `final`, local `tool_call`, or
   delegated `agent_call`.
2. For delegated work, it selected the authoritative specialist rather than a
   plausible overlapping decoy.
3. It selected the correct tool or inference action and supplied the required
   typed arguments or evidence fields.
4. It used the returned observation to produce the exact requested final text.
5. The ledger and trace independently confirmed the same route and execution.

The routing catalog includes direct completion, both coordinator-owned tools,
authoritative workspace and travel tools, and inference delegation to the
deterministic reference analyst. The routine `core` suite includes at least one
routing case for every action mode; the `full` suite exercises all routing
variants with different deterministic inputs.

## Quick start

### 1. Prepare the checkout and model

Run the benchmark from the repository root. Install ProtoLink in editable
development mode, start Ollama, and make sure the requested model is present:

```bash
uv pip install -e ".[dev]"
ollama pull gemma4:e4b
```

The benchmark imports the source and prompt files in this checkout. It is not
installed as part of the published `protolink` package.

### 2. Run the smoke suite

```bash
python -m benchmarks.infer_loop \
  --provider ollama \
  --model gemma4:e4b \
  --suite smoke
```

For Ollama, the base URL resolves from `--base-url`, then `OLLAMA_URL`, then
`http://localhost:11434`. Defaults are chosen for repeatable local comparison:
temperature `0`, model seed `1337`, context size `8192`, generation limit
`2048`, JSON-prompt action mode, and one unscored warm-up.

:::note[JSON-prompt mode is part of the experiment]

Ollama uses ProtoLink's portable JSON action protocol by default. Use
`--supports-tool-calling` only for a model with compatible native tool support.
Native-tool and JSON-prompt runs are different configurations and should not be
mixed in one before/after comparison.

:::

### 3. Read the terminal summary

The final block follows this shape; the numbers below are illustrative:

```text
STRICT     10/12 (83.3%)
FUNCTIONAL 11/12 (91.7%)
FIRST TRY  9/12 (75.0%)
RESCUED ON LATER ATTEMPT 1
ATTEMPT DIAGNOSTICS parse-recovery=1 hallucinated-action=1 crashed=0 timed-out=0
LLM STEPS avg=2.25 p95=4; STRICT FIRST-TRY LATENCY median=1.84s p95=3.71s
WALL TIME  scored=29.40s warmup=1.20s; LLM CALLS median=0.78s
RESULTS    benchmark_results/20260728-143000
```

- `STRICT` is the headline score: correct task, exact actions, and a clean
  protocol path.
- `FUNCTIONAL` includes cases that reached the correct result after infer-loop
  self-correction.
- `FIRST TRY` counts logical cases whose first fresh attempt passed strictly.
- `WALL TIME` is elapsed time for the scored suite; warm-up is reported
  separately.
- `REPEAT PROBE` appears when eligible adjacent repetitions exist.
- `RESULTS` points to the directory containing the detailed evidence.

Open `report.html` inside the results directory for the same run as a visual
dashboard. It is a single self-contained file, so it opens directly in a
browser without a server or external assets.

The report is designed for both overview and diagnosis:

- **Correctness by category** separates routing decisions from directed local,
  delegated, multi-step, and grounding work.
- **Case latency and outcome** shows one selected-attempt bar per logical case
  repetition. When a run has hundreds or thousands of entries, the chart
  scrolls inside its own panel instead of widening the entire page.
- **Attempt review** includes every logical case that had a non-strict fresh
  attempt—not only cases that ultimately failed. A case that passes on a later
  fresh attempt is marked `Rescued`, while a case with no strict attempt remains
  unresolved.
- Each review card shows the original request, the expected final output and
  actions, the actual final output, normalized model decisions, successful
  ledger actions, diagnostics, and the runtime error for every fresh attempt.

This distinction is useful when the visible answer is not the real failure.
For example, a decoy specialist can return the same value as the authoritative
Agent. The review card then shows a correct-looking `Actual final output`
alongside a `Model decisions` entry naming the wrong Agent and an
`execution_ledger_mismatch` or `trace_action_mismatch` diagnostic.

### Example generated report

The report below is a generated snapshot from an example local run. It is
embedded here as produced by the benchmark, rather than being maintained as
hand-written documentation:

```bash
python -m benchmarks.infer_loop \
  --provider ollama \
  --model gemma4:e4b \
  --suite core \
  --attempts 2 \
  --repetitions 2
```

<div className="generated-report-embed">
  <iframe
    src={useBaseUrl('/html/benchmark-report.html')}
    title="Generated infer-loop benchmark report for Ollama with gemma4:e4b"
    loading="lazy"
    sandbox=""
  />
</div>

<p>If the embedded report is too narrow for detailed inspection, <a href={useBaseUrl('/html/benchmark-report.html')} target="_blank" rel="noreferrer">open the generated report in a new tab</a>.</p>

### Choose a suite

| Suite | Default cases | Routing-choice cases | Best use |
| --- | ---: | ---: | --- |
| `smoke` | 12 | 2 | Fast feedback while editing a prompt or the infer loop |
| `core` | 40 | 4 | Routine comparison, including direct/local/tool-delegation/inference routing modes |
| `full` | 200 | 20 | Slower release check covering every routing variant and the broadest deterministic input set |

`full` produces a denominator of 200 only with one repetition and without
filters, `--limit`, or a `--count` override. The catalog and order are generated
deterministically from `--seed`. In the default full catalog, each of the six
directed categories contributes 30 cases and `routing_choice` contributes 20.
This keeps the total fixed at 200 while avoiding unnecessary repetition in the
explicitly directed categories.

## What the catalog tests

Each case asks the coordinator to demonstrate one or more infer-loop skills.

| Category | Skill under test | A failure usually means |
| --- | --- | --- |
| `direct_final` | Finish without unnecessary actions and match exact output | The model called a tool, delegated, or changed the requested answer |
| `local_tool` | Select a coordinator-owned tool and provide typed arguments | Wrong tool, invalid arguments, or invented output |
| `delegated_tool` | Execute an explicitly requested Agent tool with exact typed arguments | Wrong target/tool, malformed arguments, or invented output |
| `delegated_infer` | Execute explicitly requested inference delegation with all required prompt evidence | Missing evidence, wrong specialist, or fabricated result |
| `multi_step` | Use one action's receipt in a later dependent action | Wrong order or failure to carry authoritative evidence forward |
| `grounding_trap` | Reject stale/untrusted prompt values in favor of an observation | The model repeated the trap instead of using the tool or Agent result |
| `routing_choice` | Infer the action mode, capability, and authoritative Agent without implementation names | Unnecessary action, wrong local/remote mode, decoy selection, or otherwise incorrect semantic routing |

Here, a **hallucinated action** has a narrow, testable meaning: an invalid or
unexpected tool/Agent attempt, an action absent from the expected ledger, a
fabricated receipt, or a grounding-trap mismatch. The benchmark does not judge
the truth or writing quality of arbitrary open-domain prose. In particular, a
decoy call counts as an unexpected action even when it returns the same value
as the expected specialist: the tested mistake is the route, not the data.

## Read the score correctly

<div className="benchmark-score-grid">
  <div className="benchmark-score-card benchmark-score-card--strict">
    <span className="benchmark-score-kicker">Headline regression signal</span>
    <strong>STRICT</strong>
    <span className="benchmark-score-example">180 / 200</span>
    <p>Exact final output, exact action evidence, and no protocol recovery or invalid action.</p>
  </div>
  <div className="benchmark-score-card benchmark-score-card--functional">
    <span className="benchmark-score-kicker">Eventual task success</span>
    <strong>FUNCTIONAL</strong>
    <span className="benchmark-score-example">≥ strict</span>
    <p>The answer and executed actions are correct, even if the infer loop had to self-correct.</p>
  </div>
  <div className="benchmark-score-card benchmark-score-card--first">
    <span className="benchmark-score-kicker">Fresh-attempt reliability</span>
    <strong>FIRST TRY</strong>
    <span className="benchmark-score-example">attempt 1</span>
    <p>The first fresh attempt passed strictly, so extra attempts cannot hide instability.</p>
  </div>
</div>

The denominator is:

```text
selected cases × repetitions
```

Therefore, `180/200` means 180 logical case repetitions achieved a strict pass.
It does **not** mean 180 provider calls succeeded. One logical case may require
multiple LLM calls, and `--attempts` may execute the task again.

### The four proof gates

A strict pass requires all four gates:

| Gate | What must be true |
| --- | --- |
| **Task result** | The task completed without a crash or timeout and `infer_output` exactly matched the deterministic oracle. |
| **Execution ledger** | Exactly the expected tools and Agents ran, with the expected arguments and action order. |
| **Runtime trace** | The local trace independently contains the same successful actions and targets. |
| **Clean protocol** | There was no parse recovery, duplicate action, invalid tool, or invalid Agent attempt. |

:::info[Why exact output alone is insufficient]

Suppose a routing-choice case asks for authoritative workspace data. The model
calls `workspace_archive_agent.read_file`, and that decoy happens to return the
same digest and receipt as `workspace_agent.read_file`.

- **Task result gate:** passes, because the final text matches.
- **Execution ledger gate:** fails, because the observed Agent is the decoy.
- **Runtime trace gate:** fails for the same target mismatch.
- **Functional and strict result:** both fail, because all proof gates are
  required.

This is what makes `routing_choice` a routing benchmark rather than an
answer-only benchmark.

:::

:::info[Worked recovery example]

Suppose the model first delegates to an Agent that does not exist. The infer
loop reports the error, the model retries with the correct Agent, and the task
finishes with the exact expected answer and action evidence.

- `FUNCTIONAL`: **pass**
- `STRICT`: **fail**, because the protocol path included an invalid Agent
  attempt
- `FIRST TRY`: depends on whether this was the first *fresh task attempt* and
  whether that attempt passed strictly; infer-loop correction inside it does
  not create another fresh attempt

:::

## Choose what you are measuring

Attempts, repetitions, parse corrections, and provider retries answer different
questions:

| Control or metric | What it changes | What it tells you |
| --- | --- | --- |
| `--attempts N` | Allows up to `N` fresh tasks per logical case, stopping after its first strict pass | How often a later clean run rescues a case |
| `--repetitions N` | Runs each selected case `N` times adjacently and scores every repetition | Reliability and a cache-sensitive repeat signal |
| `--max-parse-failures N` | Sets the action-envelope correction budget inside one fresh attempt | Whether the infer loop can recover from malformed model output |
| Provider retries | Repeats one physical provider request after a transient error | Infrastructure reliability; reported separately |
| `llm_steps` | Counts action proposals inside an attempt | How much infer-loop work the model needed |

For example, `40 cases × 3 repetitions = 120` scored logical results.
`--attempts 2` does not change that denominator; it only permits a second fresh
task when the first one did not pass strictly, so the number of executed
attempts and provider calls can be higher.

Use one attempt when measuring pure pass-at-one reliability. Use multiple
attempts when you also want to know whether failures are recoverable. Use at
least two repetitions for the repeat/cache probe.

When multiple fresh attempts are enabled, the HTML attempt-review section keeps
the failed attempts visible even if a later attempt passes. This prevents an
eventual strict result from hiding the exact request, output, or action that
failed first.

## Timing and prompt-cache signals

Correctness and speed are separate outputs. A faster wrong answer never
improves `STRICT`.

| Metric | Interpretation |
| --- | --- |
| `scored_wall_ms` | Elapsed wall time for scored tasks only; preflight, mesh startup, warm-up, and teardown are separate |
| Attempt end-to-end | Complete task latency, including infer-loop and deterministic Agent/tool work |
| LLM latency | Sum of completed logical model-call latency inside an attempt |
| `non_llm_latency_ms` | End-to-end minus LLM latency, only when every started provider call completed |
| Strict first-try median / p95 | Typical and tail latency among clean first attempts |
| Ollama prompt-eval / eval / load | Provider-reported phase durations in nanoseconds, converted to milliseconds |
| Repeat speedup | Positive means the later adjacent repetition was faster; negative means it was slower |
| Baseline `median-delta` | Current minus baseline in milliseconds; positive is slower and negative is faster |

Runner-side wall, attempt, and logical-call durations use Python's monotonic
`time.perf_counter` clock. Ollama's load, prompt-evaluation, generation, and
total durations come from Ollama. All exported timing fields are normalized to
milliseconds.

If a call times out or fails while in flight, `non_llm_latency_ms` is left
unavailable. This prevents provider wait time from being mislabeled as
non-model runtime overhead.

### Measure the repeat signal

```bash
python -m benchmarks.infer_loop \
  --provider ollama \
  --model gemma4:e4b \
  --suite core \
  --repetitions 3 \
  --warmup 1 \
  --run-name prompt-before
```

Identical case repetitions run next to each other. The repeat probe pairs only
retry-free strict first attempts with the same number of model calls. It
reports median end-to-end, model, first-call, and prompt-evaluation speedups
when the required data exists.

The first-call comparison is the cleanest controlled prompt signal because
equivalent repetitions begin with equivalent provider inputs. Whole-attempt
timing also contains the model-generated action history from later infer-loop
calls.

:::caution[Cache-sensitive does not mean cache-confirmed]

Ollama exposes prompt-evaluation and load timing, but not an unambiguous cache
hit flag. A faster repeated prompt is useful evidence, not proof that a
particular request hit a cache. Small suites are noisy: use `core` or `full`,
repeat controlled runs, and compare on the same machine under similar load.

The default unscored Ollama warm-up is one direct-final task. Its outcome and
timing are recorded. `--warmup 0` is only a cold-ish measurement because the
runner cannot unload an Ollama model or clear the server cache.

:::

## Compare before and after

Treat the comparison as a controlled experiment. Keep the machine, model
build, provider URL, generation settings, suite, seed, filters, ordering,
attempts, repetitions, action mode, timeout, and warm-up constant. Change only
the prompt or infer-loop behavior you intend to evaluate.

### 1. Record the baseline

```bash
python -m benchmarks.infer_loop \
  --provider ollama \
  --model gemma4:e4b \
  --suite core \
  --seed 1337 \
  --attempts 2 \
  --repetitions 2 \
  --run-name infer-before
```

### 2. Run the candidate against it

```bash
python -m benchmarks.infer_loop \
  --provider ollama \
  --model gemma4:e4b \
  --suite core \
  --seed 1337 \
  --attempts 2 \
  --repetitions 2 \
  --run-name infer-after \
  --baseline benchmark_results/infer-before/summary.json
```

The report shows strict-score delta, fixed and regressed logical cases, and
paired timing deltas for retry-free strict first attempts that exist in both
runs. Model and prompt-evaluation pairs also require the same infer-loop call
count.

A **performance-fingerprint warning** means a timing-relevant setting or
warm-up outcome differs, so timing deltas are not directly comparable. Prompt
hashes may differ—that is expected when the prompt is the variable under test.
Case identity may not differ: the suite hash and logical case keys must match.

### Test a prompt file without editing benchmark source

```bash
python -m benchmarks.infer_loop \
  --provider ollama \
  --model gemma4:e4b \
  --suite core \
  --system-prompt-file ./candidate-infer-instructions.txt
```

`--system-prompt-file` replaces the benchmark's complementary coordinator
instructions. ProtoLink's internal action-format prompts are still constructed
by the infer loop. The report records separate prompt hashes so you can tell
which layer changed.

## Find the right artifact

Each run creates a child directory under `benchmark_results/`.
`--output-dir` changes the parent; `--run-name` gives the child a stable name
instead of the timestamped default.

```text
benchmark_results/<run-name>/
├── report.html
├── summary.json
├── results.csv
├── failures.csv
├── llm_calls.csv
└── traces.jsonl
```

| Open this file when you want to… | File |
| --- | --- |
| View headline strict/functional/first-try scores, category bars, contained latency charts, repetition/cache-sensitive metrics, optional baseline comparison, unresolved and rescued attempt diagnostics, and run configuration | `report.html` |
| Read the configuration, generated case definitions, hashes, score distributions, model decisions, repeat signal, or baseline comparison | `summary.json` |
| Triage cases that never achieved a strict pass | `failures.csv` |
| Analyze every executed fresh attempt, including later rescue attempts and normalized model-action decisions | `results.csv` |
| Inspect per-call latency, physical attempts, tokens, and provider timing/cache fields | `llm_calls.csv` |
| Audit the redacted runtime evidence used for validation | `traces.jsonl` |

The default `benchmark_results/` directory is ignored by Git so local model
runs do not pollute commits.

### How diagnostic data is organized

`summary.json` keeps case definitions separate from attempt outcomes:

- `case_definitions` records each selected case once, including its prompt,
  expected final output, expected action sequence, forbidden values, and action
  ordering rule.
- `case_results` records every logical case repetition and all fresh attempts.
- Each attempt includes `final_output`, `expected_actions`,
  `observed_actions`, `trace_actions`, and `model_actions`.

These fields answer different questions:

| Field | Question it answers |
| --- | --- |
| `final_output` | What final text did the task actually produce? |
| `expected_actions` | Which exact successful route and operations did the oracle require? |
| `observed_actions` | Which operations actually reached the independent benchmark ledger successfully? |
| `trace_actions` | Which successful operations did runtime telemetry independently observe? |
| `model_actions` | Which normalized actions did the model propose, including an action that was parsed successfully but failed during dispatch? |

`model_actions` is especially important for crashes before final output. A
failed delegated call may never appear in `observed_actions`, because that list
contains successful benchmark operations. The model-decision record still
shows the target, action type, tool, arguments, or inference prompt that caused
the failure. Parse-recovery entries record the parse error and whether it was
recoverable; they do not claim that malformed provider text was a successfully
parsed action.

## Filtering and CI

List cases without contacting a provider:

```bash
python -m benchmarks.infer_loop \
  --suite core \
  --list-cases
```

Select categories or case-ID patterns with repeatable flags:

```bash
python -m benchmarks.infer_loop \
  --suite full \
  --category routing_choice \
  --case 'routing-choice-*' \
  --limit 20
```

The default full suite contains 20 routing-choice cases, so the following runs
that complete category without contacting the other templates:

```bash
python -m benchmarks.infer_loop \
  --suite full \
  --category routing_choice
```

`--shuffle` changes the selected order deterministically with `--seed`. Record
the full command because seed, generated count, filters, and ordering define
suite identity.

For automation, `--fail-under 90` exits with status `2` when the strict
percentage is below the threshold, after artifacts are written. Infrastructure
failures exit `1`; interruption exits `130`.

For every provider option, output field, schema detail, and advanced example,
see the repository's
[detailed benchmark guide](https://github.com/nMaroulis/protolink/blob/main/benchmarks/infer_loop/README.md).

## Scope and limitations

- The benchmark validates closed-world action correctness, not open-domain
  factuality or prose quality.
- Routing-choice prompts are synthetic and intentionally unambiguous. They test
  action-mode selection and routing among a small, controlled set of
  specialists with plausible overlapping decoys. They do not measure
  open-ended organizational planning, negotiation among Agents, or discovery
  in a large and continuously changing marketplace.
- Decoy specialists can deliberately return the same controlled result as the
  authoritative specialist. This makes target selection independently
  measurable, but it should not be interpreted as a realism claim about stale
  archives or generic planning systems.
- Runtime `output_schema` metadata is carried through the task but is not
  currently enforced by the infer loop; the benchmark therefore uses its own
  exact deterministic oracle.
- `RuntimeTransport` includes ProtoLink task serialization, registry,
  delegation, tools, telemetry, and infer-loop work, but excludes HTTP,
  WebSocket, gRPC, and real-network performance.
- Per-task timeouts are cooperative and best-effort. A blocking provider
  request or action already in progress may not stop exactly at the boundary.
- Model execution can vary even at temperature zero. Repetitions and controlled
  settings improve comparison quality but do not provide a statistical
  guarantee.
- The full suite may require many generations because delegated and multi-step
  cases use several infer-loop steps.

:::note[Use the score as a regression signal]

The benchmark is strongest when comparing two controlled runs of the same
catalog and model configuration. It is not a universal ranking of models,
providers, machines, or prompt quality.

:::
