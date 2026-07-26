# Five AI Jurors, One Case, Two Verdicts

## Can communication make AI agents smarter than independent voting? An observable A2A experiment built with ProtoLink

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

In the deterministic seed-7 reference replay, five AI jurors heard the same
case and the same seven exhibits.

When they were not allowed to speak to one another, they voted **2–3 not
guilty**. When the same panel could communicate directly, they voted **3–2
guilty**.

The case did not change. The evidence did not change. The juror identities did
not change. What changed was who could talk to whom.

In the direct-communication run, one public challenge preceded the only
majority-changing vote flip. That does not prove the message caused the
revision, and it certainly does not prove that mesh communication is generally
better. But it creates something much more useful than a final answer: an
observable path to a different collective outcome.

That was the experiment I wanted to build:

> If the same AI jurors hear the same evidence, does allowing them to talk
> produce a different decision than asking them to vote independently?

Most multi-agent demos show the answer while hiding the interesting part.

A coordinator calls several models, collects their responses, and produces a
summary. The result may be useful, yet it is hard to tell whether the agents
actually influenced one another, who changed their mind, or whether
“multi-agent” meant little more than running several prompts in parallel.

The result is **The Ghost in Lane Four**, a fictional AI Liability Tribunal
built on ProtoLink. Lawyers, technical witnesses, a regulator, an insurer, an
investigator, and jurors are autonomous, addressable agents. The jurors have
recognizable professional backgrounds. They can ask one another questions,
challenge claims, seek clarification, concede a point, and choose whom to
address.

The interface then replays those exchanges alongside the jurors’ changing
public decision registers. Instead of merely saying that a panel deliberated,
the demo lets you watch it happen.

The courtroom is the setting. The real subject is what becomes possible when
agent-to-agent communication is a first-class, observable part of an
application.

> Every person, organization, rule, and event in this example is fictional.
> This is a software experiment, not legal advice or a validated model of any
> judicial process.

---

## The case: an autonomous vehicle, a fatal collision, and no single clean cause

At 21:47 on a rainy evening, an Aster Vale robotaxi struck and killed
31-year-old cyclist Lina Ortega inside a temporary crossing. The vehicle began
emergency braking only 0.35 seconds before impact. Thirty-six hours earlier, it
had received the company’s Orchid 4.8 software release.

The fictional charge is:

> **Is Aster Vale Mobility guilty of criminally negligent deployment of an
> autonomous vehicle system that caused Lina Ortega’s death?**

The case rests on seven admitted exhibits. None is a magic smoking gun:

| Exhibit | What the jury learns | Why it cuts both ways |
| --- | --- | --- |
| **E1 — Crash mechanism** | The camera merged Lina, her bicycle, and the illuminated arrow board into one static object. Radar detected motion, but emergency braking was suppressed until 0.35 seconds before impact. | It establishes a technical failure, but not who knowingly accepted the risk. |
| **E2 — Warning and retest** | Dr. Nia Sol saw late braking in 3 of 20 simulations and wrote “block release.” Calibration C-90 then passed 20 of 20 reruns. | The warning makes the danger foreseeable; the clean rerun supports the claim that it was resolved. |
| **E3 — Provenance gap** | The crashed vehicle ran C-91, while the signed safety report validated C-90. The deployment record bears Dr. Sol’s credential, while audit logs show the CI bot held the same deployment token. | The wrong calibration reopens the safety issue, but the credential and automation trail complicate individual attribution. |
| **E4 — Road contractor** | The contractor moved the arrow board 2.4 metres, failed to update the map, and removed about 1.1 seconds of useful observation. | It is a serious third-party contribution, but it does not automatically excuse weak deployment safeguards. |
| **E5 — Radar veto** | Above 25 km/h, the camera could veto radar-only braking. The rule reduced false emergency stops by 41% and received conditional approval. | It was an intentional, reviewed safety tradeoff; approval is not proof that deployment was reasonable in every condition. |
| **E6 — Failed fallback** | A cellular outage defeated the assumed two-second remote response. Aster Vale knew of two nearby outages; the regulator had only an aggregate report. | The outage was external, but the failure of a known fallback may have been foreseeable. |
| **E7 — Interaction test** | Safe stops were 19/20 for C-90 with the corrected map, 14/20 for C-90 with the crash map, 16/20 for C-91 with the corrected map, and 6/20 for C-91 with the crash map. | Both calibration and road state matter, and their combination is much worse than either factor alone. |

