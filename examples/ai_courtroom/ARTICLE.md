# Can Communication Make AI Agents Smarter Than Independent Voting?

## An observable AI Liability Tribunal built with ProtoLink

<!--
FIGURE 1 SUGGESTION — Article hero
Placement: below the subtitle.
Format: 2000×1125 editorial illustration with generous negative space.
Prompt/composition: a fictional autonomous vehicle stopped in a rain-lit lane;
above it, a clean constellation of seven tribunal agents and five jurors linked
by directional message arcs. One juror’s verdict marker visibly changes from
“not guilty” to “guilty” along a replay timeline. Serious investigative-tech
tone, not sci-fi spectacle; no real brands, injury, gavels, or humanoid robots.
Palette: near-black navy, paper ivory, amber evidence markers, cyan A2A links.
Caption: “The courtroom is the setting. Communication is the experiment.”
Alt text: “An AI liability case connected to a replayable network of tribunal
agents and jurors whose public verdicts change after direct messages.”
-->

Most multi-agent demos show the answer, but hide the interesting part.

A coordinator calls several models, collects their responses, and produces a
summary. The result may be useful, yet it is hard to tell whether the agents
actually influenced one another, who changed their mind, or whether
“multi-agent” meant little more than running several prompts in parallel.

I wanted to make communication the experiment:

> If the same AI jurors hear the same evidence, does allowing them to talk
> produce a different decision than asking them to vote independently?

The result is **The Ghost in Lane Four**, a fictional AI Liability Tribunal
built on ProtoLink. Lawyers, technical witnesses, a regulator, an insurer, an
investigator, and jurors are autonomous, addressable agents. The jurors have
recognizable professional backgrounds. They can ask one another questions,
challenge claims, seek clarification, concede a point, and choose whom to
address.

The interface then replays those exchanges alongside the jurors’ changing
public decision registers. Instead of merely saying that a panel deliberated,
the demo lets you watch it happen.

In the deterministic seed-7 replay, the five jurors vote **2–3 not guilty**
when isolated from one another and **3–2 guilty** when direct mesh
communication is enabled. One observable challenge precedes the
majority-changing vote flip. That contrast is an intentionally designed
fixture—not evidence that mesh is generally superior—but it gives the A2A
system something concrete and inspectable to explain.

The courtroom is the setting. The real subject is what becomes possible when
agent-to-agent communication is a first-class, observable part of an
application.

> Every person, organization, rule, and event in this example is fictional.
> This is a software experiment, not legal advice or a validated model of any
> judicial process.

---

## The case: an autonomous vehicle, a fatal collision, and no single clean cause

At 21:47 on a rainy evening, an Aster Vale robotaxi struck and killed cyclist
Lina Ortega inside a temporary crossing. The vehicle began emergency braking
only 0.35 seconds before impact. Thirty-six hours earlier, it had received the
company’s Orchid 4.8 software release.

The fictional charge is:

> **Is Aster Vale Mobility guilty of criminally negligent deployment of an
> autonomous vehicle system that caused Lina Ortega’s death?**

The admitted evidence does not point neatly in one direction:

- The camera system merged Lina, her bicycle, and an illuminated lane-arrow
  board into one static object. Radar detected motion, but braking was
  suppressed.
- A perception engineer had recorded late braking in 3 of 20 simulations and
  wrote “block release.” A later calibration passed 20 of 20 reruns.
- The crashed vehicle ran calibration C-91, while the signed safety report
  validated C-90. A deployment bot shared the engineer’s signing credential.
- A road contractor moved the arrow board, failed to update the digital map,
  and removed roughly 1.1 seconds of useful observation.
- A conditionally approved design allowed camera classification to veto
  radar-only braking above 25 km/h.
- A cellular outage defeated the remote-operator safeguard. Aster Vale had
  recorded two earlier outages near the site.
- Independent reconstruction found that both the calibration and the road
  layout materially changed the safe-stop rate.

This is an interacting-failures problem. The contractor, network, regulator,
release process, perception system, and emergency-braking policy all matter.
But the jury decides a narrower question: whether Aster Vale is guilty of the
charged deployment decision.

That distinction creates useful disagreement. A juror can believe the company
made serious mistakes while still voting not guilty under the stated burden. A
juror can also believe other actors contributed while finding the company
guilty.

