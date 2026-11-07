"""The public answer view never exposes the runtime's action protocol."""

import asyncio
import json

import pytest

from protolink.core.answers import _AnswerProjector
from protolink.core.events import RunEvent
from protolink.core.redaction import RedactionPolicy
from protolink.llms.mock_client import MockLLM


def event(kind, content=None, *, task_id="root", sequence=1, **metadata):
    return RunEvent(
        type="llm.stream",
        task_id=task_id,
        run_id="run-root",
        agent_name="writer",
        sequence=sequence,
        payload={"llm_event_type": kind, "content": content, "metadata": metadata},
    )


def display(updates):
    value = ""
    for update in updates:
        if update.type == "delta":
            value += update.content
        else:
            value = update.content
    return value


@pytest.mark.parametrize("width", [1, 2, 7, 1024])
def test_json_final_only_streams_decoded_content_with_exact_markdown(width):
    answer = '  ## Prices\n\n- **ETH**: €2\\3\n- 🚀: "up"\n\n'
    raw = json.dumps({"thought": "private reasoning", "type": "final", "content": answer})
    projection = _AnswerProjector("root")
    updates = []
    for index in range(0, len(raw), width):
        updates.extend(projection.feed(event("llm_chunk", raw[index : index + width], sequence=index + 1)))
    assert display(updates) == answer
    assert "private reasoning" not in "".join(update.content for update in updates)
    assert all(update.provisional for update in updates)
    updates.extend(projection.finish("completed", answer))
    assert display(updates) == answer
    assert updates[-1].type == "completed" and updates[-1].provisional is False
    assert [update.sequence for update in updates] == list(range(1, len(updates) + 1))
    assert updates[-1].source_sequence == ((len(raw) - 1) // width) * width + 1


def test_content_before_discriminator_is_withheld_until_identified():
    projection = _AnswerProjector("root")
    assert projection.feed(event("llm_chunk", '{"content":"hello"')) == ()
    updates = projection.feed(event("llm_chunk", ',"type":"final"}'))
    assert display(updates) == "hello"


def test_changed_discriminator_withdraws_the_previous_answer_prefix():
    projection = _AnswerProjector("root")
    updates = list(projection.feed(event("llm_chunk", '{"type":"final","content":"draft"')))
    assert display(updates) == "draft"
    updates.extend(projection.feed(event("llm_chunk", ',"type":"tool_call"}')))
    assert display(updates) == ""
    assert updates[-1].type == "replacement"


@pytest.mark.parametrize(
    "raw",
    [
        '{"thought":"private","type":"tool_call","tool":"trade","args":{"content":"secret"}}',
        '{"args":{"type":"final","content":"secret"},"type":"tool_call","tool":"trade"}',
        '{"type":"agent_call","agent":"analyst","action":"infer","prompt":"secret"}',
        '{"tool_calls":[{"type":"final","content":"secret"}]}',
    ],
)
def test_action_envelopes_and_nested_content_are_never_answers(raw):
    projection = _AnswerProjector("root")
    updates = []
    for character in raw:
        updates.extend(projection.feed(event("llm_chunk", character)))
    assert updates == []
    assert projection.finish("failed", None) == ()


def test_native_text_and_reasoning_prefixes_are_separated():
    projection = _AnswerProjector("root")
    updates = []
    raw = "<think>private thought</think>\n\n# Public answer\n"
    for character in raw:
        updates.extend(projection.feed(event("llm_chunk", character)))
    assert display(updates) == "\n\n# Public answer\n"
    assert "private" not in "".join(update.content for update in updates)
    updates.extend(projection.feed(event("llm_final", raw)))
    updates.extend(projection.finish("completed", raw))
    assert display(updates) == "\n\n# Public answer\n"


@pytest.mark.parametrize("tag", ["think", "thought"])
@pytest.mark.parametrize("closed", [False, True])
def test_native_reasoning_stays_private_when_final_hooks_wrap_or_edit_text(tag, closed):
    projection = _AnswerProjector("root")
    raw = f"<{tag}>private reasoning" + (f"</{tag}>Answer" if closed else "")
    updates = []
    for character in raw:
        updates.extend(projection.feed(event("llm_chunk", character)))
    authoritative = "Checked: " + raw + " [approved]"
    updates.extend(projection.feed(event("llm_final", authoritative)))
    updates.extend(projection.finish("completed", authoritative))
    assert display(updates) == "Checked: " + ("Answer" if closed else "") + " [approved]"
    assert "private reasoning" not in "".join(item.content for item in updates)


@pytest.mark.parametrize("fenced", [False, True])
def test_reasoning_prefixed_json_keeps_literal_final_content(fenced):
    projection = _AnswerProjector("root")
    literal = "<think>This is a literal example.</think>\n"
    envelope = json.dumps({"type": "final", "content": literal})
    if fenced:
        envelope = f"```json\n{envelope}\n```"
    raw = "<think>private reasoning</think>" + envelope
    updates = []
    for character in raw:
        updates.extend(projection.feed(event("llm_chunk", character)))
    updates.extend(projection.feed(event("llm_final", literal)))
    updates.extend(projection.finish("completed", literal))
    assert display(updates) == literal
    assert "private reasoning" not in "".join(item.content for item in updates)


@pytest.mark.parametrize("answer", ['{"asset":"ETH"}', "```python\nprint(1)\n```"])
def test_native_reasoning_before_json_or_code_answers_remains_private(answer):
    projection = _AnswerProjector("root")
    raw = "<think>private reasoning</think>" + answer
    updates = list(projection.feed(event("llm_chunk", raw)))
    updates.extend(projection.feed(event("llm_final", raw + "\nChecked.")))
    updates.extend(projection.finish("completed", raw + "\nChecked."))
    assert display(updates) == answer + "\nChecked."
    assert "private reasoning" not in "".join(item.content for item in updates)


def test_identifier_redaction_matches_content_redaction():
    projection = _AnswerProjector(
        "root", redaction_policy=RedactionPolicy(sensitive_values=frozenset({"root", "writer"}))
    )
    updates = projection.feed(event("llm_final", "Public answer"))
    assert updates[0].task_id == "[REDACTED]"
    assert updates[0].run_id == "run-[REDACTED]"
    assert updates[0].agent_name == "[REDACTED]"
    assert updates[0].content == "Public answer"


def test_json_fence_and_partial_escape_are_withheld():
    projection = _AnswerProjector("root")
    updates = []
    for chunk in ["```j", 'son\n{"type":"final","content":"A\\', "n\\uD83D", "\\uDE80", '"}\n```']:
        updates.extend(projection.feed(event("llm_chunk", chunk)))
    assert display(updates) == "A\n🚀"
    assert all(not any(0xD800 <= ord(char) <= 0xDFFF for char in update.content) for update in updates)


@pytest.mark.parametrize("encoded", [False, True])
@pytest.mark.parametrize("width", [1, 3, 5])
def test_redaction_masks_secrets_split_across_any_chunks(encoded, width):
    secret = "s3cr3t-🚀-token"
    answer = f"Public text {secret}; trailing public text."
    projection = _AnswerProjector("root", redaction_policy=RedactionPolicy(sensitive_values=frozenset({secret})))
    raw = json.dumps({"type": "final", "content": answer}) if encoded else answer
    updates = []
    for index in range(0, len(raw), width):
        updates.extend(projection.feed(event("llm_chunk", raw[index : index + width])))
        assert secret not in display(updates)
        assert "s3cr3t" not in display(updates)
    updates.extend(projection.feed(event("llm_final", answer)))
    updates.extend(projection.finish("completed", answer))
    assert display(updates) == "Public text [REDACTED]; trailing public text."


def test_tool_transition_and_completion_hooks_replace_provisional_text():
    projection = _AnswerProjector("root")
    updates = list(projection.feed(event("llm_chunk", "Draft answer")))
    updates.extend(projection.feed(event("tool_start", tool="inspect")))
    assert updates[-1].type == "replacement" and display(updates) == ""
    updates.extend(projection.feed(event("llm_call_started")))
    updates.extend(projection.feed(event("llm_chunk", "New answer")))
    updates.extend(projection.feed(event("llm_final", "Hook-adjusted answer")))
    assert updates[-1].type == "replacement"
    updates.extend(projection.finish("completed", "Final task answer"))
    assert display(updates) == "Final task answer"
    assert [update.type for update in updates[-2:]] == ["replacement", "completed"]
    assert projection.finish("completed", "Duplicate") == ()


@pytest.mark.parametrize("status", ["canceled", "failed", "rejected", "input-required", "uncertain"])
def test_non_success_withdraws_provisional_text_and_never_completes(status):
    projection = _AnswerProjector("root")
    updates = list(projection.feed(event("llm_chunk", "Unfinished answer")))
    updates.extend(projection.feed(event("llm_final", "Still provisional")))
    updates.extend(projection.finish(status, "Must not succeed"))
    assert display(updates) == ""
    assert "completed" not in [update.type for update in updates]
    assert projection.feed(event("llm_chunk", "Late event")) == ()


def test_child_answers_are_excluded_and_final_content_is_not_reparsed():
    projection = _AnswerProjector("root")
    assert projection.feed(event("llm_chunk", "private child", task_id="child")) == ()
    assert projection.feed(event("llm_final", "private child", task_id="child")) == ()
    answer = 'Example: {"type":"tool_call","tool":"example"}'
    updates = projection.feed(event("llm_final", answer, sequence=27))
    assert display(updates) == answer
    assert updates[0].source_sequence == 27
    assert updates[0].to_dict()["agent_name"] == "writer"


def test_structured_output_has_no_implicit_string_rendering():
    projection = _AnswerProjector("root")
    assert projection.finish("completed", {"price": 100}) == ()


def test_ordinary_json_is_buffered_then_preserved_by_validated_final():
    projection = _AnswerProjector("root")
    answer = '{"asset":"BTC","prices":[1,2,3]}'
    assert projection.feed(event("llm_chunk", answer)) == ()
    updates = projection.feed(event("llm_final", answer))
    assert display(updates) == answer


class FragmentedLLM(MockLLM):
    """An offline provider that yields configurable native or JSON fragments."""

    def __init__(self, answer, *, native=False, width=1, pause=None):
        super().__init__(default_response=answer)
        self.answer = answer
        self.native = native
        self.raw = (
            answer if native else json.dumps({"thought": "internal reasoning", "type": "final", "content": answer})
        )
        self.width = width
        self.pause = pause
        self.calls = 0

    async def call_stream(self, history):
        self.calls += 1
        for index in range(0, len(self.raw), self.width):
            yield self.raw[index : index + self.width]
            if self.pause is not None:
                await self.pause.wait()
            await asyncio.sleep(0)

    async def call_action_stream(self, history, *, tools, chunk_callback=None, **kwargs):
        from protolink.llms.actions import FinalAction, LLMActionResult

        if not self.native:
            return await super().call_action_stream(history, tools=tools, chunk_callback=chunk_callback, **kwargs)
        async for chunk in self.call_stream(history):
            if chunk_callback is not None:
                await chunk_callback(chunk)
        return LLMActionResult(FinalAction(content=self.answer), raw_response=self.raw, native=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_handle_answer_stream_is_live_and_subscribers_replay_without_reexecution(native):
    from protolink import Agent, AnswerEvent

    pause = asyncio.Event()
    answer = "# Market\n\n**ETH** → 🚀  \n"
    llm = FragmentedLLM(answer, native=native, pause=pause)
    agent = Agent(name="answer-replay", llm=llm, verbosity=0)
    handle = agent.start_run("Summarize the market")
    subscription = handle.answer_events()
    try:
        # Allow the initial discriminator to arrive, then stop the provider on
        # its next fragment. The consumer must see text before task completion.
        pause.set()
        first = await asyncio.wait_for(anext(subscription), 2)
        assert isinstance(first, AnswerEvent)
        pause.clear()
        assert first.provisional and first.type == "delta"
        assert handle.report.final_task is None
        pause.set()

        async def collect(stream):
            return [item async for item in stream]

        remaining, replay = await asyncio.wait_for(
            asyncio.gather(collect(subscription), collect(handle.answer_events(after=first.sequence))), 2
        )
        result = await handle.result()
        full_replay = [item async for item in handle.answer_events()]
        assert remaining == replay
        assert [first, *remaining] == full_replay
        assert display(full_replay) == answer == result.output
        assert full_replay[-1].type == "completed"
        assert llm.calls == 1
    finally:
        pause.set()
        await subscription.aclose()
        await handle.cancel("test cleanup")
        await handle.result()


@pytest.mark.asyncio
async def test_handle_keeps_owned_child_answers_out_of_root_answer_stream():
    from protolink import Agent

    child = Agent(name="answer-child", llm=FragmentedLLM("private child answer", native=True), verbosity=0)
    parent = Agent(
        name="answer-parent",
        llm=MockLLM(
            sequential_responses=[
                {"type": "agent_call", "agent": child.card.name, "action": "infer", "prompt": "analyze"},
                "public parent answer",
            ]
        ),
        subagents=[child],
        verbosity=0,
    )
    handle = parent.start_run("Delegate analysis")
    updates = [item async for item in handle.answer_events()]
    result = await handle.result()
    assert result.status == "completed" and result.output == "public parent answer"
    assert display(updates) == "public parent answer"
    assert all("private child" not in item.content for item in updates)
    assert any(item.agent_name == child.card.name for item in result.report.events)


@pytest.mark.asyncio
async def test_handle_does_not_present_string_tool_results_as_answers():
    from protolink import Agent, RunHandle, Task

    agent = Agent(name="tool-answer", verbosity=0)

    @agent.tool
    def inspect() -> str:
        return "private tool result"

    handle = RunHandle.start(agent, Task.create_tool_call(tool_name="inspect", args={}))
    assert [item async for item in handle.answer_events()] == []
    assert (await handle.result()).output == "private tool result"


@pytest.mark.asyncio
async def test_handle_replaces_draft_with_hook_result_before_success():
    from protolink import Agent, AgentHooks

    def finalize(response):
        response.content = "Checked answer\n"

    agent = Agent(
        name="hook-answer",
        llm=FragmentedLLM("Draft answer", native=True),
        hooks=[AgentHooks(before_complete=finalize)],
        verbosity=0,
    )
    handle = agent.start_run("write")
    updates = [item async for item in handle.answer_events()]
    assert any(item.type == "replacement" and item.content == "Checked answer\n" for item in updates)
    assert display(updates) == (await handle.result()).output == "Checked answer\n"
    assert updates[-1].type == "completed"


@pytest.mark.asyncio
async def test_handle_redacts_across_raw_recording_boundary():
    from protolink import Agent, RunHandle, Task

    secret = "abcdefgh🚀token"
    answer = f"Visible {secret}; public conclusion."
    agent = Agent(name="secret-answer", llm=FragmentedLLM(answer), verbosity=0)
    handle = RunHandle.start(
        agent,
        Task.create_infer(prompt="answer safely"),
        redaction_policy=RedactionPolicy(sensitive_values=frozenset({secret, "cde"})),
    )
    updates = []
    async for item in handle.answer_events():
        updates.append(item)
        assert "abcdefgh" not in display(updates)
        assert secret not in display(updates)
    assert display(updates) == "Visible [REDACTED]; public conclusion."
    assert (await handle.result()).status == "completed"


@pytest.mark.asyncio
async def test_handle_cancellation_withdraws_live_text_without_success():
    from protolink import Agent

    pause = asyncio.Event()
    agent = Agent(name="cancel-answer", llm=FragmentedLLM("Provisional answer", native=True, pause=pause), verbosity=0)
    handle = agent.start_run("write")
    stream = handle.answer_events()
    first = await asyncio.wait_for(anext(stream), 2)
    assert first.type == "delta"
    await handle.cancel("stop generation")
    updates = [first, *[item async for item in stream]]
    result = await asyncio.wait_for(handle.result(), 2)
    assert result.status == "canceled"
    assert display(updates) == ""
    assert all(item.type != "completed" for item in updates)