Lina’s family argues that this was a preventable organizational failure: Aster
Vale owned the release, had warning signs, relied on a fragile remote fallback,
and put an unvalidated calibration on the road.

Aster Vale argues that it was a rare compound accident: a moved road sign, an
incorrect map, a network outage, a conditionally approved braking policy, and
a safety concern that appeared to have passed its retest.

The defendant is **Aster Vale Mobility**, not Rowan Hale personally. Amara Bell
is counsel for Lina’s family. Rowan is Aster Vale’s vice president for product
safety and designated tribunal representative; he is the current defence-side
agent and argues for a not-guilty verdict, but he is not a defence lawyer. He
authors the company’s opening and closing, while witnesses author their own
testimony. An experiment specifically about legal advocacy should add a
separate defence-counsel agent rather than silently relabel Rowan.

The jury is not asked to identify one exclusive cause. It must decide whether
all four elements of the fictional charge are satisfied:

1. Aster Vale controlled the safety-critical release.
2. It knew or should have known that the release created a substantial risk.
3. It deployed without reasonable safeguards.
4. That deployment decision was a substantial cause of Lina Ortega’s death.

A juror can therefore believe the company made serious mistakes while still
voting not guilty under the stated burden. Another can accept that third
parties contributed and still find Aster Vale guilty.

Every tribunal agent receives only the public summary and admitted E1–E7
record. The hidden evaluator fixture is discussed later; it never enters an
agent prompt or message.

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

## Four conditions change one thing: who may communicate

Every run follows the same procedure:

```text
orientation → 2 openings → 8 witness examinations → 2 closings
            → optional peer deliberation → frozen ballots → judgment
```

Each public statement is delivered to every active juror. The juror then
updates an observable guilt register, categorical vote, confidence, evidence
citations, and short public reason. Only after the shared hearing does the
communication condition diverge.

| Condition | Decision-makers | Permitted peer communication | What it asks |
| --- | --- | --- | --- |
| **Solo** | Casey Morgan alone | None | What does one generalist decide? This is a descriptive product baseline, not a topology-only control. |
| **Independent** | The same five specialist jurors used below | None | What does a diverse panel decide when its members cannot influence one another? |
| **Star** | The five specialists, with Sofia Bell as foreperson | Per round, four jurors each address Sofia once; Sofia then chooses one juror to address | What changes when communication is concentrated through a hub? |
| **Mesh** | The same five specialists | Per round, every juror chooses any other juror and authors one direct message | What changes when communication is decentralized and recipients are agent-selected? |

Star is not an automatic broadcast. Sofia may receive four different
arguments, then choose one panelist and one issue to address. That makes her an
information hub and a possible bottleneck.

Mesh is not a group chat. Each juror gets an explicit turn, chooses an eligible
recipient, selects an action such as asking or challenging, cites public
evidence, and sends one addressed ProtoLink task. Only the recipient updates
from that peer message.

The clean communication comparison is **Independent versus Star or Mesh**:
same five jurors, same permitted evidence, and the same procedure, with
communication topology as the treatment. Solo changes panel size, persona mix,
and inference budget, so it is useful context rather than evidence about the
isolated effect of communication.

For a controlled result, the saved public-record hashes and control
fingerprints must also match. The deterministic reference fixture guarantees
that match; live-model hearings may vary and must be checked rather than
assumed identical.

<!--
FIGURE 3 SUGGESTION — The communication ladder
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

