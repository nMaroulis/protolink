# Infer-loop benchmark

The infer loop is the part of ProtoLink that turns a model response into one
validated next action: a final answer, a local tool call, or a delegation to
another agent. This benchmark is intended for comparing infer-loop and prompt
changes with the same provider, model, and generation settings.

It runs the normal `AgentClient -> Agent -> LLM` path against a deterministic
in-process mesh. The benchmark coordinator has local tools and can delegate
tool calls or inference to specialist agents. Those specialists return
closed-world values and opaque `BENCH-...` receipts, so the coordinator must
actually execute the expected action and use its observation to produce the
exact final answer.

Run the CLI from the repository root:

```bash
python -m benchmarks.infer_loop --help
```

The benchmark is repository tooling, not part of the installable `protolink`
package. Run it from a source checkout so it evaluates the code and prompt
files in that checkout.

## Quick start with Ollama and Gemma

Start Ollama and make sure the requested model is installed, then run the
12-case smoke suite:

```bash
python -m benchmarks.infer_loop \
  --provider ollama \
  --model gemma4:e4b \
  --base-url http://localhost:11434 \
  --suite smoke
```

`--base-url` defaults to `OLLAMA_URL`, then
`http://localhost:11434`. The benchmark uses deterministic-oriented Ollama
settings by default: temperature `0`, model seed `1337`, context size `8192`,
and generation limit `2048`.

For another Gemma model:

```bash
OLLAMA_URL=http://localhost:11434 \
python -m benchmarks.infer_loop \
  --provider ollama \
  --model gemma3:4b \
  --suite core \
  --attempts 2
```

Ollama uses ProtoLink's JSON prompt action protocol by default. Enable
`--supports-tool-calling` only when the selected model supports Ollama's native
tool interface; results from native and JSON-prompt modes should be treated as
different benchmark configurations.

Provider generation options can be changed with convenience flags or repeated
key/value arguments:

```bash
python -m benchmarks.infer_loop \
  --provider ollama \
  --model gemma4:e4b \
  --temperature 0 \
  --model-seed 1337 \
  --num-ctx 16384 \
  --model-param top_k=20 \
  --suite core
```

Values passed to `--model-param` and `--provider-option` are parsed as JSON
when possible. Use `--api-key-env NAME` for hosted providers rather than
putting credentials on the command line.

## Suites and task coverage

The generated catalogs have fixed default sizes:

| Suite | Cases | Intended use |
| --- | ---: | --- |
| `smoke` | 12 | Fast check while editing prompts or the infer loop |
| `core` | 40 | Routine before/after development comparison |
| `full` | 200 | Slower release or regression baseline |

Cases are generated deterministically from `--seed` and cover these
categories:

- `direct_final`: finish without calling a tool or agent.
- `local_tool`: select and execute a coordinator-owned tool.
- `delegated_tool`: select an agent, tool, and exact typed arguments.
- `delegated_infer`: send a constrained prompt to an inference specialist.
- `multi_step`: consume one receipt in a later dependent action.
- `grounding_trap`: ignore untrusted or stale values and use the authoritative
  observation.

`--count` overrides a suite's generated size. Changing the seed, count, or
selected cases changes the suite hash and therefore creates a different
baseline.

## Strict and functional scores

The headline score is `STRICT`, for example:

```text
STRICT     36/40 (90.0%)
FUNCTIONAL 38/40 (95.0%)
FIRST TRY  34/40 (85.0%)
```

A functional pass requires all of the following:

- the task completed without an exception or timeout;
- the final `infer_output` exactly matched the deterministic oracle;
- the independent execution ledger contained exactly the expected successful
  actions;
- the runtime trace contained the same successful actions, targets, arguments,
  and order.

A strict pass is a functional pass whose protocol path was also clean. It has
no parse recovery, duplicate-action retry, invalid local tool attempt, or
invalid agent-call attempt.

