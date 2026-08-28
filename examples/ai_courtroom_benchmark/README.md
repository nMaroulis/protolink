# AI Courtroom Advocacy Benchmark

> Put two LLMs on opposite sides of the same case, swap their roles, and replay
> how a fixed jury responds to every argument.

This example is a portable, paired benchmark for model-to-model persuasion. It
uses the fictional C-91 autonomous-vehicle case from
[`examples/ai_courtroom`](../ai_courtroom/), but asks a different question.
Instead of comparing jury communication topologies, it compares the two models
acting as advocates.

Only Aster Vale Mobility is the defendant. The two model roles are advocates:

- counsel for Lina Ortega's family, arguing for the configured positive vote;
- counsel for Aster Vale, arguing for the configured negative vote.

The judge and independent jurors are also ProtoLink agents. They stay fixed
while Model A and Model B exchange sides. Every public argument, evidence
citation, juror update, vote change, retry, and A2A task is saved for replay.

The included case and every person in it are fictional. This is a software
experiment, not legal analysis, legal advice, or a validated measure of human
persuasion.

## Why the benchmark swaps roles

A single trial cannot separate model quality from side advantage. The default
paired run therefore performs two legs:

| Leg | Lina's family | Aster Vale |
| --- | --- | --- |
| 1 | Model A | Model B |
| 2 | Model B | Model A |

Both legs use the same case file, admitted evidence, stage order, judge, juror
personas, control backend, temperature, and seed. Each leg creates fresh agents
so no conversation history crosses the role swap.

The default jury is independent. Jurors update after each public argument but
do not communicate with one another. This keeps the opinion pipeline focused
on advocacy rather than adding a second persuasion treatment inside the jury.

`single` mode runs one controlled assignment for debugging or exploration. It
does not swap roles, does not control side advantage, and does not produce a
role-balanced candidate score. Use paired mode for candidate comparisons.

There are no witness agents in this benchmark. A live witness would add another
stochastic model between an advocate's words and the jury's response, and its
answers could change across legs. Both advocates instead receive the same
complete admitted record and get the same opening, rebuttal, and closing
opportunities.

## Quick start

Run from the repository root:

```bash
python examples/ai_courtroom_benchmark/run.py
```

The default run is offline and deterministic. It compares the
`reference-evidence` and `reference-narrative` fixtures in paired mode, uses the
bundled C-91 case, and requires no API key or network connection. The fixtures
exist to exercise the benchmark, role swap, metrics, traces, and HTML report.
They are not real language models and their result is not a leaderboard.

The command prints the exact output directory and the path to the standalone
HTML report when it finishes.

Run a single leg:

```bash
python examples/ai_courtroom_benchmark/run.py \
  --mode single \
  --model-a-side victim_family \
  --seed 17
```

Use another case configuration:

```bash
python examples/ai_courtroom_benchmark/run.py \
  --case examples/ai_courtroom_benchmark/cases/template.json
```

Validate a case and preview the complete execution plan without starting agents,
creating an output directory, or making model calls:

```bash
python examples/ai_courtroom_benchmark/run.py \
  --case examples/ai_courtroom_benchmark/cases/template.json \
  --mode paired \
  --replicates 3 \
  --plan
```

Plan mode prints the evidence, juror, stage, argument, trial, and scheduled A2A
exchange counts. It also validates reference fixture names and requires exact
model IDs for live providers. Because it makes no live calls, `--plan` does not
require `--allow-live`, even when live providers are selected.

## Compare live models

Install the optional model clients first:

```bash
python -m pip install -e '.[llms]'
```

Then select an exact provider and model ID for each candidate and for the fixed
control panel. Model IDs are required for live providers. The values below are
placeholders because availability and naming vary by account and over time:

```bash
export ANTHROPIC_API_KEY="..."
export OPENAI_API_KEY="..."

python examples/ai_courtroom_benchmark/run.py \
  --model-a-provider anthropic \
  --model-a "your-exact-anthropic-model-id" \
  --model-a-label "Candidate A" \
  --model-b-provider openai \
  --model-b "your-exact-openai-model-id" \
  --model-b-label "Candidate B" \
  --control-provider ollama \
  --control-model "your-fixed-control-model-id" \
  --control-base-url "http://localhost:11434" \
  --temperature 0 \
  --seed 17 \
  --replicates 3 \
  --mode paired \
  --allow-live
```

`--allow-live` is an explicit acknowledgement that paired legs and replicates
multiply model calls. Begin with one replicate. Check the output, token counts,
and protocol repairs before increasing the run size.

