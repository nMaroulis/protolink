"""Persistence policies mask copies before any task or report reaches SQLite."""

import json
from copy import deepcopy

import pytest

from protolink import Agent, AgentCard, RedactionPolicy, RunHandle, RunReport, SQLiteRunStore, Task


@pytest.mark.asyncio
async def test_every_agent_snapshot_and_report_is_redacted_without_changing_execution(tmp_path):
    secret = "credential-123"
    store = SQLiteRunStore(tmp_path / "runs.db", redaction_policy=RedactionPolicy(sensitive_values={secret}))
    agent = Agent(
        AgentCard(name="safe-store", description="test", url="runtime://safe-store"), run_store=store, verbosity=0
    )

    @agent.tool
    def echo(value: str) -> dict:
        assert value == secret
        return {"stdout": f"output {value}", "password": "hidden", "data_base64": "cmVjb3Zlcnk="}

    task = Task.create_tool_call(tool_name="echo", args={"value": secret})
    result = await RunHandle.start(agent, task).result()
    assert result.output["stdout"] == f"output {secret}"
    report_record = store.get_report_record(result.report.context.run_id)
    task_record = store.get_task_record(task.id)
    for record in (report_record, task_record):
        serialized = json.dumps(record.to_dict())
        assert secret not in serialized and "cmVjb3Zlcnk=" not in serialized and '"hidden"' not in serialized
        assert "[REDACTED]" in serialized
    assert secret.encode() not in (tmp_path / "runs.db").read_bytes()
    assert store.get_task(task.id).state == task.state
    assert store.get_report(result.report.context.run_id).context.run_id == result.report.context.run_id


def test_redaction_covers_caller_metadata_and_nested_payloads_and_preserves_sources(tmp_path):
    policy = RedactionPolicy(sensitive_values={"abc", "abcdef", "literal.*"})
    store = SQLiteRunStore(tmp_path / "runs.db", redaction_policy=policy)
    task = Task.create_infer(prompt="abcdef and literal.*")
    task.metadata["nested"] = {"AUTHORIZATION": "Bearer hidden", "items": [{"client-secret": "secret"}]}
    report = RunReport.from_task(task)
    metadata = {"message": "abcdef abc literal.*", "token": "token value"}
    before_task, before_report, before_metadata = (
        deepcopy(task.to_dict()),
        deepcopy(report.to_dict()),
        deepcopy(metadata),
    )
    for record in (store.save_task(task, metadata=metadata), store.save_report(report, metadata=metadata)):
        assert record.metadata == {"message": "[REDACTED] [REDACTED] [REDACTED]", "token": "[REDACTED]"}
        serialized = json.dumps(record.to_dict())
        assert "abcdef" not in serialized and "literal.*" not in serialized and "Bearer hidden" not in serialized
    assert task.to_dict() == before_task and report.to_dict() == before_report and metadata == before_metadata


def test_unconfigured_store_keeps_existing_raw_contract(tmp_path):
    store = SQLiteRunStore(tmp_path / "raw.db")
    task = Task.create_infer(prompt="private output")
    task.metadata["password"] = "raw"
    assert store.save_task(task).task["metadata"]["password"] == "raw"
    report = RunReport.from_task(task)
    assert store.save_report(report).report == report.to_dict()


def test_secret_values_are_validated_hidden_in_repr_and_masked_before_truncation():
    with pytest.raises(ValueError, match="nonempty"):
        RedactionPolicy(sensitive_values={""})
    policy = RedactionPolicy(sensitive_values={"very-long-secret"}, max_string_length=4, replacement="***")
    assert "very-long-secret" not in repr(policy)
    assert policy.redact("very-long-secret tail") == "*** ..."
