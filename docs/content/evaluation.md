# Agent evaluations

Evaluations run an Agent against named reference cases and score its actual output and execution evidence. They help compare prompts, models, tool configurations and policies using repeatable experiments. ProtoLink provides a local Python API with JSONL datasets, repetitions, asynchronous checks and portable reports; it does not require a hosted evaluation service.

```python
import asyncio
from protolink import EchoAgent, EvaluationCase, evaluate

async def main():
    report = await evaluate(
        lambda: EchoAgent(verbosity=0),
        [EvaluationCase("greeting", "hello", expected="hello")],
        repetitions=2,
    )
    print(report.passed)  # True

asyncio.run(main())
```

`evaluate()` uses ordinary Agent runs, so tools execute under their normal capabilities, approvals and budgets. Use mocked integrations or isolated application resources for experiments with external effects. Every repetition receives a distinct session. A zero-argument factory creates a fresh Agent and model per sample; supplying one Agent is supported for sequential execution.

## Datasets and checks

An `EvaluationCase` contains a unique nonblank `name`, a string `prompt`, optional `expected` output and application `metadata`. Pass a sequence or a JSONL file:

```json
{"name":"greeting","prompt":"hello","expected":"hello"}
{"name":"farewell","prompt":"bye","expected":"bye","metadata":{"category":"conversation"}}
```

```python
report = await evaluate(
    lambda: EchoAgent(verbosity=0),
    "cases.jsonl",
    repetitions=3,
    concurrency=2,
)
report.save("experiment.json")
```

Case names must be unique; JSONL files are limited to 10,000 records and one million characters per record. Experiments allow up to 100,000 total samples and cap active concurrency at 128. Parallel evaluations require a factory to avoid sharing conversation/model state. A factory should return a fresh Agent on every call, and every repetition still executes real work.

The default check, `exact_match`, compares the final output to `expected` using Python equality. Every sample also receives `execution_completed`. Use checks suited to the task rather than treating one metric as a universal measure of quality:

```python
from protolink import EvaluationScore, tool_used

def has_citations(sample):
    output = sample.output
    return EvaluationScore(
        "has_citations",
        float(isinstance(output, str) and "https://" in output),
        "Require a source URL in the completed answer.",
    )

report = await evaluate(
    make_research_agent,
    cases,
    checks=[has_citations, tool_used("fetch_url")],
)
```

Checks receive `EvaluationSample`: the reference case, repetition index, output, task, diagnostic run report, execution error, elapsed time, observed usage and existing scores. Return `EvaluationScore(name, value, comment)`, a boolean or a numeric value in `[0, 1]`. Names must be distinct within a sample. Synchronous and asynchronous checks are supported; use an explicit score name for reproducible comparisons.

`tool_used(name)` checks successful named execution evidence. It does not merely search model text for a claimed tool call. A custom check can inspect report actions, blockers and validations for richer behavioral requirements. Model-based judges can be supplied as asynchronous checks; the application owns judge credentials, cost limits, rubric and calibration. Judge calls are outside the evaluated Agent's run budget.

## Budgets, failures and cancellation

```python
from protolink import RunBudget

report = await evaluate(
    make_agent,
    cases,
    budget=RunBudget(max_steps=8, max_llm_calls=10, max_tool_calls=5),
)
```

The budget applies separately to each sample. Execution exceptions, interrupted runs and failed tasks become samples with errors. Checks can still inspect their evidence, but an interrupted task is never counted as successful completion. Evaluator exceptions are recorded visibly and make the report fail. Canceling `evaluate()` cancels and drains its active run handles before returning control; cancellation is not converted into a quality score.

`report.passed` requires every execution to complete without errors and every score to equal one. For graded rubrics, inspect score distributions and use a comparison or application threshold instead of treating every score below one as an operational failure.

## Reports and experiment comparisons

```python
from protolink import compare_evaluations

baseline = await evaluate(make_baseline_agent, cases, repetitions=3)
candidate = await evaluate(make_candidate_agent, cases, repetitions=3)
comparison = compare_evaluations(baseline, candidate, tolerance=0.02)
print(comparison["passed"], comparison["regressions"])
candidate.save("candidate.json", include_reports=True)
```

Comparisons average repetitions for each case and named metric. Missing baseline metrics and decreases beyond the tolerance are reported as regressions. Candidate execution/evaluator errors also fail the comparison. Timing is recorded but is not implicitly treated as quality. Run-report regression diffing remains available when you need to compare normalized event/action structure rather than experiment scores.

JSON exports contain reference cases, outputs, errors, scores, observed budget counters and elapsed time. Aggregate totals include steps, model calls, tool calls and input/output tokens observed by the runtime. Token counts may be estimates; provider failures can consume usage not reported by a provider, and judge usage is separate. Diagnostic run reports are included only with `include_reports=True`. Experiment files contain application input/output data, so apply your own redaction and retention policy before sharing them.

For the conceptual distinction between datasets, experiments and evaluators, see [LangSmith's evaluation concepts](https://docs.langchain.com/langsmith/evaluation-concepts). ProtoLink runs evaluations locally through its own Agent and RunReport contracts. Offline scripted experiments test those runtime contracts; real-model evaluations measure model behavior on the chosen dataset.

