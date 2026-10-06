# Agent evaluations

Evaluations run an Agent against named reference cases and score its actual output and execution evidence. They help compare prompts, models, tool configurations and policies using repeatable experiments. ProtoLink provides a local Python API with JSONL datasets, repetitions, asynchronous checks and portable reports; it does not require a hosted evaluation service.

Use evaluations to answer concrete development questions: did a new prompt improve the answers, can a smaller model still handle the required tasks, or did changing a tool introduce a regression? You define the inputs and success criteria; `evaluate()` runs the cases and collects the results.

"Local" refers to the evaluation runner and reports. Your Agent can use a local or hosted LLM, and its normal model calls and tool execution still take place. Evaluation does not change the Agent's inference loop.

Start with this complete example, which needs only the base package and no model or credentials:

```python
import asyncio
from protolink import EchoAgent, EvaluationCase, evaluate


async def main():
    cases = [
        EvaluationCase("greeting", "hello", expected="hello"),
        EvaluationCase("farewell", "bye", expected="bye"),
    ]

    report = await evaluate(
        lambda: EchoAgent(verbosity=0),
        cases,
        repetitions=3,
        concurrency=2,
    )
    print(report.passed)  # True
    print(report.to_dict()["scores"])
    report.save("evaluation.json")


asyncio.run(main())
```

Save it as `evaluate_agent.py` and run `python evaluate_agent.py`. It performs six runs: two cases repeated three times, with up to two runs active concurrently. The default checks require completed execution and an output equal to `expected`. The JSON file contains each run's output, scores, errors and execution measurements.

`evaluate()` uses ordinary Agent runs, so tools execute under their normal capabilities, approvals and budgets. Use mocked integrations or isolated application resources for experiments with external effects. Every repetition receives a distinct session. A zero-argument factory creates a fresh Agent and model per sample; supplying one Agent is supported for sequential execution.

## Cases, checks and reports

| Piece | Purpose | Example |
| --- | --- | --- |
| Case | A named input and optional reference answer | "Add 2 and 3", with `expected="5"` |
| Check | A Python function that scores output or execution evidence | Require the correct answer and successful use of `add` |
| Report | The results of running all cases and checks | Per-run scores, failures, execution time and observed usage |

One execution of a case is an `EvaluationSample`. Repeating a case produces separate samples so you can inspect variation rather than relying on one answer. The EchoAgent example demonstrates the evaluation API; meaningful model-quality experiments need your actual Agent and cases representative of its workload.

## Evaluate your own Agent

Replace the EchoAgent factory with one that constructs your application's Agent. Keep a small dataset of ordinary tasks, difficult cases and previous failures, and choose checks that describe what successful behavior means for that application.

For example, define a calculator factory alongside `main()`:

```python
from protolink import Agent, EvaluationScore, create_llm, tool_used


def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def make_calculator_agent():
    return Agent(
        name="calculator",
        llm=create_llm(
            "ollama",
            base_url="http://127.0.0.1:11434",
            model="qwen3:4b",
        ),
        tools=[add],
        system_prompt="Use add for addition. Return only the number.",
        verbosity=0,
    )


def correct_answer(sample):
    return EvaluationScore(
        "correct_answer",
        float(str(sample.output).strip() == str(sample.case.expected).strip()),
        "Compare the result after normalizing text and surrounding whitespace.",
    )
```

This configuration requires a running Ollama server with the named model available and the `protolink[ollama]` extra; see [model setup](llm.md#install-configure-and-make-the-first-call). Substitute your configured local or hosted model as needed. The factory creates a fresh Agent and model adapter for every sample.

Inside `main()`, replace the earlier evaluation call with:

```python
report = await evaluate(
    make_calculator_agent,
    [EvaluationCase("addition", "Add 2 and 3", expected="5")],
    checks=[correct_answer, tool_used("add")],
    repetitions=3,
)
```

This experiment requires both the right answer and successful execution of `add`. The answer check accepts numeric or text representations and ignores surrounding whitespace; it does not assess free-form mathematical explanations. `tool_used("add")` inspects actual execution evidence, so a final answer claiming to have used the tool cannot satisfy that check on its own.

Supplying `checks=` replaces the default `exact_match` check. The `execution_completed` check always remains. If a case has no reference answer, supply checks appropriate to its output or behavior rather than relying on the default comparison to `expected=None`.

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

Case names must be unique; JSONL files are limited to 10,000 records and one million characters per record. Experiments allow up to 100,000 total samples and cap active concurrency at 128. Parallel evaluations require a factory to avoid sharing conversation/model state. A factory should return a fresh Agent on every call and every repetition still executes real work.

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

The citation check above only detects a URL in the answer. Assessing whether sources support the claims requires a stronger application check or a calibrated model judge. Choose checks that match your requirements: exact answers for deterministic outputs, field validation for structured data, or evidence and rubric checks for research and natural-language tasks.

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

Inspect individual samples when a check fails, and use the aggregate values to understand the experiment as a whole:

```python
summary = report.to_dict()
print(summary["scores"])  # Mean score for each named metric.
print(summary["mean_duration_seconds"])
print(summary["total_usage"])
for sample in report.samples:
    print(sample.case.name, sample.output, sample.error)
```

When changing a prompt, model or configuration, run the same cases and checks against a baseline and a candidate:

```python
from protolink import compare_evaluations

baseline = await evaluate(make_baseline_agent, cases, repetitions=3)
candidate = await evaluate(make_candidate_agent, cases, repetitions=3)
comparison = compare_evaluations(baseline, candidate, tolerance=0.02)
print(comparison["passed"], comparison["regressions"])
candidate.save("candidate.json", include_reports=True)
```

Comparisons average repetitions for each case and named metric. Missing baseline metrics and decreases beyond the tolerance are reported as regressions. Candidate execution/evaluator errors also fail the comparison. Timing is recorded but is not implicitly treated as quality. Run-report regression diffing remains available when you need to compare normalized event/action structure rather than experiment scores.

For scores on the zero-to-one scale, `tolerance=0.02` permits a decrease of up to two percentage points in each case's mean metric. A passing comparison means the candidate has no detected regression beyond that tolerance and no execution/evaluator errors; it does not require every score to equal one as `report.passed` does.

JSON exports contain reference cases, outputs, errors, scores, observed budget counters and elapsed time. Aggregate totals include steps, model calls, tool calls and input/output tokens observed by the runtime. Token counts may be estimates; provider failures can consume usage not reported by a provider and judge usage is separate. Diagnostic run reports are included only with `include_reports=True`. Experiment files contain application input/output data, so apply your own redaction and retention policy before sharing them.

For the conceptual distinction between datasets, experiments and evaluators, see [LangSmith's evaluation concepts](https://docs.langchain.com/langsmith/evaluation-concepts). ProtoLink runs evaluations locally through its own Agent and RunReport contracts. Offline scripted experiments test those runtime contracts; real-model evaluations measure model behavior on the chosen dataset.
