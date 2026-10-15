"""Exercise real RunTree serialization and lifecycle without network exports."""

import asyncio
import inspect
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from protolink import Part, Task
from protolink.telemetry import LangSmithTelemetry

langsmith = pytest.importorskip("langsmith")
requests = pytest.importorskip("requests")


class RecordedRequests(list):
    def __init__(self):
        super().__init__()
        self.executors = []

    def wait(self):
        # Early SDKs submit RunTree requests to a real background executor.
        for executor in self.executors:
            executor.shutdown(wait=True)


@pytest.fixture
def telemetry_factory(monkeypatch):
    clients = []
    recordings = []
    executors_by_client = {}

    class RecordingSession(requests.Session):
        def __init__(self):
            super().__init__()
            self.records = RecordedRequests()

        def send(self, request, **kwargs):
            self.records.append((request.method, request.url, json.loads(request.body)))
            response = requests.Response()
            response.status_code = 200
            response._content = b"{}"
            response.headers["Content-Type"] = "application/json"
            response.request = request
            return response

    def create(project_name="test-project", api_key="test-key"):
        session = RecordingSession()
        recordings.append(session.records)
        client_parameters = inspect.signature(langsmith.Client).parameters
        executor = None
        if "executor" in inspect.signature(langsmith.RunTree).parameters:
            executor = ThreadPoolExecutor(max_workers=1)
            session.records.executors.append(executor)

        def client_factory(**kwargs):
            options = {"session": session, "auto_batch_tracing": False, "info": {"version": "test"}}
            options = {name: value for name, value in options.items() if name in client_parameters}
            client = langsmith.Client(**kwargs, api_url="http://127.0.0.1:9", **options)
            if "session" not in options:
                session.headers.update(client.session.headers)
                client.session.close()
                client.session = session
            clients.append(client)
            executors_by_client[id(client)] = executor
            return client

        def run_tree_factory(**kwargs):
            run_executor = executors_by_client[id(kwargs["client"])]
            if run_executor is not None:
                kwargs["executor"] = run_executor
            return langsmith.RunTree(**kwargs)

        monkeypatch.setattr(
            "protolink.telemetry.langsmith_telemetry.require_langsmith",
            lambda: (langsmith, client_factory, run_tree_factory),
        )
        return LangSmithTelemetry(api_key=api_key, project_name=project_name), session.records

    yield create
    for records in recordings:
        records.wait()
    for client in clients:
        if hasattr(client, "close"):
            client.close()
        else:
            client.session.close()


def posted_runs(records):
    records.wait()
    return {body["id"]: body for method, _, body in records if method == "POST"}


def patched_runs(records):
    records.wait()
    return {url.rsplit("/", 1)[-1]: body for method, url, body in records if method == "PATCH"}


@pytest.mark.asyncio
async def test_real_sdk_posts_task_children_and_final_results(telemetry_factory):
    telemetry, records = telemetry_factory()
    task = Task.create_infer(prompt="hello")

    await telemetry.on_task_start(task, "assistant")
    await telemetry.on_llm_start("hello", model="test-model", metadata={"tokens": 3})
    await telemetry.on_llm_end(Part("text", "answer"))
    await telemetry.on_tool_start("success", {"value": 1})
    await telemetry.on_tool_end("success", {"value": 2})
    await telemetry.on_tool_start("failure", {})
    await telemetry.on_tool_end("failure", None, error="unavailable")
    await telemetry.on_task_end(task, task, "assistant")

    posts = posted_runs(records)
    patches = patched_runs(records)
    assert len(posts) == len(patches) == 4
    root = next(run for run in posts.values() if run["run_type"] == "chain")
    assert root["session_name"] == "test-project"
    assert root["inputs"] == {"task_id": task.id}
    assert root["extra"]["metadata"]["agent_name"] == "assistant"
    assert patches[root["id"]]["outputs"] == task.to_dict()
    for run in posts.values():
        assert patches[run["id"]]["end_time"]
        if run is not root:
            assert run["parent_run_id"] == root["id"]
            if "dotted_order" in run:
                assert run["trace_id"] == root["trace_id"]
                assert run["dotted_order"].startswith(root["dotted_order"] + ".")
        update = patches[run["id"]]
        if run["run_type"] == "llm":
            assert run["inputs"] == {"prompt": "hello", "model": "test-model", "metadata": {"tokens": 3}}
            assert update["outputs"] == {"response": "answer"}
        elif run["name"] == "Tool: success":
            assert update["outputs"] == {"result": {"value": 2}}
        elif run["name"] == "Tool: failure":
            assert update["error"] == "unavailable"


