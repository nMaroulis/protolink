# Benchmark

The repository includes a **deterministic benchmark** for deciding whether a
change to ProtoLink's prompts or **infer loop** improved correctness, reliability,
or execution time. It runs real infer tasks through an in-process agent mesh
and produces a headline strict score such as `180/200`, detailed failure
diagnostics, and cache-sensitive timing comparisons.

The benchmark is development tooling under `benchmarks/`. It is intentionally
outside the installable `protolink` package and must be run from the repository
root.

## Quick start

Start Ollama, install the model you want to evaluate, and run:

```bash
python -m benchmarks.infer_loop \
  --provider ollama \
  --model gemma4:e4b \
  --suite smoke
```

The default Ollama URL is `OLLAMA_URL`, then
`http://localhost:11434`. Defaults are temperature `0`, sampling seed `1337`,
context size `8192`, generation limit `2048`, JSON-prompt action mode, and one
unscored warm-up.

Use `core` for routine comparisons and `full` for the fixed 200-case catalog:

```bash
python -m benchmarks.infer_loop \
  --provider ollama \
  --model gemma4:e4b \
  --suite full \
  --run-name full-baseline
```

## What is tested

The generated catalog covers:

- exact direct final answers;
- local tool selection and typed arguments;
- tool calls delegated to the correct specialist agent;
- inference delegated with required prompt evidence;
- dependent multi-step actions whose receipts must be passed forward;
- grounding traps where an untrusted value conflicts with an authoritative
  tool or agent observation.

Specialists return deterministic data and opaque `BENCH-...` receipts that are
not present in the task prompt. A model cannot pass by merely claiming it
called an agent or by inventing a plausible answer.

## Scores and attempts

`STRICT` is the headline score. A strict pass requires:

1. a completed task with the exact expected final output;
2. exactly the expected tools and agents, arguments, and action order in the
   independent execution ledger;
3. matching successful actions in the local trace;
4. no parse recovery, duplicate action, invalid tool, or invalid agent attempt.

`FUNCTIONAL` accepts a correct result after infer-loop self-correction, which
makes recoveries visible without counting them as clean strict passes.
`FIRST TRY` prevents multiple fresh attempts from hiding pass-at-one
reliability.

`--attempts N` allows up to `N` fresh attempts per logical case and stops after
the first strict pass. `--repetitions N` repeats each case adjacently and keeps
every repetition as a separate logical result. Internal parse retries and
physical provider retries are counted separately.

## Timing and prompt caching

Runner-side wall and call timing uses the monotonic `time.perf_counter` clock.
Ollama phase durations come from the provider in nanoseconds and are converted
to milliseconds. All machine-readable timing fields use milliseconds. The
summary separates:

- scored suite wall time from preflight, mesh startup, warm-up, and teardown;
- end-to-end attempt latency;
- summed model-call latency and non-model/runtime overhead;
- strict first-attempt median, mean, p95, minimum, maximum, and total latency;
- latency by repetition and infer-loop step;
- provider token usage;
- Ollama load, prompt-evaluation, generation, and total durations and
  throughput when returned by Ollama;
- explicit cached or cache-write input tokens when another provider exposes
  them.

Non-model overhead is calculated only when every started provider call has a
matching completion event. Timeouts and in-flight provider failures leave that
decomposition unavailable instead of treating model wait time as runtime
overhead.

For a cache-sensitive comparison, use at least two repetitions:

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
retry-free strict first attempts with the same number of model calls, then
reports median end-to-end, model, and prompt-evaluation speedup. First-call
timing compares equivalent initial provider inputs; whole-attempt timing also
includes model-generated action text in later call history. Ollama provides
evaluation timings, not an unambiguous cache-hit flag, so this is deliberately
called a **cache-sensitive repeat signal**, not proof that a specific request
hit a cache.

One warm-up is useful for steady-state comparisons. `--warmup 0` gives a
cold-ish measurement, but ProtoLink cannot force an Ollama server to unload a
model or clear its cache. Compare results on the same machine under similar
load, with the same model build, generation settings, suite order, warm-up,
attempt count, and repetitions.

## Artifacts

By default, each run writes a timestamped directory below
`benchmark_results/`:

```text
benchmark_results/<run-name>/
├── summary.json
├── results.csv
├── failures.csv
├── llm_calls.csv
└── traces.jsonl
```

- `summary.json` contains configuration, prompt and suite hashes, scores,
  timing distributions, repeat signals, baseline deltas, and logical results.
- `results.csv` has one row per fresh attempt.
- `failures.csv` contains attempts from cases that never passed strictly.
- `llm_calls.csv` has one row per logical model call, including provider timing
  and cache fields when available.
- `traces.jsonl` contains the redacted runtime evidence used for validation.

## Before-and-after comparison

Record the baseline with controlled settings:

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

After the prompt or infer-loop change, repeat the same command with a baseline:

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

The comparison lists fixed and regressed cases and reports paired timing
deltas for strict first attempts. A recorded performance-fingerprint mismatch
warns when provider, model, model parameters, action mode, timeout, warm-up
outcome, verbosity, or repetition order differs. Prompt hashes are allowed to
differ because changing the prompt is a primary use case.

## Filtering and CI

Use `--list-cases` without contacting a provider. Cases can be selected with
repeatable `--category` and `--case` options, then limited or deterministically
shuffled.

`--fail-under 90` exits with status `2` when the strict percentage is below the
threshold, after artifacts are written. Infrastructure failures exit `1`, and
an interrupted run exits `130`.

For every CLI option, schema detail, limitation, and additional example, see
the repository's
[benchmark guide](https://github.com/nMaroulis/protolink/blob/main/benchmarks/infer_loop/README.md).

## Scope and limitations

The benchmark validates closed-world action correctness; it is not an
open-domain factuality judge. It uses `RuntimeTransport`, so its timing covers
the infer loop and in-process agent/tool work rather than HTTP, WebSocket, or
gRPC transport performance. Provider calls and model execution may remain
nondeterministic even at temperature zero, so use repeated controlled runs
rather than treating one timing sample as a guarantee.