## Give agents human roles, not benchmark labels

Early versions described jurors as abstractions such as “systems thinker” or
“probabilistic integrator.” Those are defensible experimental categories, but
they make the project feel like a benchmark configuration file.

The current jury is immediately legible. Their professions are not decorative
backstories; they create different error-detection lenses:

- **Evelyn Brooks**, a 62-year-old woman and former collision detective,
  reconstructs physical sequences and distrusts polished narratives.
- **Malik Thompson**, a 43-year-old man and civil-rights lawyer, watches the
  burden of proof, institutional power, and scapegoating.
- **Dr. Anika Rao**, a 38-year-old woman and human-factors psychologist,
  notices automation bias, hindsight bias, and hidden assumptions.
- **Ruben Park**, a 35-year-old man and site-reliability engineer, thinks in
  deployment controls, defence in depth, and incident ownership.
- **Sofia Bell**, a 46-year-old woman, investigative journalist, and
  foreperson, connects documents, incentives, and timelines while watching for
  stories that outrun the evidence.

The solo condition uses Casey Morgan, a 40-year-old woman and civic generalist.

The other participants are equally concrete: Judge Imani Quill, a 58-year-old
woman; Amara Bell, a 41-year-old woman and lawyer for Lina’s family; Rowan Hale,
a 47-year-old man and Aster Vale safety executive; perception engineer Dr. Nia
Sol, a 36-year-old woman; regulator Elias Trent, a 56-year-old man; insurance
claims director Dana Pierce, a 50-year-old woman; and independent investigator
Dr. Amina Kade, a 44-year-old woman.

Most importantly, the juror prompts do **not** say things such as “you begin
61/100 convinced” or “your communication strategy is `reinforce_ally`.” They
describe a role, professional habits, personality, and decision rule in natural
language. The application asks the agent to produce its initial position.

Reference-only coefficients make the offline fixture reproducible, but they
remain outside the human-facing prompts. A live model receives the character,
case, admitted record, and output contract, not a prewritten opinion.

Age and gender are fictional prompt metadata, not priors or explanations for a
decision. Because models may reproduce demographic stereotypes, controlled
provider comparisons must hold these assignments fixed or rotate them through
a preregistered balanced design.

---

## The agents are explicit, and the communication is direct

The example intentionally keeps construction simple. Every participant is
declared as a normal ProtoLink `Agent` in [`run.py`](run.py). An agent needs
three ideas:

- an `AgentCard` that gives it an identity and address;
- an LLM backend, which may differ from the backend used by other agents;
- a system prompt describing its role, knowledge boundary, and behaviour.

Here is one real declaration, abridged only to omit secondary card metadata,
telemetry, and logging options:

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

`model_for_role(...)` is a small provider selector, not an agent factory. The
actual ProtoLink composition remains visible in one place: card, transport,
model, and prompt.

Once two agents exist, the core communication path is just as direct:

```python
task = Task.create_infer(prompt=prompt)
result = await sender.call_agent(receiver.card.url, task)
```

The full example attaches run metadata, tracing context, validation, and bounded
repair feedback around those two lines. But there is no hidden workflow graph
pretending to be a conversation. One addressed agent sends a ProtoLink task to
another addressed agent and receives a task result.

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

### The case is replaceable; the communication scaffold is reusable

*The Ghost in Lane Four* is one configuration of the example, not its limit.
The fastest extension is another binary guilty/not-guilty case using the same
cast shape, tribunal procedure, and seven-exhibit convention:

1. Copy `examples/ai_courtroom` into a new example directory.
2. Replace `CASE` in
   [`courtroom/case_data.py`](courtroom/case_data.py): title, question, charge,
   burden, elements, public summary, admitted evidence, and the private
   synthetic-truth fixture used for evaluation.
3. Rewrite `ACTOR_PROFILES`, `ROLE_PROMPTS`, and `JUROR_PROFILES` for the new
   cast and incentives.