The seed is applied by the deterministic reference fixture. Live provider
adapters in this example record the seed and replicate schedule but do not pass
the seed into generation. The fairness audit warns when any live model is used.

Supported providers are:

- `reference`
- `openai`
- `anthropic`
- `gemini`
- `ollama`
- `openai-compatible`

Use the candidate-specific base URL flags for Ollama or compatible servers.
Credentials come from the normal provider environment variables and must never
be placed in a case JSON file.

For a serious comparison, use one fixed control provider and exact model for
the judge and every juror. The offline reference jury is excellent for a
reproducible smoke test, but it responds to deterministic fixture signals. A
fixed live jury can react to more of the candidates' language, although it also
introduces evaluator variance and cost.

## CLI

| Option | Purpose |
| --- | --- |
| `--case PATH` | Load a portable JSON case. Defaults to `cases/c91_incident.json`. |
| `--model-a-provider PROVIDER` | Provider for candidate Model A. |
| `--model-a MODEL` | Exact model ID, required for live providers, or reference-fixture variant for Model A. |
| `--model-a-label LABEL` | Human-readable label used in the report. |
| `--model-a-base-url URL` | Optional endpoint for Model A. |
| `--model-b-provider PROVIDER` | Provider for candidate Model B. |
| `--model-b MODEL` | Exact model ID, required for live providers, or reference-fixture variant for Model B. |
| `--model-b-label LABEL` | Human-readable label used in the report. |
| `--model-b-base-url URL` | Optional endpoint for Model B. |
| `--control-provider PROVIDER` | Fixed provider for the judge and jurors. |
| `--control-model MODEL` | Exact fixed control model ID, required for live providers. |
| `--control-base-url URL` | Optional endpoint for the control backend. |
| `--temperature FLOAT` | Shared generation temperature from `0` through `1`. |
| `--seed INTEGER` | Applied by reference fixtures; recorded but not applied by live providers. |
| `--replicates INTEGER` | Number of repeated paired or single runs. |
| `--mode paired\|single` | Swap candidates across both sides or run one non-role-balanced assignment. |
| `--model-a-side SIDE_ID` | In single mode, bind Model A to this configured side. Defaults to the case's positive side. |
| `--max-attempts INTEGER` | Application-schema attempts allowed per A2A exchange. |
| `--action-parse-attempts INTEGER` | Internal ProtoLink action-envelope attempts per task. |
| `--allow-live` | Acknowledge live-provider usage. |
| `--plan` | Validate the case and print call counts without starting agents or making model calls. |
| `--output-dir PATH` | Choose the generated artifact directory. |
| `-q`, `--quiet` | Reduce application progress output. |
| `-v`, `--verbose` | Show detailed A2A progress and repairs. |
| `--agent-verbosity 0\|1\|2` | Control ProtoLink's own agent logs independently. |

Provider-specific model and base URL values are intentionally isolated. A model
or endpoint selected for one provider must not leak into another candidate or
the fixed control agents.

## Portable case configuration

The runner accepts strict JSON so the example needs no YAML dependency. Unknown
keys, duplicate participant IDs, duplicate evidence IDs, invalid side
references, and inconsistent vote mappings are rejected before any agents are
started.

[`cases/c91_incident.json`](cases/c91_incident.json) contains the full bundled
case. [`cases/template.json`](cases/template.json) is a small, valid starting
point for a new case.

The top-level fields are:

| Field | Meaning |
| --- | --- |
| `schema_version` | Portable case schema version. The supported value is `1.0`. |
| `id`, `title` | Stable machine ID and public title. |
| `summary` | Shared orientation delivered before advocacy begins. |
| `question`, `charge`, `burden` | The exact binary decision and its fictional rule. |
| `elements` | Requirements the positive side is trying to establish. |
| `decision` | Positive, negative, and tie vote policy plus the two side mappings. |
| `evidence` | Ordered admitted exhibits with an ID, title, and public text. |
| `sides` | Exactly two advocate roles, objectives, target votes, and prompts. |
| `judge` | The fixed neutral procedural agent. |
| `jurors` | Fixed independent evaluator personas. |
| `procedure.stages` | Ordered speaking stages and their side order. |
| `reference_fixture` | Optional deterministic controls used only by the offline provider. |

The decision vocabulary is case-neutral. A criminal-fiction example can use
`guilty` and `not_guilty`; another case can use `approve` and `reject`, or any
two lowercase IDs:

```json
{
  "probability_label": "probability that approval is warranted",
  "positive_vote": "approve",
  "negative_vote": "reject",
  "tie_vote": "reject",
  "positive_side_id": "applicant",
  "negative_side_id": "reviewer"
}
```

`tie_vote` is required and must equal either `positive_vote` or
`negative_vote`. Each side's `target_vote` must match the vote assigned to that
side. Each stage lists the side IDs that speak and whether prior public
arguments are included in the next prompt:

```json
{
  "id": "rebuttal",
  "label": "Rebuttals",
  "instruction": "Answer the strongest opposing argument using admitted evidence.",
  "speakers": ["reviewer", "applicant"],
  "include_prior_arguments": true
}
```

To create a case:

1. Copy `cases/template.json` to a new filename.
2. Give every case, side, judge, juror, and stage a stable lowercase ID.
3. Write one precise binary question, burden, and set of elements.
4. Add admitted evidence. Evidence IDs do not have to be `E1`, `E2`, and so on,
   but they must be unique.
5. Define exactly two sides and map each one to a different configured vote.
6. Choose the required `tie_vote`, even when the configured jury has an odd
   number of members.
7. Give both sides equal procedural opportunities and keep stage order fixed
   across candidate comparisons.
8. Run the new file with `--case` and inspect the validation error if a
   cross-reference is inconsistent.

Invalid JSON, unsupported schema versions, and inconsistent cross-references
produce a concise CLI error before an output directory or agent is created.

Do not put API keys, personal data, confidential evidence, or untrusted private
material in a case file. Case text, prompts, public outputs, and traces are
written to disk and may appear in the HTML report.

### Offline reference controls

`reference_prior`, `reference_receptiveness`, and `reference_threshold` are
fixture parameters for deterministic offline runs. They are not inserted into
the juror's natural-language persona prompt. `reference_fixture.evidence_signals`
assigns each admitted evidence ID a signed deterministic signal: positive
values point toward the configured positive vote and negative values point
toward the configured negative vote.

These fields make a new case reproducible without a live provider. They should
not be described as human psychology, ground truth, or a model evaluation.

### Strict public assessments and citation grounding

Every juror response must contain a finite numeric `support_probability` from
`0` through `100`. Values outside that range are rejected and repaired through
the application schema. Fractions are not rescaled, so `0.5` means 0.5, not 50.

Public advocacy statements have a provider-neutral limit of 2,400 characters,
and their one-sentence theses have a 400-character limit. Overlong responses
are rejected and repaired instead of being silently truncated, so the content
evaluated by jurors is exactly the validated public treatment.

An advocacy citation counts as grounded only when an admitted evidence ID is
visibly present as a complete token in the public statement. The validator
separately records valid declared IDs, valid declarations that never appear in
the statement, and unknown declared IDs. It also finds admitted IDs that are
visible in the statement but omitted from the declaration and emits a mismatch
warning. This makes `E1` distinct from text such as `E10`.

Grounding is visible citations divided by all citation attempts, including
declared-only and unsupported IDs. When there are no citation attempts, the
grounding rate is `N/A`, not a perfect score.

## What the report shows

The run creates one standalone HTML report that opens locally without a server
or external JavaScript. It is organized around the paired role swap:

- Model A and Model B assignments in both legs;
- verdicts and categorical vote tallies;
- every juror's probability trajectory after each public argument;
- opinion changes aligned to the side each model was advocating;
- the exact opening, rebuttal, and closing statements;
- evidence citations and coverage by model, role, and stage;
- vote flips toward and away from each advocate's target;
- configured providers and exact model IDs, plus runtime-resolved IDs when the
  adapter exposes them;
- retries, validation warnings, estimated tokens, and latency;
- a fairness audit for case, procedure, seed, temperature, and control models.

The public event ledger remains available in the generated data even when
JavaScript is disabled. No private chain-of-thought is requested or displayed.
Candidate IDs, report labels, provider names, and model IDs are removed from
juror payloads, and recognized explicit disclosures in either the public
statement or thesis are rejected before delivery. This is not complete
blinding: wording, style, or characteristic behavior can still let an evaluator
infer identity.

Each run writes a timestamped directory beneath `output/` unless
`--output-dir` is supplied. Its root contains `report.html`, `benchmark.json`,
`summary.json`, and `transcript.md`. Each trial directory contains its own
`result.json` and `traces.jsonl`. Before a rerun, root report artifacts and
known `result.json` and `traces.jsonl` files inside recognized trial directories
are cleaned so stale data cannot enter a new report. Unrelated files in a
reused output directory are preserved.

