"""Embedded admission, reconnect and request identity never resubmit work."""

import asyncio

import pytest

from protolink import Agent, AgentGroup, GroupLimits, RunHandle, StreamGapError, Task
from protolink.core.events import RunEvent


def tool_task(value="hello"):
    return Task.create_tool_call(tool_name="work", args={"value": value})


def worker():
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    agent = Agent(name="worker", verbosity=0)

    @agent.tool
    async def work(value: str) -> str:
        """Wait until the application permits this observation."""
        calls.append(value)
        entered.set()
        await release.wait()
        return value

    return agent, entered, release, calls


@pytest.mark.asyncio
async def test_fifo_admission_queue_full_cancel_and_timeout():
    agent, entered, release, calls = worker()
    limits = GroupLimits(max_concurrent_runs=1, max_queued_runs=2, queue_timeout=0.08)
    async with AgentGroup([agent], limits=limits) as group:
        first = group.run(agent, tool_task("first"))
        await entered.wait()
        second = group.run(agent, tool_task("second"))
        third = group.run(agent, tool_task("third"))
        rejected = group.run(agent, tool_task("overflow"))
        assert group.snapshot().active_runs == 1
        assert group.snapshot().queued_runs == 2
        result = await rejected.result()
        assert result.status == "failed" and result.error["code"] == "queue_full"
        assert "run.rejected" in [e.type async for e in rejected.events()]
        await second.cancel()
        assert (await second.result()).status == "canceled"
        expired = await third.result()
        assert expired.error["code"] == "queue_timeout"
        assert group.snapshot().queued_runs == 0
        release.set()
        assert (await first.result()).output == "first"
        assert calls == ["first"]
        fourth = group.run(agent, tool_task("fourth"))
        assert (await fourth.result()).status == "completed"
        assert calls == ["first", "fourth"]
    assert group.snapshot().state == "closed"
    assert group.snapshot().active_runs == group.snapshot().queued_runs == 0


@pytest.mark.asyncio
async def test_queue_keeps_private_context_and_fifo():
    from protolink import current_request_context, request_context

    agent, entered, release, calls = worker()
    observed = []

    @agent.tool
    async def inspect() -> str:
        """Read a request-local value after admission."""
        value = current_request_context()["value"]
        observed.append(value)
        return value

    async with AgentGroup([agent], limits=GroupLimits(max_concurrent_runs=1)) as group:
        first = group.run(agent, tool_task())
        await entered.wait()
        with request_context({"value": "frozen"}):
            second = group.run(agent, Task.create_tool_call(tool_name="inspect", args={}))
        third = group.run(agent, tool_task("last"))
        release.set()
        await asyncio.gather(*(handle.result() for handle in (first, second, third)))
        assert observed == ["frozen"]
        assert calls == ["hello", "last"]


@pytest.mark.asyncio
async def test_queued_task_is_an_immutable_submission_snapshot_and_deadline_prevents_execution():
    agent, entered, release, calls = worker()
    async with AgentGroup([agent], limits=GroupLimits(max_concurrent_runs=1, queue_timeout=10)) as group:
        first = group.run(agent, tool_task("first"))
        await entered.wait()
        task = tool_task("original")
        second = group.run(agent, task, request_id="request")
        task.messages[0].parts[0].content.args["value"] = "mutated"
        assert group.run(agent, tool_task("original"), request_id="request") is second
        assert task.metadata == {}  # Submission does not attach execution state to caller-owned input.
        expired = group.run(agent, tool_task("expired"))
        expired._admission.deadline = asyncio.get_running_loop().time() - 1
        release.set()
        assert (await first.result()).status == "completed"
        assert (await second.result()).output == "original"
        assert (await expired.result()).error["code"] == "queue_timeout"
        assert calls == ["first", "original"]