The evaluator stores a hidden synthetic truth: in the fixture, the release
committee saw an integrity warning identifying the C-91 mismatch and knowingly
waived it to meet a launch date. No tribunal agent receives that fact. It
exists only so the experiment can distinguish agreement from correctness
against a known fictional answer.

<!--
FIGURE 2 SUGGESTION — Evidence is a system, not a smoking gun
Placement: after the case section.
Prefer a designed diagram over generated art. Center node: “Fatal collision”.
Surrounding nodes: perception merge (E1), blocked simulation/retest (E2),
C-90/C-91 provenance gap (E3), moved arrow board (E4), radar veto policy (E5),
remote-operator outage (E6), interaction reconstruction (E7). Use solid arrows
only for relationships stated in case_data.py; use dashed lines for disputed
attribution. Add a narrow bracket on the right: “Causation is distributed;
the charge is organizational deployment.” Do not reveal the hidden synthetic
truth in the graphic. Source all wording from case_data.py.
Alt text: “Seven admitted exhibits converge on a fatal collision through
interacting software, deployment, road, regulatory, and network failures.”
-->

---

## Give agents human roles, not benchmark labels

Early versions described jurors as abstractions such as “systems thinker” or
“probabilistic integrator.” Those are defensible experimental categories, but
they make the project feel like a benchmark configuration file.

The current jury is immediately legible:

- **Evelyn Brooks**, a former collision detective, reconstructs physical
  sequences and distrusts polished narratives.
- **Malik Thompson**, a civil-rights lawyer, watches the burden of proof,
  institutional power, and scapegoating.
- **Dr. Anika Rao**, a human-factors psychologist, notices automation bias,
  hindsight bias, and hidden assumptions.
- **Ruben Park**, a site-reliability engineer, thinks in deployment controls,
  defence in depth, and incident ownership.
- **Sofia Bell**, an investigative journalist and foreperson, connects
  documents, incentives, and timelines while watching for stories that outrun
  the evidence.

The solo condition uses Casey Morgan, a civic generalist.

The other participants are equally concrete: Judge Imani Quill; Amara Bell,
lawyer for Lina’s family; Rowan Hale, Aster Vale’s safety executive; perception
engineer Dr. Nia Sol; regulator Elias Trent; insurance claims director Dana
Pierce; and independent investigator Dr. Amina Kade.

Most importantly, the juror prompts do **not** say things such as “you begin
61/100 convinced” or “your communication strategy is `reinforce_ally`.” They
describe a role, professional habits, personality, and decision rule in natural
language. The application asks the agent to produce its initial position.

Reference-only coefficients make the offline fixture reproducible, but they
remain outside the human-facing prompts. A live model receives the character,
case, admitted record, and output contract—not a prewritten opinion.

---

## The agents are explicit, and the communication is direct

The example intentionally keeps construction simple. Every participant is
declared as a normal ProtoLink `Agent` in the script. Here is one declaration,
abridged only to omit secondary card metadata, telemetry, and logging options:

```python
software_engineer_agent = Agent(
    card=AgentCard(
        name="software_engineer",
        description="Perception engineer who filed the pre-release warning.",
        url=f"runtime://ai-liability/{namespace}/software-engineer",
    ),
    transport="runtime",
    llm=model_for_role(
        args.provider,
        role="software_engineer",
        seed=args.seed,
        model=args.model,
        base_url=args.base_url,
        temperature=args.temperature,
    ),
    system_prompt=ROLE_PROMPTS["software_engineer"],
)
```

There is no elaborate factory or hidden agent hierarchy. The composition is
visible in one place.

The world engine acts as a procedural referee. It schedules orientation,
openings, direct and cross-examinations, closings, deliberation, frozen
ballots, and judgment. It enforces valid evidence identifiers and the allowed
communication topology. It does not write arguments, choose opinions, or
select a mesh recipient on an agent’s behalf.

Every exchange crosses a ProtoLink task boundary. A lawyer addresses a witness,
a juror receives a public-record update, or one juror calls another agent
directly. The local runtime keeps the default demo easy to run, while preserving
the same addressable A2A surface that can be moved to another transport.

This division matters:

- the engine controls **procedure** so conditions remain comparable;
- agents control **content and decisions**;
- ProtoLink carries each observable interaction between them.

Autonomy does not require an unstructured free-for-all. It requires being clear
about which decisions belong to the environment and which belong to the
agents.

