# AI Liability Tribunal

> **Can AI agents talk themselves into a better answer, or a worse one?**

This ProtoLink showcase puts autonomous agents inside a fictional liability
tribunal and makes their communication observable. The case is memorable, but
the case is not the product. The product is the interaction:

- agents with different roles, incentives, professions, and communication
  habits;
- direct ProtoLink agent-to-agent tasks;
- jurors who choose whom to address and what to ask;
- replayable opinion changes after every public message;
- solo, independent, foreperson-star, and direct-mesh comparisons;
- provider/model experiments using the same application protocol.

The default run is deterministic and offline. It produces JSON results,
ProtoLink traces, a public transcript, and standalone interactive HTML reports.

Everything and everyone in this example is fictional. It is a software
experiment, not legal analysis, legal advice, or a validated safety assessment.

<!--
FIGURE SUGGESTION — README hero / social preview
Placement: directly below the disclaimer above.
Format: 1600×900 PNG, readable when cropped to a GitHub social card.
Composition: a rain-dark autonomous-vehicle test scene on the left; on the
right, five distinct juror silhouettes connected by bright directed message
arcs; a slim replay timeline along the bottom. Keep the tribunal fictional and
avoid photorealistic injury, real manufacturer logos, gavels, and robot faces.
Palette: midnight navy, warm ivory, signal amber, restrained cyan.
Headline in image: “Can AI agents talk themselves into a different verdict?”
Small label: “An observable A2A experiment · powered by ProtoLink”.
Alt text: “Five specialist AI jurors exchange messages while their verdict
trajectories change in an autonomous-vehicle liability simulation.”
-->

## The case: The C-91 Incident

At 21:47 on a rain-soaked evening, an autonomous Aster Vale robotaxi struck and
killed 31-year-old cyclist Lina Ortega inside a temporary crossing. The car
began emergency braking only 0.35 seconds before impact. Thirty-six hours
earlier it received the Orchid 4.8 software release.

The fictional tribunal asks:

> **Is Aster Vale Mobility guilty of criminally negligent deployment of an
> autonomous vehicle system that caused Lina Ortega's death?**

The evidence creates an interacting-failures problem:

| ID | Admitted evidence |
| --- | --- |
| `E1` | Camera classification merged the cyclist and lane-arrow board; radar detected motion but braking was suppressed. |
| `E2` | An engineer had blocked release after 3 of 20 late-braking simulations, but a later calibration passed 20 of 20 reruns. |
| `E3` | The crashed car ran calibration C-91 while the safety report validated C-90; a CI bot shared the signing credential. |
| `E4` | A contractor moved the arrow board and failed to update the city map, removing roughly 1.1 seconds of useful observation. |
| `E5` | A regulator-approved design allowed camera classification to veto radar-only braking above 25 km/h. |
| `E6` | A cellular outage defeated the remote-operator safeguard despite two earlier outages near the site. |
| `E7` | Reconstruction shows both calibration and road layout materially changed the safe-stop rate. |

The binary charge is deliberately narrower than the causal story. A not-guilty
verdict does not mean nothing went wrong, and a guilty verdict does not mean
Aster Vale was the only contributor.

## The agents

The actor declarations are intentionally explicit in
[`run.py`](run.py)-there is no factory hiding the ProtoLink composition.

### Tribunal actors

| Agent | Age | Gender | Character and incentive |
| --- | ---: | --- | --- |
| Judge Imani Quill | 58 | Woman | Neutral tribunal chair; separates causal contribution from legal guilt |
| Amara Bell | 41 | Woman | Lawyer for Lina's family; resists complexity being used to dissolve accountability |
| Rowan Hale | 47 | Man | Aster Vale safety executive; argues that external failures created an unforeseeable combination |
| Dr. Nia Sol | 36 | Woman | Perception engineer; precise about calibration and the release pipeline |
| Elias Trent | 56 | Man | Safety regulator; candid but institutionally defensive |
| Dana Pierce | 50 | woman | Insurance claims director with an explicit financial interest |
| Dr. Amina Kade | 44 | Woman | Independent accident investigator who reconstructs interacting causes |