4. Keep evidence identifiers in the `E1`, `E2`, … form, or update the prompt
   contracts and evidence-reference recovery to match a different convention.
5. Update the explicit `Agent` names, descriptions, and tags in
   [`run.py`](run.py). Keeping the existing internal actor IDs is the
   least-work route; changing the cast or its size also requires changing the
   procedure in `simulation.py`.
6. Run with a live provider. If the new example also needs a deterministic
   offline golden path, replace the case-specific behaviour in
   [`courtroom/reference_llm.py`](courtroom/reference_llm.py) and its expected
   results in [`tests/test_courtroom.py`](tests/test_courtroom.py).

The rest of the structure can remain: addressed agents, public-record delivery,
Solo/Independent/Star/Mesh topology, observable juror state, frozen ballots,
event ledger, comparison artifacts, and replay UI.

For a different domain—an incident review, scientific peer review, product-risk
council, policy committee, or negotiation—the same ProtoLink pattern still
applies, but the courtroom vocabulary must also change:

| What changes | Main module |
| --- | --- |
| Participants, models, and addresses | [`run.py`](run.py) |
| Procedure, turn order, and topology | [`courtroom/simulation.py`](courtroom/simulation.py) |
| Observable decisions and communication actions | [`courtroom/schemas.py`](courtroom/schemas.py) |
| Replay labels and domain-specific presentation | [`courtroom/reporting.py`](courtroom/reporting.py) |

This is not a generic one-file scenario loader today. It is a compact reference
architecture whose reusable idea is clear: autonomous roles, controlled
communication paths, explicit state changes, and replayable A2A tasks.

<!--
FIGURE 4 SUGGESTION — What ProtoLink carries
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
keeps the communication itself, not hidden simulator metadata, as the mechanism
of influence.

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

It also stores a hidden synthetic answer for evaluation. In that private
fixture, the release committee saw an integrity warning identifying the C-91
mismatch and knowingly waived it to meet a launch date. No tribunal agent
receives that fact. It exists only so the experiment can distinguish agreement
from correctness against a known fictional answer.

For the default seed-7 fixture, the expected results are:

| Condition | Group verdict | Ballots (guilty–not guilty) | Mean final guilt probability | A2A events | Deliberation vote flips |
| --- | --- | ---: | ---: | ---: | ---: |
| Solo | Guilty | 1–0 | 78.59 | 27 | 0 |
| Independent | Not guilty | 2–3 | 77.56 | 83 | 0 |
| Star | Not guilty | 2–3 | 80.21 | 93 | 0 |
| Mesh | Guilty | 3–2 | 80.54 | 93 | 1 |

With one deliberation round, running all four conditions produces **296
observable A2A events** before any application-level repair calls. Star and
Mesh each add five agent-authored planning events and five corresponding peer
messages to the independent-panel procedure.

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

I also ran the complete workflow against a local 8B Gemma model through Ollama.
That successful run is an encouraging integration stress test, but I do not
treat one local model’s verdict as a quality benchmark or publish it as evidence
that one topology is superior.

---

## Running the experiment locally with Ollama

One reason this example is useful is that it does not require a frontier hosted
model to exercise the full protocol. From the example directory, I ran the Star
condition with Ollama providing both the tribunal actors and the jurors:

```bash
cd examples/ai_courtroom

python run.py \
  --provider ollama \
  --base-url "http://localhost:11434" \
  --juror-provider ollama \
  --juror-base-url "http://localhost:11434" \
  --condition star
```

The juror flags are explicit even though they point at the same server. That
makes an important ProtoLink capability visible: actors and jurors are separate
agents, so their providers can be configured together or changed
independently.

For a reproducible published run, pin the exact installed Ollama tag rather
than relying on the adapter default:

```bash
python run.py \
  --provider ollama \
  --model "<exact-ollama-model-tag>" \
  --base-url "http://localhost:11434" \
  --juror-provider ollama \
  --juror-model "<exact-ollama-model-tag>" \
  --juror-base-url "http://localhost:11434" \
  --condition star \
  --verbose
```