<!--
FIGURE 3 SUGGESTION — What ProtoLink carries
Placement: after this architecture section.
Use a sequence diagram, not generative imagery. Lanes: world engine, sender
Agent, ProtoLink task/runtime, receiver Agent, event ledger/report. Show:
(1) engine schedules a turn, (2) sender creates an addressed task,
(3) receiver produces a public application JSON response,
(4) validator accepts or returns bounded repair feedback,
(5) event plus before/after public state is saved,
(6) replay reads the saved ledger. Distinguish “procedure” (gray), “agent
authorship” (amber), and “transport/telemetry” (cyan). Explicitly label that
private chain-of-thought is neither requested nor stored.
Alt text: “A scheduled turn becomes a direct ProtoLink task, a validated public
response, and a replayable event without exposing private reasoning.”
-->

---

## Let the juror author the interaction

An orchestrator that always says “Juror A, persuade Juror B” may generate an
interesting dialogue, but the orchestrator is still the real social actor.

In the mesh condition, the juror instead returns a public communication action:

```json
{
  "action": "ask_question",
  "target_id": "juror_ruben",
  "message": "Does the shared deployment token make the company more accountable, or only make attribution harder?",
  "evidence_ids": ["E3"],
  "public_intent": "Clarify whether release automation changes organizational control."
}
```

The available actions are human: ask a question, challenge a claim, share
evidence, seek clarification, attempt persuasion, or concede a point. The
agent chooses the target, wording, cited evidence, and public intent. The
application validates that the target is permitted by the topology, then sends
the message directly through ProtoLink.

The receiver replies with observable state:

- a public guilt-probability register;
- a categorical `guilty` or `not_guilty` vote;
- confidence;
- cited evidence;
- a concise public reason;
- a public reply;
- explicitly stated influences.

A peer message does not silently inject the sender’s private score, vote, or
confidence. The receiver sees only what the sender chose to say publicly. This
keeps the communication itself—not hidden simulator metadata—as the mechanism
of influence.

---

## Four conditions, one communication ladder

The demo runs four conditions.

### 1. Solo

One civic generalist hears the public tribunal record and decides without
peers. This is the most intuitive product baseline, but not a clean scientific
control: panel size, persona mix, and total inference budget all change.

### 2. Independent

The same five specialist jurors hear the same public record and cast frozen
ballots without speaking to one another. This isolates diversity without
deliberation.

### 3. Star

Juror communication goes through foreperson Sofia Bell. This is the familiar
hub-and-spoke pattern: efficient, but vulnerable to compression and
gatekeeping.

### 4. Mesh

Each juror receives a turn and may address any other juror directly. The agent
authors the target and message. This creates more paths for correction,
persuasion, confusion, and repetition.

The meaningful communication comparison is independent versus star or mesh,
provided the saved public-record hashes and control fingerprints match. Solo is
useful context, not evidence about the isolated effect of communication.

<!--
FIGURE 4 SUGGESTION — The communication ladder
Placement: after the four conditions.
Create one horizontal four-panel topology diagram using the same juror icons in
every applicable panel: Solo (one isolated generalist), Independent (five
unconnected specialist jurors), Star (five jurors with only foreperson hub
paths), Mesh (five jurors with permitted direct paths). Use arrows to represent
possible communication, not messages that necessarily occurred. Underline
Independent→Star/Mesh as the controlled comparison; mark Solo “descriptive
baseline—panel size also changes”.
Alt text: “Four conditions progress from one isolated juror to independent
specialists, a foreperson hub, and direct mesh communication.”
-->

---

## A probability is not a verdict

One design choice turned out to be especially important.

The application records a public `guilt_probability`, but it never converts
that number into a criminal verdict using an arbitrary 50% threshold. Each
juror separately authors `guilty` or `not_guilty` under the fictional
instruction to vote guilty only when firmly convinced that every element is
satisfied.

That means a juror can report substantial probability that the company is
guilty while still voting not guilty because one element remains unresolved.
This is not an inconsistency to “fix.” It is useful decision information.

The probability is also not a probe of hidden chain-of-thought or a calibrated
measurement of an internal model belief. It is an application-owned public
register: something the agent states so its trajectory can be observed.

At the end of deliberation, the register and categorical vote are frozen. A
private ballot task confirms the saved state; it cannot quietly create one
last unobserved revision.