### Jury

| Juror | Age | Gender | Human perspective |
| --- | ---: | --- | --- |
| Evelyn Brooks | 62 | Woman | Former collision detective |
| Malik Thompson | 43 | Man | Civil-rights lawyer |
| Dr. Anika Rao | 38 | Woman | Human-factors psychologist |
| Ruben Park | 35 | Man | Site-reliability engineer |
| Sofia Bell | 46 | Woman | Investigative journalist and foreperson |
| Casey Morgan *(solo only)* | 40 | woman | Civic generalist |

These prompts describe people, not seeded numbers. They do not say “you begin
at 61/100” and they do not expose routing enums such as `reinforce_ally`.
Reference-only fixture coefficients remain outside every human-facing prompt.
Age and gender are fictional prompt metadata, not numerical priors. Hold them
fixed across provider comparisons, or deliberately rotate the assignments, so
demographic changes are not mistaken for model effects.

## Agent-authored communication

The world engine schedules bounded turns and enforces topology. It does not
choose what a juror should say or whom a mesh juror should approach.

On a deliberation turn, a juror returns an observable public action:

```json
{
  "move": "ask_question",
  "target_id": "juror_ruben",
  "message": "Does the shared CI token make the company more accountable, or only make attribution harder?",
  "evidence_ids": ["E3"],
  "public_intent": "Clarify whether release automation changes organizational control."
}
```

The application validates the target against the current topology, then the
speaker sends the message directly to the selected agent through ProtoLink.
The receiver returns an updated public register, categorical vote, concise
reason, and public reply.

Peer messages never automatically expose another juror's private probability,
confidence, or vote. An agent reveals only what it chooses to put in its public
message.

## Four decision conditions

### `solo`

One civic generalist receives the public record and decides without peers. This
is an intuitive product baseline, not a clean communication treatment: it also
changes panel size, persona composition, and inference budget.

### `independent`

The same five jurors hear the same public tribunal record and vote without peer
messages. This captures specialization and diversity without deliberation.

### `star`

Jurors send public messages through foreperson Sofia Bell. The foreperson is an
information hub and possible bottleneck.

### `mesh`

Every juror receives a turn with all other jurors as permitted targets. The
agent authors the recipient, move, message, and public intent.

The primary communication comparison is `independent` versus `star` or `mesh`
when their saved control fingerprints and public-record hashes match.

## What the default replay shows

The offline seed-7 fixture is designed to make the communication treatment
visible in one quick run:

| Condition | Peer messages | Verdict | Tally | Mean guilt register |
| --- | ---: | --- | ---: | ---: |
| `solo` | 0 | Guilty | 1–0 | 78.59 |
| `independent` | 0 | Not guilty | 2–3 | 77.56 |
| `star` | 5 | Not guilty | 2–3 | 80.21 |
| `mesh` | 5 | Guilty | 3–2 | 80.54 |

The independent and mesh panels receive the same public record. In mesh,
foreperson Sofia Bell chooses to challenge human-factors psychologist Dr. Anika
Rao with the interaction between the unvalidated C-91 calibration and the
crash-scene map. Anika's public guilt register moves from 77.90 to 81.41 and her
categorical vote changes from not guilty to guilty. Later messages strengthen
that position, but the first direct exchange is the majority-changing event in
the observable ledger.

The star topology also raises the mean guilt register, but it concentrates
messages at the foreperson and does not change the 2–3 verdict. The demo's point
is therefore not “more messages are better.” Who can address whom changes which
assumptions are exposed.

These are illustrative deterministic-fixture results, not evidence that mesh
communication generally improves accuracy. Live-model comparisons need
repeated paired runs and message ablations.

## Quick start

Run from the repository root:

```bash
python examples/ai_courtroom/run.py
```

The default command uses the deterministic `reference` provider and runs all
four conditions without network access or credentials.

Run one condition:

```bash
python examples/ai_courtroom/run.py \
  --provider reference \
  --condition mesh \
  --seed 17
```

The exact output location is printed at the end. To choose it:

```bash
python examples/ai_courtroom/run.py \
  --condition all \
  --seed 17 \
  --output-dir examples/ai_courtroom/output/c-91-incident-seed-17
```

When an output directory is reused, only the example's known generated files
are replaced. `traces.jsonl` is not allowed to accumulate stale runs beside a
new result.

## Watching a run

The runner reports work as it happens so a live model does not look stalled:

- the offline `reference` provider uses compact phase and step updates;
- live providers show each A2A exchange and its elapsed time by default;
- `-v` or `--verbose` forces detailed message, acceptance, and repair updates;
- `-q` or `--quiet` suppresses application progress at the default agent log
  level, only run headers and final condition summaries remain;
- `--agent-verbosity {0,1,2}` independently controls ProtoLink's own
  per-agent logs and defaults to `0`.

For example:

```bash
python examples/ai_courtroom/run.py \
  --condition mesh \
  --verbose \
  --agent-verbosity 1
```

Application progress and agent logs are separate on purpose. Start with the
default display or `--verbose`; raise `--agent-verbosity` only when diagnosing
the underlying agent runtime. Repair diagnostics are ordinary progress, so
they remain visible unless `--quiet` is selected.

## The replay-first report

The report opens with communication, not a wall of benchmark metrics:

- the pre- versus post-deliberation verdict;
- a playable A2A event replay;
- the active sender and receiver;
- the natural question, challenge, clarification, or concession;
- the receiver's public reply;
- synchronized before/after guilt registers and categorical votes;
- evidence citations and ProtoLink task metadata;
- observed after-message shifts using explicitly non-causal language.

The full event ledger remains available as a static, accessible fallback.

The report does not expose chain-of-thought. A public reason is an application
artifact that may be incomplete or post-hoc.

## Outputs

Each condition writes:

| File | Purpose |
| --- | --- |
| `result.json` | Full configuration, public record, agent models, decision histories, actions, events, metrics, and verdict |
| `summary.json` | Compact outcome and comparison data |
| `transcript.md` | Escaped public transcript |
| `report.html` | Standalone interactive replay and analysis |
| `traces.jsonl` | ProtoLink task, inference, and A2A telemetry |

An all-condition run also writes `index.html`, which presents the
solo → independent → star → mesh ladder.

Saved metadata includes:

- provider and exact resolved model for every agent;
- seed, temperature, evidence order, rounds, and both retry limits;
- public-record hash;
- baseline and pre-deliberation snapshot hashes;
- a comparison control fingerprint;
- message, retry, latency, estimated-token, grounding, and routing information.

## Live models

Install optional clients:

```bash
python -m pip install -e '.[llms]'
```

Example:

```bash
export OPENAI_API_KEY="..."

python examples/ai_courtroom/run.py \
  --provider openai \
  --model "your-model-id" \
  --temperature 0 \
  --condition mesh \
  --seed 17
```

Supported backends:

- `openai`
- `anthropic`
- `gemini`
- `ollama`
- `openai-compatible`

Use `--base-url` for a local or compatible server.

Running `--condition all` with a live provider requires the explicit
`--allow-multi-condition-live` acknowledgement because it multiplies API use.

### Ollama

Start with one condition and name the locally installed model explicitly:

```bash
python examples/ai_courtroom/run.py \
  --provider ollama \
  --model "your-ollama-model" \
  --base-url "http://localhost:11434" \
  --condition mesh \
  --action-parse-attempts 5 \
  --max-attempts 5 \
  --verbose
```

If every actor uses the same Ollama backend, the juror-specific provider flags
are unnecessary. Use `--juror-provider ollama`, `--juror-model`, and
`--juror-base-url` only when the jurors intentionally use a different model or
endpoint.

Live responses cross two intentionally separate validation boundaries:

1. `--action-parse-attempts` controls how many times the ProtoLink inference
   loop may ask the model to correct its outer action envelope.
2. `--max-attempts` controls how many bounded application-contract attempts the
   tribunal permits for each A2A message after it receives final content.