To run the entire live matrix, the runner requires an explicit acknowledgement
because it creates many model calls:

```bash
python run.py \
  --provider ollama \
  --base-url "http://localhost:11434" \
  --juror-provider ollama \
  --juror-base-url "http://localhost:11434" \
  --condition all \
  --allow-multi-condition-live \
  --verbose
```

At the default single deliberation round, that matrix schedules 296 observable
A2A events. Schema-repair attempts can increase the actual number of model
generations. Completing the matrix on an 8B local model does not prove that its
legal conclusion is good; it demonstrates that the agent identities, direct
calls, delegation, response contracts, bounded repair, frozen ballots, traces,
and report generation can survive a long real workflow.

---

## How to compare GPT, Claude, Gemini, Qwen, or local models

Provider comparisons are interesting only if we decide what is being compared.

Switching every model end to end changes the lawyers, witnesses, public record,
jurors, and deliberation. That can make a compelling demo, but any outcome
difference has many possible causes.

A cleaner experiment keeps the tribunal actors on the deterministic reference
provider and changes only the juror backend. From the repository root:

```bash
python examples/ai_courtroom/run.py \
  --provider reference \
  --juror-provider ollama \
  --juror-model "<exact-ollama-model-tag>" \
  --juror-base-url "http://localhost:11434" \
  --condition mesh \
  --temperature 0 \
  --seed 17
```

The same pattern works with the supported `openai`, `anthropic`, `gemini`,
`ollama`, and `openai-compatible` backends. An OpenAI-compatible endpoint can
be used for other hosted or local models.

### A sharper benchmark: which model can move a fixed jury?

A particularly interesting extension is to change only the defence-side model.
Keep the case, evidence, judge, Lina’s family counsel, witnesses, juror models,
role prompts, evidence order, topology, and inference settings fixed. Then ask:

> Which model moves an otherwise fixed jury toward not guilty using only
> admitted evidence?

The current example can already test Rowan Hale as the defendant company’s
representative. He authors Aster Vale’s opening and closing, although he is not
a defence lawyer and the present examination turns do not ask him to author
individual questions. A cleaner legal-advocacy benchmark would add a dedicated
`defense_counsel_agent`, keep Rowan as the company representative or witness,
and assign only the counsel agent’s `llm` to the candidate model. ProtoLink
makes that separation natural because the model belongs to the individual
`Agent`, not to a global workflow.

I would start with the **Independent** condition so juror-to-juror persuasion
cannot obscure the treatment, then repeat the experiment under Star and Mesh
to see whether peer communication amplifies or resists the advocate.

For each exact Claude, Gemini, GPT, Qwen, or local-model version, a credible
closing-statement benchmark would:

1. Freeze one public record and make the candidate defence closing the only
   changing message.
2. Generate several saved closings per model, then show each closing to fresh
   copies of the same fixed jury. Ten closing samples crossed with ten jury
   replicates gives 100 panels per model without pretending one lucky message
   represents the model.
3. Compare against a common reference defence closing and a no-closing
   ablation, not just against another model’s changing prose.
4. Report the final not-guilty verdict rate and the average change in juror
   guilt registers after defence messages.
5. Count categorical flips toward not guilty and how long those flips survive.
6. Measure evidence grounding, unsupported claims, schema repair, failures,
   latency, tokens, and cost.
7. Publish intervals, sample counts, exact versions, and losing runs—not only
   the most dramatic successful replay.

Use provider-supported sampling seeds where available. The example’s `--seed`
controls the deterministic fixture and procedural randomization; it does not
force every live inference backend to sample identically. For providers
without seeded generation, record repeated calls as stochastic replicates,
randomize evaluation order, and save exact model versions and timestamps.