---

## The replay is the product

A final verdict tells us almost nothing about multi-agent communication.

The report therefore opens with a replay. For every peer exchange it shows:

- who initiated the interaction and whom they selected;
- the authored question, challenge, clarification, persuasion attempt, or
  concession;
- the evidence cited;
- the receiver’s public reply;
- every juror’s before-and-after register and vote;
- the corresponding ProtoLink task metadata.

A timeline and scrubber make the deliberation playable. An influence graph
aggregates who preceded the largest observed changes. Juror trajectories reveal
whether a position moved gradually, snapped after one exchange, or became more
confident without changing its vote.

This creates the moment a static benchmark lacks:

```text
Before    Dr. Anika Rao   77.90   not guilty
Message   Sofia connects the C-91 mismatch in E3 with the interaction tests in E7
After     Dr. Anika Rao   81.41   guilty
Change    +3.51 after the message
```

The wording in the report is intentionally careful. A shift immediately after
a message is an **observed after-message change**, not proof that the sender
caused the entire movement. Establishing causality would require matched runs
with that message removed or replaced.

Observability here means public outputs, protocol events, and state changes. It
does not mean exposing private chain-of-thought.

<!--
FIGURE 5 SUGGESTION — The vote-changing moment
Placement: after “The replay is the product”.
Best source: a cropped screenshot from mesh/report.html at the Sofia→Anika
event, rather than an invented mock-up. If redrawing, derive exact values from
mesh/result.json: locate the peer_message event with sender=juror_sofia and
receiver=juror_anika, then use belief_before, belief_after, belief_delta,
authored_action.message, response.public_reply, and evidence_ids. Pair a small
five-line trajectory chart with the directed influence edge. Label the change
“observed after message”, never “caused by”.
Caption: “A direct challenge preceded the panel’s only deliberation vote flip.”
Alt text: “Replay frame showing Sofia’s message to Anika, Anika’s public reply,
and her register and categorical vote before and after the exchange.”
-->

---

## What happened in the deterministic seed-7 run?

The repository includes a deterministic offline reference provider so anyone
can exercise the protocol, reports, and comparisons without an API key.

For the default seed-7 fixture, the expected results are:

| Condition | Group verdict | Ballots (guilty–not guilty) | Mean final guilt probability | Deliberation vote flips |
| --- | --- | ---: | ---: | ---: |
| Solo | Guilty | 1–0 | 78.59 | 0 |
| Independent | Not guilty | 2–3 | 77.56 | 0 |
| Star | Not guilty | 2–3 | 80.21 | 0 |
| Mesh | Guilty | 3–2 | 80.54 | 1 |

Three observations are more interesting than a winner:

First, the independent panel and the mesh panel heard the same public case yet
reached different categorical outcomes. Dr. Anika Rao was the one mesh juror
whose frozen categorical vote changed during deliberation.

The mesh delivered five agent-authored routes: Sofia to Anika, Evelyn to Malik,
Ruben to Anika, Malik to Anika, and Anika to Sofia. Star also delivered five
peer messages. Both conditions completed with zero routing fallbacks and zero
schema repairs in this run.

Second, the star panel’s mean guilt register increased, but its verdict did
not change. More numerical confidence is not the same as consensus, and neither
is automatically the same as a better decision.

Third, the independent panel averaged 77.56% guilt while returning only two
guilty ballots. That apparent tension is exactly why the categorical decision
must be recorded separately from the probability register.

The mesh verdict agrees with the fixture’s hidden synthetic truth. It would be
tempting to conclude that mesh communication made the agents smarter.

That would overstate the evidence.

The deterministic reference fixture was deliberately designed and tuned to
create an illustrative contrast: independent and star stop short of a guilty
majority, while mesh deliberation produces a visible vote change. It is a
golden path for testing the A2A protocol and replay UI, not an empirical finding
about AI juries or communication topologies.

The honest claim is narrower and still useful:

> Direct agent communication changed the outcome, and the system makes the
> path to that change inspectable.

No live-provider result is claimed in this article.

---

## How to compare GPT, Claude, Gemini, Qwen, or local models

Provider comparisons are interesting only if we decide what is being compared.

Switching every model end to end changes the lawyers, witnesses, public record,
jurors, and deliberation. That can make a compelling demo, but any outcome
difference has many possible causes.