Both default to `3`, accept `1..5`, and provide targeted validation feedback
before another attempt. They are separate because a valid ProtoLink
`FinalAction` can still contain malformed courtroom JSON. Increasing either
limit can help a smaller local model recover, but it also increases run time.
Accepted application repairs and failed attempts remain visible in progress
output and saved event metadata; lower-level action-parser diagnostics are
visible through `--agent-verbosity`.

Provider/network backoff is a third, lower layer and is not controlled by
either flag. Retry budgets can multiply, so increase them deliberately rather
than setting every limit to its maximum.

Strict parsing and model self-correction remain the primary path. The outer
parser adds two narrow normalizations for the response shapes exposed here: it
can serialize an object/list placed inside `FinalAction.content`, and it can
treat a direct application object as final content only when no ProtoLink
action-envelope fields are present. It does not guess missing votes, evidence,
targets, or arguments.

The application has one equally narrow last-resort fallback for the earlier
“valid prose, no application JSON” failure: after the final structured attempt,
a nonempty lawyer, witness, or judge public statement may be kept as its
`statement`, with only exact admitted `E1`–`E7` references extracted. The event
is marked with a recovery warning. Juror assessments, ballots, categorical
verdict fields, and deliberation targets never use this prose fallback because
recovering them would require inventing decision data.

An all-condition live run repeats the full hearing for each condition and may
take substantially longer:

```bash
python examples/ai_courtroom/run.py \
  --provider ollama \
  --model "your-ollama-model" \
  --base-url "http://localhost:11434" \
  --condition all \
  --allow-multi-condition-live \
  --verbose
```

## Controlled juror-only model comparison

An end-to-end provider switch changes the lawyers, witnesses, public record, and
jury. That is visually interesting but scientifically confounded.

For a cleaner comparison, keep tribunal actors deterministic and change only
the jurors:

```bash
python examples/ai_courtroom/run.py \
  --provider reference \
  --juror-provider anthropic \
  --juror-model "your-model-id" \
  --condition mesh \
  --temperature 0 \
  --seed 17
```

For publishable comparisons:

1. Freeze prompts, persona demographics, case, evidence order, topology, round
   count, and temperature, or preregister a balanced rotation of demographic
   assignments.
2. Pair runs by seed.
3. Verify record hashes and control fingerprints.
4. Repeat every cell.
5. Include schema failures, warnings, and routing failures.
6. Report outcome, calibration, grounding, volatility, latency, and cost
   separately.
7. Describe the result as a case study, not a general intelligence leaderboard.

Provider temperature zero is not a determinism guarantee.

## Compare saved summaries

```bash
python examples/ai_courtroom/compare.py \
  path/to/solo/summary.json \
  path/to/independent/summary.json \
  path/to/star/summary.json \
  path/to/mesh/summary.json \
  --output comparison.md
```

The comparison treats solo polarization and consensus as `N/A`.

## Interpreting opinion and influence

`guilt_probability` is an application-owned public register. It is not a probe
of hidden model belief.

The categorical `guilty` or `not_guilty` vote is authored by the juror under the
fictional tribunal burden. The application does not silently derive criminal
guilt from a 50% threshold.

The default mesh replay contains this immediate change:

```text
Sofia Bell → Dr. Anika Rao
77.90 not guilty → 81.41 guilty
Observed after-message shift: +3.51
```

It is not automatically proof that Sofia caused the full change. Causal
language requires a matched message ablation across repeated paired runs.

## Tests

The repository's default test discovery targets the root `tests/` directory, so
run this example's offline tests explicitly:

```bash
pytest -q examples/ai_courtroom/tests
```

## Directory map

```text
examples/ai_courtroom/
├── run.py
├── compare.py
├── README.md
├── ARTICLE.md
├── courtroom/
│   ├── case_data.py
│   ├── providers.py
│   ├── reference_llm.py
│   ├── schemas.py
│   ├── simulation.py
│   └── reporting.py
├── tests/
│   ├── conftest.py
│   └── test_courtroom.py
└── output/
    └── .gitignore
```

ProtoLink is the communication substrate. The showcase question is deliberately
open: communication can correct an error, amplify one, expose a hidden
assumption, or merely make a group more confident. The replay lets you see
which happened.