@pytest.mark.asyncio
async def test_request_ids_reconnect_retention_and_input_conflicts():
    agent, entered, release, calls = worker()
    async with AgentGroup([agent], max_retained_runs=1) as group:
        task = tool_task()
        first = group.run(agent, task, request_id="alice:1")
        original_run_id = first.context.run_id
        await entered.wait()
        assert group.run("worker", tool_task(), request_id="alice:1") is first
        assert first.context.run_id == original_run_id
        assert group.get_run(original_run_id) is first
        with pytest.raises(ValueError, match="different input"):
            group.run(agent, tool_task("changed"), request_id="alice:1")
        release.set()
        await first.result()
        assert group.run(agent, tool_task(), request_id="alice:1") is first
        next_run = group.run(agent, tool_task("next"), request_id="alice:2")
        await next_run.result()
        await asyncio.sleep(0)  # Run completion callback evicts oldest finished handle.
        with pytest.raises(KeyError):
            group.get_run(original_run_id)
        assert group.get_run(next_run.context.run_id) is next_run
        assert calls == ["hello", "next"]


@pytest.mark.asyncio
async def test_request_id_preserves_permissions_and_distinct_local_targets():
    agent, entered, release, _calls = worker()
    other, _entered, _release, _other_calls = worker()
    async with AgentGroup([agent]) as group:
        task = tool_task()
        task.metadata["permissions"] = {"read": True}
        first = group.run(agent, task, request_id="request")
        await entered.wait()
        equivalent = tool_task()
        equivalent.metadata["permissions"] = {"read": True}
        assert group.run(agent, equivalent, request_id="request") is first
        with pytest.raises(ValueError, match="different input"):
            group.run(agent, tool_task(), request_id="request")
        with pytest.raises(ValueError, match="different input"):
            group.run(other, equivalent, request_id="request")
        release.set()
        await first.result()


@pytest.mark.asyncio
async def test_subscription_cursor_gap_and_multiple_readers_do_not_execute_again():
    agent, entered, release, calls = worker()
    async with AgentGroup([agent], event_buffer_size=2) as group:
        handle = group.run(agent, tool_task())
        await entered.wait()
        for index in range(4):
            await handle._record(RunEvent(type="test", payload={"index": index}))
        latest = handle._sequence
        with pytest.raises(StreamGapError) as gap:
            await anext(handle.events(after=0))
        assert gap.value.latest == latest
        assert gap.value.first_available == latest - 1
        retained = handle.events(after=latest - 2)
        assert (await anext(retained)).sequence == latest - 1
        await retained.aclose()
        release.set()
        await handle.result()
        # Full report remains available even when the live replay window evicts.
        assert len(handle.report.events) > 2
        cursor = handle._sequence - 2
        one = [e.sequence async for e in group.get_run(handle.context.run_id).events(after=cursor)]
        two = [e.sequence async for e in handle.events(after=cursor)]
        assert one == two == [cursor + 1, cursor + 2]
        assert calls == ["hello"]


@pytest.mark.asyncio
async def test_queued_remote_cancellation_and_immediate_cancel_never_submit():
    class Client:
        async def send_task_streaming(self, url, task):
            raise AssertionError("Canceled submission must not reach the transport")
            yield

    handle = RunHandle.start("runtime://remote", tool_task(), client=Client())
    await handle.cancel()
    assert (await handle.result()).status == "canceled"
    agent, entered, release, calls = worker()
    async with AgentGroup([agent], client=Client(), limits=GroupLimits(max_concurrent_runs=1)) as group:
        first = group.run(agent, tool_task())
        await entered.wait()
        remote = group.run("runtime://remote", tool_task())
        await remote.cancel()
        assert (await remote.result()).status == "canceled"
        release.set()
        await first.result()
        assert calls == ["hello"]


@pytest.mark.asyncio
async def test_shutdown_cancels_all_waiters_without_starting_their_tools():
    agent, entered, _release, calls = worker()
    group = await AgentGroup([agent], limits=GroupLimits(max_concurrent_runs=1)).start()
    first = group.run(agent, tool_task("active"))
    await entered.wait()
    queued = [group.run(agent, tool_task(str(i))) for i in range(3)]
    await asyncio.wait_for(group.close(), 2)
    assert calls == ["active"]
    results = await asyncio.gather(*(handle.result() for handle in [first, *queued]))
    assert all(result.status == "canceled" for result in results)


@pytest.mark.parametrize(
    "kwargs", [{"max_concurrent_runs": 0}, {"max_queued_runs": -1}, {"queue_timeout": float("nan")}]
)
def test_admission_configuration_rejects_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        GroupLimits(**kwargs)