A cleaner experiment keeps the tribunal actors on the deterministic reference
provider and changes only the juror backend:

```bash
python examples/ai_courtroom/run.py \
  --provider reference \
  --juror-provider anthropic \
  --juror-model "your-model-id" \
  --condition mesh \
  --temperature 0 \
  --seed 17
```

The same pattern works with the supported `openai`, `anthropic`, `gemini`,
`ollama`, and `openai-compatible` backends. An OpenAI-compatible endpoint can
be used for other hosted or local models.

A credible comparison should:

1. Freeze the case, prompts, topology, evidence order, round count, and output
   contracts.
2. Pair runs by seed and verify matching public-record hashes and control
   fingerprints.
3. Repeat each condition; temperature zero does not guarantee determinism.
4. Separate verdict accuracy from probability calibration, consensus, and
   stability.
5. Measure evidence grounding, invalid citations, schema retries, and routing
   failures.
6. Report latency, estimated tokens, and cost separately from decision quality.
7. Compare influence concentration: does one model over-rely on the
   foreperson, target only allies, or revise after substantive challenges?

The most revealing provider question may not be “which model gets the right
verdict?” It may be:

> Which models use communication to discover a missed consideration, and which
> use it mainly to amplify an existing position?

That requires repeated runs and message ablations. The included fixture makes
the experiment runnable; it does not answer the question in advance.

<!--
FIGURE 6 SUGGESTION — Provider experiment matrix
Placement: after the provider-comparison section, once real repeated runs exist.
Do not prefill fabricated winners. Rows: exact provider/model/version. Columns:
independent verdict accuracy, mesh verdict accuracy, message-ablation lift,
vote-flip rate, evidence-grounding rate, schema-repair rate, routing-fallback
rate, latency, estimated tokens, and measured cost. Show mean plus interval and
sample count for every cell. Put model/date/temperature/seed set in a footnote.
An adjacent scatter plot can compare grounding rate (x) with outcome change
after communication (y), encoding influence concentration by point size.
Caption: “Model quality and communication quality are different axes.”
-->

---

## What this showcase demonstrates about A2A systems

The project exposes several properties that disappear inside a monolithic
orchestrator:

**Identity has operational meaning.** Each actor has an address, role, prompt,
model, and task history. A message is sent by one participant to another, not
appended anonymously to a shared scratchpad.

**Topology is an application choice.** The same agents can be isolated,
connected through a hub, or allowed to communicate directly without rewriting
their identities.

**Interaction is data.** Sender, receiver, action, evidence, response, and
before/after public state become replayable artifacts.

**Disagreement can survive.** The system does not require an orchestrator to
collapse every view into a synthetic consensus.

**Models can be changed independently.** Tribunal actors and jurors can use
different providers while sharing one protocol.

**Communication can fail visibly.** Invalid targets, malformed actions,
unsupported evidence references, retries, and fallback routing are measured
rather than silently hidden.

This is the indirect value proposition for ProtoLink. The framework is not the
headline painted over the demo. It is the engine that makes an inspectable
society of agents practical.

---

## The less glamorous lesson: structured output is part of the protocol

Live models do not always return the shape a long-running agent experiment
expects. A model may produce a sound courtroom statement wrapped in the wrong
outer object, place a JSON object where text was required, add prose around the
payload, or omit one application field. Local models can make these variations
especially visible.

Treating every failure as the same “JSON parsing error” makes recovery brittle.
The showcase instead keeps two boundaries explicit:

1. **ProtoLink action validation** determines whether the model is finishing,
   calling a tool, or delegating to an agent. The
   `--action-parse-attempts` limit bounds corrective passes at this outer
   protocol layer.
2. **Tribunal application validation** checks the final content against the
   statement, decision, deliberation-action, or judgment contract. The
   `--max-attempts` limit bounds these per-message application attempts.

A valid outer `FinalAction` can still contain an invalid tribunal response, so
collapsing the two counters would hide where interoperability failed. In both
layers, recovery is bounded and diagnostic. The system first attempts strict
parsing and validation, then gives the model specific field-level feedback for
self-correction.

For the response shapes exposed by this showcase, the outer parser adds two
narrow deterministic normalizations. If a `FinalAction` contains an object or
list instead of a text content field, it serializes that value to JSON text. If
a model returns the application object directly, the parser can wrap it as
final content only when the object contains no ProtoLink action-envelope
fields. These repairs preserve what the model actually authored. They never
invent a vote, evidence citation, message target, tool argument, or legal
conclusion.