If a leg fails, the runner preserves its partial result, completed event ledger,
trace file, error, and root-level report, then continues with the remaining
scheduled legs. Failed legs appear in the fairness audit and reliability
counts. In paired mode, outcome wins, movement, and vote flips are calculated
only from replicates where both reciprocal legs completed, so an orphaned leg
cannot create an apparently balanced comparison. Grounding and reliability
still include every attempted leg. The aggregate records `complete_pairs` and
`scored_trials`, and the CLI returns a nonzero exit code after writing artifacts
so automated runs cannot mistake a partial benchmark for a clean result.

## Metrics and interpretation

The benchmark reports dimensions separately rather than hiding them inside one
opaque score:

- **Outcome:** verdict, vote margin, and side wins in each role-swapped leg.
- **Observed aligned movement:** mean juror probability change after a model's
  public arguments. Movement toward `positive_vote` is positive for the
  positive advocate; movement toward `negative_vote` is positive for the
  negative advocate.
- **Vote conversion:** categorical flips toward and away from the model's
  current target vote.
- **Grounding:** admitted IDs visibly cited in public text, declared-only IDs,
  unsupported declarations, and unique evidence coverage. Zero attempts are
  reported as `N/A`.
- **Protocol reliability:** first-attempt success, application-schema repairs,
  warnings, blocked metadata disclosures, and failed exchanges.
- **Efficiency:** application-task token estimates and latency, kept separate
  from quality.
- **Role balance:** the same candidate's results from complete reciprocal pairs
  when advocating each side. `complete_pairs` and `scored_trials` make the
  denominator explicit. The balanced metric is `N/A` in single mode or when no
  full pair completed.

Application-schema repair counts and task token estimates cover the benchmark
tasks and their application-level retries. They exclude ProtoLink's internal
action-envelope parsing attempts. Token values are estimates, not provider
billing records.

An opinion update immediately after an argument is an observed after-message
shift, not proof that the argument caused the entire change. Evidence-ID
validity shows that an exhibit was admitted and cited; it does not prove that a
claim logically follows from it. A persuasive model can also move a jury away
from the best-supported outcome.

For that reason, this example can support a persuasion benchmark now, but it
does not by itself validate broad claims about logical reasoning. A reasoning
study should add a preregistered, blinded claim-to-evidence rubric and fixed
evaluators, then report that rubric separately from persuasion.

## Running a defensible experiment

For results intended for publication:

1. Freeze the case JSON, prompts, stage order, control provider and model,
   temperature, retry budgets, and code revision.
2. Use paired role swaps for every seed.
3. Repeat every matchup enough times to show variance. Reference seeds change
   the deterministic fixture; live seeds are labels unless the provider has a
   separately verified seeded-generation contract.
4. Record runtime-resolved model IDs when available and retain the exact model
   IDs supplied on the CLI.
5. Include failures, invalid citations, repairs, latency, and token estimates.
6. Inspect the fairness audit before comparing scores. Different public-record
   hashes are expected because the candidates wrote different arguments;
   different case or control fingerprints are not.
7. Add A/A and B/B controls, then neutral-message or argument-ablation runs if
   you want stronger causal evidence.
8. Consider multiple fixed jury models or a balanced evaluator rotation. Five
   LLM jurors are a synthetic evaluator panel, not a sample of people.
9. Report persuasion, grounding, reliability, and any external reasoning rubric
   on separate axes.
10. Describe the result as performance in this protocol and case set, not as a
    universal ranking of intelligence or truthfulness.

Temperature zero is not a determinism guarantee for live providers. A paired
role swap also changes both advocates simultaneously, so it controls obvious
side assignment bias but does not isolate one candidate's causal effect.

## Tests

The offline suite makes no provider calls:

```bash
pytest -q examples/ai_courtroom_benchmark/tests
```

The repository's default pytest discovery targets the root `tests/` directory,
so run this example's tests explicitly when working on it.

## Directory map

```text
examples/ai_courtroom_benchmark/
├── run.py
├── README.md
├── cases/
│   ├── c91_incident.json
│   └── template.json
├── courtroom/
│   ├── benchmark.py
│   ├── config.py
│   ├── providers.py
│   ├── reference_llm.py
│   ├── reporting.py
│   ├── schemas.py
│   └── simulation.py
├── tests/
└── output/
    └── .gitignore
```

The original [`examples/ai_courtroom`](../ai_courtroom/) remains the topology
experiment. This directory is the modular advocacy benchmark and does not
change the original example's CLI, deterministic verdicts, schema, or tests.