This distinction makes self-correction visible. A model that first invents an
agent and later recovers may be functionally correct, but it does not receive a
strict pass. Provider-level transient retries are reported as diagnostics and
do not by themselves make an otherwise clean result non-strict.

## Attempts, repetitions, and internal retries

These controls measure different things:

| Control or metric | Meaning |
| --- | --- |
| `--attempts N` | Run a fresh task up to `N` times for each logical case, stopping after its first strict pass |
| `--repetitions N` | Repeat each case `N` times adjacently; each repetition remains a separate logical result and feeds the cache-sensitive repeat probe |
| `--max-parse-failures N` | Infer-loop correction budget inside one fresh attempt |
| Provider retries | Automatic retries of one physical provider call after a transient error; observed in diagnostics |
| `llm_steps` | Number of infer-loop action proposals used by an attempt |

Later attempts do not erase the first result. The summary reports pass-at-first
attempt and how many cases were rescued on a later fresh attempt. Use the same
attempt and repetition settings for meaningful before/after comparisons.
Use at least `--repetitions 2` when you want the paired repeat/cache signal.

## Filtering and inspecting cases

List generated cases without contacting the provider:

```bash
python -m benchmarks.infer_loop \
  --suite core \
  --list-cases
```

Run one or more categories:

```bash
python -m benchmarks.infer_loop \
  --suite full \
  --category delegated_tool \
  --category multi_step
```

Filter case IDs with repeatable shell-style patterns:

```bash
python -m benchmarks.infer_loop \
  --suite full \
  --case 'multi-step-*' \
  --case 'grounding-trap-000[1-5]'
```

`--limit N` keeps the first `N` cases after filtering. `--shuffle` shuffles the
selection deterministically with `--seed`. Record the complete command because
filters, ordering, generated count, and seed are part of suite identity.

To test alternative complementary coordinator instructions without editing the
benchmark source:

```bash
python -m benchmarks.infer_loop \
  --suite core \
  --system-prompt-file ./candidate-infer-instructions.txt
```

## Results

Each run creates a child directory under `benchmark_results/`. `--output-dir`
changes that parent directory, and `--run-name` gives the child a stable name
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

- `report.html` is a self-contained visual report with headline scores,
  per-category correctness, reliability diagnostics, latency charts,
  repetition/cache-sensitive metrics, optional baseline comparison, strict
  failure details, and run configuration. Open it directly in a browser; it
  needs no server or external assets.
- `summary.json` contains provider settings, suite identity and hash, prompt
  hashes, git metadata, aggregate and per-category scores, and every logical
  case result.
- `results.csv` contains one row per executed fresh attempt.
- `failures.csv` contains attempts belonging to logical cases that never
  achieved a strict pass.
- `llm_calls.csv` contains one row per completed infer-loop model call, with
  call latency, physical attempts, token counts, and provider timing/cache
  fields when the provider exposes them.
- `traces.jsonl` contains redacted local runtime traces used for action and
  retry diagnostics.

The terminal summary also reports parse recovery, hallucinated-action,
crash/timeout, LLM-step, wall-clock, model-call, and repeat timing. Timing is
useful within a stable local environment but is not part of the correctness
score.

## Timing and prompt-cache signals

Runner-side wall and call durations use Python's monotonic
`time.perf_counter` clock. Ollama phase durations are reported by Ollama in
nanoseconds and converted to milliseconds. All exported timing fields use
milliseconds. The timing section separates:

- `scored_wall_ms`: wall time for scored tasks only;
- preflight, mesh startup, warm-up, and teardown wall time;
- end-to-end attempt latency;
- summed model-call latency and non-model/runtime overhead;
- first-attempt and strict-first-attempt median, mean, p95, minimum, maximum,
  and total latency;
- timing by repetition and infer-loop step;
- Ollama load, prompt-evaluation, generation, and total provider durations,
  plus prompt and generation throughput, when those fields are returned;
- explicit cached/cache-write input tokens for providers that expose them.