The application layer has one scoped last-resort recovery for public
statements. If the final structured attempt from a lawyer, witness, or judge is
nonempty prose rather than application JSON, the tribunal can preserve that
prose as the `statement`, extract only exact admitted `E1`–`E7` references, and
record a recovery warning in the event ledger. The fallback is deliberately
unavailable to juror assessments, ballots, categorical verdict fields, and
deliberation routing; recovering those from prose would require guessing
decision data.

Both controls default to three attempts and accept values from one to five.
Higher limits can make a small local model more resilient, but they also add
latency and inference cost. The detailed runner display shows A2A calls,
accepted application responses, and repair attempts; lower-level inference
diagnostics can be enabled separately with `--agent-verbosity`.

Provider and network backoff form a third layer below both controls. The
budgets can multiply, which is why the defaults are modest and why simply
turning every retry limit to its maximum is a poor substitute for deterministic
normalization.

This may sound like infrastructure housekeeping, but it is part of the research
record. A provider that reaches a verdict only after frequent schema repair is
behaving differently from one that follows the protocol on its first attempt.
Repair rate therefore belongs beside grounding, outcome, latency, and cost—not
hidden in a catch-all retry loop.

---

## Limitations and threats to validity

This is a research prototype, not a benchmark result.

- The case, burden, prompts, fixture coefficients, and synthetic truth are
  authored. Different choices may reverse the result.
- The solo baseline changes more than communication and should not be used as a
  causal treatment.
- One seed and one case cannot establish that a topology or provider is
  generally better.
- A public reason may be incomplete, simplified, or post-hoc.
- An after-message shift is temporal association, not causal attribution.
- More agreement can mean correction, conformity, anchoring, or shared error.
- Model personas are prompt-induced behaviors, not durable human identities.
- Legal guilt is an intentionally simplified fictional decision. The system
  should not be used to evaluate real people, products, or cases.
- Token counts and costs vary by provider, and live services can change over
  time.

The next serious experiment would run a preregistered matrix across cases,
seeds, providers, and topologies, then ablate individual messages. It would
publish both successes and reversals—including cases where communication makes
the group confidently wrong.

---

## Reproduce the showcase

From the repository root, run all four conditions with the offline reference
provider:

```bash
python examples/ai_courtroom/run.py
```

The default seed is 7. The command prints the generated comparison-page path.
To choose the destination explicitly:

```bash
python examples/ai_courtroom/run.py \
  --provider reference \
  --condition all \
  --seed 7 \
  --output-dir examples/ai_courtroom/output/ghost-lane-seed-7
```

Run a single mesh experiment:

```bash
python examples/ai_courtroom/run.py \
  --provider reference \
  --condition mesh \
  --seed 17
```

For a local Ollama model, start with one condition so the full experiment
matrix does not hide setup problems:

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

The reference provider prints compact phase progress. Live providers print
per-A2A timing by default; `--verbose` forces that detail, `--quiet` suppresses
application progress, and `--agent-verbosity {0,1,2}` independently controls
lower-level ProtoLink logs. With quiet mode and the default agent log level,
only headers and final summaries remain.

Compare previously saved summaries:

```bash
python examples/ai_courtroom/compare.py \
  path/to/solo/summary.json \
  path/to/independent/summary.json \
  path/to/star/summary.json \
  path/to/mesh/summary.json \
  --output comparison.md
```

Run the example’s offline tests:

```bash
pytest -q examples/ai_courtroom/tests
```

Each condition writes a full result, compact summary, public Markdown
transcript, standalone replay report, and ProtoLink JSONL traces.

---

## The verdict is not the ending

The memorable part of this demo is not that an AI jury said “guilty.”

It is seeing an investigative journalist connect two exhibits, watching a
human-factors psychologist revise her public position, seeing a
site-reliability engineer reinforce the technical argument, and tracing those
interactions through real A2A tasks instead of accepting a final orchestrator
summary.

Communication does not guarantee intelligence. It can reveal missing evidence,
correct a mistake, create a bottleneck, spread an unsupported claim, or turn
uncertainty into unjustified confidence.

That is precisely why it should be observable.

The question is no longer merely whether several agents can produce an answer.
It is whether we can understand what changes when they are allowed to talk.