@pytest.mark.asyncio
async def test_nested_tasks_restore_parent_generation(telemetry_factory):
    telemetry, records = telemetry_factory()
    parent = Task.create_infer(prompt="parent")
    child = Task.create_infer(prompt="child")

    await telemetry.on_task_start(parent, "parent")
    await telemetry.on_llm_start("parent generation")
    await telemetry.on_task_start(child, "child")
    await telemetry.on_llm_start("child generation")
    await telemetry.on_llm_end(Part("text", "child output"))
    await telemetry.on_task_end(child, child, "child")
    await telemetry.on_llm_end(Part("text", "parent output"))
    await telemetry.on_task_end(parent, parent, "parent")

    posts = posted_runs(records)
    patches = patched_runs(records)
    assert len(posts) == len(patches) == 4
    for run in posts.values():
        if run["run_type"] == "llm":
            root = posts[run["parent_run_id"]]
            expected = root["name"].removeprefix("Task: ") + " output"
            assert patches[run["id"]]["outputs"] == {"response": expected}


@pytest.mark.asyncio
async def test_concurrent_tasks_and_tracker_instances_do_not_share_runs(telemetry_factory):
    first, first_records = telemetry_factory("first-project")
    second, second_records = telemetry_factory("second-project")

    async def run(name):
        task = Task.create_infer(prompt=name)
        await first.on_task_start(task, name)
        await second.on_task_start(task, name)
        await first.on_llm_start(name)
        await second.on_llm_start(name)
        await asyncio.sleep(0)
        await first.on_llm_end(Part("text", name))
        await second.on_llm_end(Part("text", name))
        await second.on_task_end(task, task, name)
        await first.on_task_end(task, task, name)

    await asyncio.gather(run("one"), run("two"))
    for project, records in (("first-project", first_records), ("second-project", second_records)):
        posts = posted_runs(records)
        patches = patched_runs(records)
        assert len(posts) == len(patches) == 4
        assert all(run["session_name"] == project for run in posts.values())
        for run in posts.values():
            if run["run_type"] == "llm":
                root = posts[run["parent_run_id"]]
                assert patches[run["id"]]["outputs"] == {"response": root["name"].removeprefix("Task: ")}


@pytest.mark.asyncio
async def test_failed_nested_start_cannot_attach_hooks_to_parent(telemetry_factory, monkeypatch):
    telemetry, records = telemetry_factory()
    parent = Task.create_infer(prompt="parent")
    child = Task.create_infer(prompt="child")
    await telemetry.on_task_start(parent, "parent")
    original_post = langsmith.RunTree.post

    def fail_child(self, *args, **kwargs):
        if self.name == "Task: child":
            raise RuntimeError("SDK unavailable")
        return original_post(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(langsmith.RunTree, "post", fail_child)
        await telemetry.on_task_start(child, "child")
    await telemetry.on_tool_start("must-not-attach-to-parent", {})
    await telemetry.on_tool_end("must-not-attach-to-parent", "ignored")
    await telemetry.on_task_end(child, child, "child")
    await telemetry.on_tool_start("parent-tool", {})
    await telemetry.on_tool_end("parent-tool", "done")
    await telemetry.on_task_end(parent, parent, "parent")

    posts = posted_runs(records)
    assert {run["name"] for run in posts.values()} == {"Task: parent", "Tool: parent-tool"}
    assert len(patched_runs(records)) == 2


@pytest.mark.parametrize("explicit", [False, True])
def test_modern_environment_settings_and_explicit_overrides(telemetry_factory, monkeypatch, explicit):
    monkeypatch.setenv("LANGSMITH_API_KEY", "modern-key")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "legacy-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "modern-project")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "legacy-project")
    telemetry, _ = telemetry_factory(
        api_key="explicit-key" if explicit else None,
        project_name="explicit-project" if explicit else None,
    )
    assert telemetry.client.api_key == ("explicit-key" if explicit else "modern-key")
    assert telemetry.project_name == ("explicit-project" if explicit else "modern-project")


def test_legacy_environment_settings_remain_supported(telemetry_factory, monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.setenv("LANGCHAIN_API_KEY", "legacy-key")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "legacy-project")
    telemetry, _ = telemetry_factory(api_key=None, project_name=None)
    assert telemetry.client.api_key == "legacy-key"
    assert telemetry.project_name == "legacy-project"