If one model eventually produces not-guilty verdicts in 75 of 100 matched runs
and another in 52, that would be a compelling result—but those numbers must be
measured, never invented in advance. The more important question is whether
the difference comes from evidence-based advocacy, exploitation of juror
biases, confident unsupported rhetoric, or simple protocol reliability.

“Persuasive” is not synonymous with “correct” or “good.” The hidden truth in
this fixture favors guilt, so a stronger defence agent may be better at moving
jurors away from the synthetic answer. Persuasive effectiveness, factual
grounding, calibration, and verdict correctness therefore belong on separate
axes.

A serious leaderboard would also use multiple balanced fictional cases:
some whose synthetic truth favors the defendant, some that favor liability,
and some that remain deliberately ambiguous. Otherwise the benchmark may only
measure which model happens to fit Aster Vale’s story.

A credible comparison should:

1. Freeze the case, prompts, topology, evidence order, round count, and output
   contracts.
2. Match runs by recorded treatment and replicate IDs; use a seed as a matching
   key only when the provider supports seeded inference. Verify matching public
   records and control fingerprints wherever the experimental design requires
   them to remain fixed.
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
FIGURE 6 SUGGESTION — Defence persuasion benchmark
Placement: after the provider-comparison section, once real repeated runs exist.
Do not prefill fabricated winners. Rows: exact defence provider/model/version.
Columns: not-guilty panel rate, mean pre/post guilt-register change, vote flips
toward not guilty, lift versus the common reference closing, evidence-grounding
rate, unsupported-claim rate, schema-repair rate, latency, estimated tokens,
and measured cost. Show Independent as the primary result and Star/Mesh as
separate follow-up strata; do not pool the topologies. Give every cell an
interval and panel count, and put model date, jury model, temperature, and
replication design in a footnote. An adjacent scatter plot can compare
grounding (x) with persuasion lift (y). Caption: “The most persuasive advocate
is not necessarily the most truthful one.”
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

## The less glamorous lesson: reliable communication is part of A2A

The local-model run is interesting partly because long agent workflows expose
small formatting mistakes quickly. A model may produce a good courtroom answer
inside the wrong outer object, return JSON where the protocol expected text,
surround a payload with prose, or omit an application field.

ProtoLink keeps two contracts separate:

1. **Action validation** asks whether the model is finishing, calling a tool,
   or delegating to another agent.
2. **Application validation** asks whether the final content is a valid
   tribunal statement, juror update, communication action, ballot, or judgment.

A valid `FinalAction` can still contain an invalid ballot. Keeping the layers
separate makes the failure understandable and prevents a broad “retry
everything” loop from hiding what went wrong.

The recovery path is deliberately narrow:

- parse and validate strictly first;
- give the model bounded, field-specific repair feedback;
- normalize only unambiguous shapes, such as serializing structured final
  content without changing it;
- recover plain prose only for public statements, never for votes, verdicts,
  evidence choices, or message targets.

The system does not invent missing decisions to keep the demo moving. Every
repair is bounded and recorded. `--action-parse-attempts` controls the outer
ProtoLink layer; `--max-attempts` controls the tribunal response layer. Both
default to three and accept one to five, while provider/network backoff remains
a separate lower layer.

That distinction matters experimentally. A model that completes 93 messages
cleanly is behaving differently from one that reaches the same verdict after
frequent repair. Repair rate belongs beside grounding, outcome, latency, and
cost.

The detailed parsing and normalization contract is documented in
[`docs/content/llm.md`](../../docs/content/llm.md).

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
- Persona demographics are controlled prompt variables; models may respond to
  them through learned stereotypes rather than authentic lived experience.
- Legal guilt is an intentionally simplified fictional decision. The system
  should not be used to evaluate real people, products, or cases.
- Token counts and costs vary by provider, and live services can change over
  time.

The next serious experiment would run a preregistered matrix across cases,
seeds, providers, and topologies, then ablate individual messages. It would
publish both successes and reversals, including cases where communication makes
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