`non_llm_latency_ms` is populated only when every started provider call has a
matching completion event. A timeout or in-flight provider failure leaves that
decomposition blank instead of misclassifying model wait time as runtime
overhead.

Prompt caching is provider-specific. Ollama exposes prompt-evaluation and load
timings but does not report an unambiguous cache-hit flag. The benchmark
therefore labels its repeat result as a **cache-sensitive probe**, not proof of
a cache hit. With `--repetitions 2` or more, identical cases run adjacently and
the report compares retry-free strict first attempts with the same number of
infer-loop calls. First-call timing is the cleanest controlled prompt signal;
whole-attempt timing also includes model-generated action text in later call
history:

```bash
python -m benchmarks.infer_loop \
  --provider ollama \
  --model gemma4:e4b \
  --suite core \
  --repetitions 3 \
  --warmup 1
```

The default Ollama warm-up is `1`, which is appropriate for steady-state
comparisons. Use `--warmup 0` for a cold-ish run, but note that the benchmark
cannot force the provider to unload a model or clear its cache. Compare runs
on the same machine under similar load with the same model build, provider
settings, suite order, warm-up, and repetitions. Prefer the paired median and
p95 over one isolated call.

## Comparing a prompt change with a baseline

First record a baseline:

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

After changing the prompts or infer loop, repeat the same benchmark and point
to the previous summary:

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

The comparison reports the strict-score delta, paired end-to-end/model/prompt
evaluation timing deltas, and the logical cases that were fixed, regressed,
stable passes, or stable failures. Timing comparisons use retry-free strict
first attempts that exist in both runs; model and prompt-evaluation pairs also
require the same infer-loop call count. Baseline comparison
requires the same suite hash and logical case keys, so use the same suite,
seed, count, filters, shuffle setting, and repetitions. The benchmark only
enforces case identity; keep provider, model, action mode, model parameters,
attempts, warm-up, and system instructions controlled when attributing a delta
to one change. A performance-fingerprint warning is included when recorded
provider, warm-up outcome, verbosity, or runner settings differ; prompt hashes
may intentionally differ.

## CI threshold

`--fail-under` checks the strict percentage after artifacts have been written:

```bash
python -m benchmarks.infer_loop \
  --provider ollama \
  --model gemma4:e4b \
  --suite core \
  --quiet \
  --fail-under 90
```

The command exits with status `2` when the strict score is below the threshold,
`1` for benchmark infrastructure failure, and `130` when interrupted. Choose a
threshold from a stable baseline on the same model and runner; do not assume
that scores transfer between machines or model builds.

## Limitations

- Hallucination checks are closed-world. The benchmark detects invented or
  unexpected actions, incorrect routing, fabricated receipts, and failures to
  use authoritative synthetic observations. It does not judge the truth or
  quality of arbitrary open-domain prose.
- Infer-part `output_schema` metadata is currently carried through the task but
  is not enforced by the infer loop. The benchmark therefore validates every
  final answer with its own deterministic oracle.
- The mesh uses `RuntimeTransport`. It exercises ProtoLink task
  serialization, registry discovery, agent delegation, tools, telemetry, and
  the infer loop without binding ports, but it does not benchmark HTTP,
  WebSocket, gRPC, or real network behavior.
- The per-task timeout is best-effort. Cancellation is cooperative, and a
  blocking provider request or an action already in progress may not stop at
  the timeout boundary. Benchmark tools are synthetic, but callers should not
  interpret this mechanism as a hard side-effect boundary.
- Model execution can remain nondeterministic even with temperature zero.
  Repetitions and unchanged generation settings make regressions easier to
  interpret but do not provide a formal statistical guarantee.
- Latency depends heavily on model loading, hardware, and host load. Compare it
  only under controlled conditions and keep it separate from the strict score.
- The full suite may require many model generations because delegated and
  multi-step cases use several infer-loop steps. Use `smoke` during iteration,
  `core` for routine comparisons, and `full` for less frequent baselines.
