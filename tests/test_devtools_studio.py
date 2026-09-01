"""Tests for the declarative Protolink Studio compiler and dashboard API."""

from __future__ import annotations

import ast
import copy
import json
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from protolink.devtools.server import serve_dashboard
from protolink.devtools.studio import (
    STUDIO_BUILTIN_TOOLS,
    STUDIO_FLOW_TYPES,
    STUDIO_LLM_PROVIDERS,
    StudioRuntimeManager,
    StudioValidationError,
    default_studio_blueprint,
    generate_studio_code,
    load_studio_blueprint,
    studio_catalog,
    validate_studio_blueprint,
)
from protolink.utils.renderers.devtools import DevtoolsHtmlRenderer


def test_load_studio_blueprint_reads_and_validates_json_file(tmp_path: Path):
    project_path = tmp_path / "valid_blueprint.json"
    blueprint_data = default_studio_blueprint()
    project_path.write_text(json.dumps(blueprint_data), encoding="utf-8")

    loaded = load_studio_blueprint(project_path)
    assert loaded["version"] == 1
    assert loaded["project"]["name"] == "my_protolink_mesh"
    assert len(loaded["nodes"]) == len(blueprint_data["nodes"])

    # Test non-json extension
    non_json_path = tmp_path / "blueprint.yaml"
    non_json_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="\\.json"):
        load_studio_blueprint(non_json_path)

    # Test file not found
    with pytest.raises(FileNotFoundError, match="not found"):
        load_studio_blueprint(tmp_path / "non_existent.json")

    # Test path is directory
    with pytest.raises(ValueError, match="\\.json"):
        load_studio_blueprint(tmp_path)

    # Test malformed JSON
    bad_json_path = tmp_path / "bad.json"
    bad_json_path.write_text("{broken json", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_studio_blueprint(bad_json_path)

    # Test invalid blueprint structure
    invalid_schema_path = tmp_path / "invalid_schema.json"
    invalid_schema_path.write_text(json.dumps({"nodes": "not a list"}), encoding="utf-8")
    with pytest.raises(StudioValidationError, match="nodes must be an array"):
        load_studio_blueprint(invalid_schema_path)


def test_studio_catalog_and_default_blueprint_are_versioned_and_runnable():
    catalog = studio_catalog()
    blueprint = validate_studio_blueprint(default_studio_blueprint())
    generated = generate_studio_code(blueprint)

    assert catalog["schema_version"] == blueprint["version"] == 1
    assert catalog["llm_providers"] == list(STUDIO_LLM_PROVIDERS)
    assert catalog["builtin_tools"] == list(STUDIO_BUILTIN_TOOLS)
    assert catalog["flow_types"] == list(STUDIO_FLOW_TYPES)
    assert generated.filename == "protolink_studio_my_protolink_mesh.py"
    assert "card_planner = AgentCard(" in generated.source
    assert "TransportConfig.from_dict" in generated.source
    assert "agents['planner'].start(register=True, background=True)" in generated.source
    assert "flows['main_pipeline'] = Pipeline(" in generated.source
    assert "FLOW_ALIASES" not in generated.source
    assert "BLUEPRINT" not in generated.source
    assert "'nodes':" not in generated.source
    assert "'edges':" not in generated.source
    assert "'x':" not in generated.source
    assert "'y':" not in generated.source
    for canvas_id in ("registry-1", "flow-1", "agent-1", "llm-1", "tool-1"):
        assert canvas_id not in generated.source
    ast.parse(generated.source)
    compile(generated.source, generated.filename, "exec")

    namespace: dict[str, Any] = {"__name__": "studio_test"}
    exec(compile(generated.source, generated.filename, "exec"), namespace)
    namespace["build"]()
    built_agent = namespace["agents"]["planner"]
    namespace["build"]()

    assert list(namespace["registries"]) == ["local_registry"]
    assert list(namespace["agents"]) == ["planner"]
    assert list(namespace["flows"]) == ["main_pipeline"]
    assert namespace["agents"]["planner"] is built_agent
    assert namespace["agents"]["planner"].card.role == "worker"
    assert "calculator" in namespace["agents"]["planner"].tools


def test_studio_generation_is_deterministic_and_source_injection_safe():
    blueprint = default_studio_blueprint()
    hostile = "Planner\n__import__('os').system('should-not-run') #"
    blueprint["project"]["name"] = hostile
    blueprint["nodes"][2]["label"] = hostile
    blueprint["nodes"][2]["config"]["system_prompt"] = hostile

    first = generate_studio_code(blueprint)
    second = generate_studio_code(copy.deepcopy(blueprint))

    assert first.source == second.source
    assert "\n__import__('os').system" not in first.source
    assert repr(hostile) in first.source
    compile(first.source, first.filename, "exec")


def test_studio_generation_is_independent_of_canvas_layout():
    blueprint = default_studio_blueprint()
    baseline = generate_studio_code(blueprint).source
    for index, node in enumerate(blueprint["nodes"]):
        node["x"] = 2784 - index * 119
        node["y"] = 1668 - index * 83

    validated = validate_studio_blueprint(blueprint)
    moved = generate_studio_code(validated).source

    assert validated["nodes"][0]["x"] == 2784
    assert validated["nodes"][0]["y"] == 1668
    assert moved == baseline


def test_studio_generation_allocates_clean_collision_safe_runtime_names():
    blueprint = default_studio_blueprint()
    blueprint["nodes"][2]["config"]["name"] = "class"
    blueprint["nodes"][2]["label"] = "Class"
    blueprint["nodes"][3]["label"] = "Class"

    source = generate_studio_code(blueprint).source

    assert "agents['class_'] = Agent(" in source
    assert "llms['class__2'] = create_llm(" in source
    assert "agent-1" not in source
    assert "llm-1" not in source


def test_studio_generation_never_uses_canvas_ids_as_logical_fallbacks():
    canvas_ids = [f"canvas_sentinel_{kind}" for kind in ("agent", "llm", "tool", "registry", "flow", "module")]
    blueprint = {
        "version": 1,
        "project": {"name": "symbol_labels", "description": ""},
        "nodes": [
            {
                "id": node_id,
                "kind": kind,
                "label": "🧠",
                "x": index * 10,
                "y": index * 10,
                "config": {},
            }
            for index, (kind, node_id) in enumerate(
                zip(("agent", "llm", "tool", "registry", "flow", "module"), canvas_ids, strict=True)
            )
        ],
        "edges": [],
    }

    source = generate_studio_code(blueprint).source

    assert all(node_id not in source for node_id in canvas_ids)
    assert "agents['agent'] = Agent(" in source
    assert "registries['registry'] = Registry(" in source


@pytest.mark.parametrize("project_name", ["os", "signal", "threading", "typing", "protolink"])
def test_studio_filename_cannot_shadow_generated_imports(project_name: str):
    blueprint = default_studio_blueprint()
    blueprint["project"]["name"] = project_name

    generated = generate_studio_code(blueprint)

    assert Path(generated.filename).stem == f"protolink_studio_{project_name}"


@pytest.mark.parametrize("kind", ["agent", "registry", "module"])
def test_studio_rejects_unmapped_constructor_options(kind: str):
    blueprint = default_studio_blueprint()
    if kind == "module":
        blueprint["nodes"].append(
            {
                "id": "module-advanced",
                "kind": "module",
                "label": "Memory",
                "x": 20,
                "y": 20,
                "config": {
                    "module_type": "storage",
                    "implementation": "memory",
                    "name": "memory",
                    "advanced": {"unknown": True},
                },
            }
        )
    else:
        index = 2 if kind == "agent" else 0
        blueprint["nodes"][index]["config"]["advanced"] = {"unknown": True}

    with pytest.raises(StudioValidationError, match="advanced is not supported"):
        generate_studio_code(blueprint)


def test_studio_rejects_unknown_config_fields_instead_of_silently_dropping_them():
    blueprint = default_studio_blueprint()
    blueprint["nodes"][2]["config"]["verbositty"] = 2

    with pytest.raises(StudioValidationError, match="unsupported fields: verbositty"):
        generate_studio_code(blueprint)


def test_studio_generation_emits_agent_start_options_without_canvas_lookups():
    blueprint = default_studio_blueprint()
    blueprint["nodes"][2]["config"]["register"] = False

    source = generate_studio_code(blueprint).source

    assert "agents['planner'].start(register=False, background=True)" in source
    assert "flow = flows.get(flow_name)" in source
    assert "BLUEPRINT" not in source


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data["nodes"].append(copy.deepcopy(data["nodes"][0])), "duplicates"),
        (lambda data: data["edges"][0].update({"to": "missing"}), "missing node"),
        (lambda data: data["edges"][0].update({"from": "llm-1", "to": "tool-1"}), "cannot connect"),
        (lambda data: data["nodes"][2]["config"].update({"transport": "smtp"}), "transport"),
        (lambda data: data["nodes"][3]["config"].update({"provider": "unknown"}), "provider"),
    ],
)
def test_studio_validation_rejects_invalid_topologies(mutate, message: str):
    blueprint = default_studio_blueprint()
    mutate(blueprint)

    with pytest.raises(StudioValidationError, match=message):
        validate_studio_blueprint(blueprint)


def test_studio_validation_rejects_nested_secrets_and_flow_cycles():
    secret_blueprint = default_studio_blueprint()
    secret_blueprint["nodes"][3]["config"]["advanced"] = {"headers": {"Authorization": "Bearer actual-secret"}}

    with pytest.raises(StudioValidationError, match="environment-variable"):
        generate_studio_code(secret_blueprint)

    cycle_blueprint = default_studio_blueprint()
    cycle_blueprint["nodes"].extend(
        [
            {
                "id": "flow-2",
                "kind": "flow",
                "label": "Nested",
                "x": 20,
                "y": 20,
                "config": {"name": "nested", "flow_type": "parallel"},
            }
        ]
    )
    cycle_blueprint["edges"].extend(
        [
            {"id": "edge-cycle-a", "from": "flow-1", "to": "flow-2", "relation": "step"},
            {"id": "edge-cycle-b", "from": "flow-2", "to": "flow-1", "relation": "step"},
        ]
    )

    with pytest.raises(StudioValidationError, match="cycle"):
        validate_studio_blueprint(cycle_blueprint)


@pytest.mark.parametrize("invalid_text", ["nul\x00text", "lone-surrogate-\ud800"])
def test_studio_validation_rejects_source_unsafe_text(invalid_text: str):
    blueprint = default_studio_blueprint()
    blueprint["nodes"][2]["label"] = invalid_text

    with pytest.raises(StudioValidationError, match="invalid Unicode or NUL"):
        generate_studio_code(blueprint)


def test_studio_validation_rejects_provider_mismatches_and_common_secrets():
    blueprint = default_studio_blueprint()
    blueprint["nodes"][3]["config"]["headers"] = {"X-Trace": "enabled"}

    with pytest.raises(StudioValidationError, match="headers is not supported by mock"):
        generate_studio_code(blueprint)

    blueprint = default_studio_blueprint()
    blueprint["nodes"][3]["config"]["advanced"] = {"client_secret": "embedded-value"}

    with pytest.raises(StudioValidationError, match="environment-variable"):
        generate_studio_code(blueprint)

    blueprint = default_studio_blueprint()
    blueprint["nodes"][2]["config"]["advanced"] = {"transport": {"credentials_env": "literal-secret-value"}}

    with pytest.raises(StudioValidationError, match="environment variable name"):
        generate_studio_code(blueprint)


def test_studio_generates_all_flow_types_and_declarative_modules():
    blueprint = default_studio_blueprint()
    blueprint["nodes"].extend(
        [
            {
                "id": "flow-parallel",
                "kind": "flow",
                "label": "Parallel",
                "x": 10,
                "y": 420,
                "config": {"name": "parallel", "flow_type": "parallel"},
            },
            {
                "id": "flow-router",
                "kind": "flow",
                "label": "Router",
                "x": 10,
                "y": 520,
                "config": {"name": "router", "flow_type": "router", "routing_prompt": "Pick planner."},
            },
            {
                "id": "flow-graph",
                "kind": "flow",
                "label": "Graph",
                "x": 10,
                "y": 620,
                "config": {"name": "graph", "flow_type": "graph"},
            },
            {
                "id": "storage-1",
                "kind": "module",
                "label": "Memory",
                "x": 830,
                "y": 190,
                "config": {
                    "module_type": "storage",
                    "implementation": "memory",
                    "name": "memory",
                    "namespace": "planner",
                },
            },
            {
                "id": "policy-1",
                "kind": "module",
                "label": "Policy",
                "x": 830,
                "y": 300,
                "config": {
                    "module_type": "policy",
                    "implementation": "capability",
                    "name": "safe_policy",
                    "rules": {"network.*": "deny"},
                },
            },
        ]
    )
    next_edge = 10
    for flow_id in ("flow-parallel", "flow-router", "flow-graph"):
        blueprint["edges"].append(
            {
                "id": f"edge-{next_edge}",
                "from": flow_id,
                "to": "agent-1",
                "relation": "step",
                "label": "planner",
            }
        )
        next_edge += 1
    blueprint["edges"].extend(
        [
            {"id": "edge-storage", "from": "storage-1", "to": "agent-1", "relation": "storage"},
            {"id": "edge-policy", "from": "policy-1", "to": "agent-1", "relation": "policy"},
        ]
    )

    generated = generate_studio_code(blueprint)

    assert "Parallel(branches=" in generated.source
    assert "Router(routes=" in generated.source
    assert "Graph(registry=" in generated.source
    assert "InMemoryStorage" in generated.source
    assert "CapabilityPolicy" in generated.source
    namespace: dict[str, Any] = {"__name__": "studio_module_test"}
    exec(compile(generated.source, generated.filename, "exec"), namespace)
    namespace["build"]()

    assert set(namespace["modules"]) == {"memory", "safe_policy"}
    assert namespace["agents"]["planner"].storage is namespace["modules"]["memory"]
    assert namespace["agents"]["planner"].action_authorizer.policy is namespace["modules"]["safe_policy"]


def test_studio_uses_safe_defaults_for_blank_module_paths():
    blueprint = default_studio_blueprint()
    modules = [
        ("storage-sqlite", "storage", "sqlite"),
        ("telemetry-local", "telemetry", "local"),
        ("logger-file", "logger", "file"),
        ("run-store", "run_store", "sqlite"),
        ("knowledge-sqlite", "knowledge", "sqlite"),
    ]
    for index, (node_id, module_type, implementation) in enumerate(modules):
        blueprint["nodes"].append(
            {
                "id": node_id,
                "kind": "module",
                "label": node_id.replace("-", " ").title(),
                "x": 860,
                "y": 80 + index * 110,
                "config": {
                    "module_type": module_type,
                    "implementation": implementation,
                    "name": node_id.replace("-", "_"),
                    "path": "",
                },
            }
        )
        blueprint["edges"].append(
            {
                "id": f"edge-{node_id}",
                "from": node_id,
                "to": "agent-1",
                "relation": module_type,
            }
        )

    source = generate_studio_code(blueprint).source

    assert "db_path='storage.db'" in source
    assert "path='traces.jsonl'" in source
    assert "filepath='protolink.log'" in source
    assert "db_path='runs.db'" in source
    assert "path='knowledge.db'" in source
    compile(source, "blank_module_paths.py", "exec")


def test_studio_runtime_can_start_stop_and_reject_stale_stop():
    manager = StudioRuntimeManager()
    try:
        started = manager.start(default_studio_blueprint())
        deadline = time.monotonic() + 5
        status = manager.status()
        while status["running"] and not status["logs"] and time.monotonic() < deadline:
            time.sleep(0.05)
            status = manager.status()

        assert started["running"] is True
        assert status["state"] == "running"
        assert status["run_id"] == started["run_id"]

        with pytest.raises(RuntimeError, match="run changed"):
            manager.stop("stale-run")

        stopped = manager.stop(started["run_id"])
        assert stopped["running"] is False
        assert stopped["state"] == "stopped"
    finally:
        manager.close()


def test_dashboard_renderer_escapes_mixed_case_script_end_tags():
    snapshot = {"studio": {"blueprint": default_studio_blueprint()}}
    snapshot["studio"]["blueprint"]["project"]["description"] = "</ScRiPt><script>alert(1)</script>"

    html = DevtoolsHtmlRenderer().render_dashboard(snapshot)

    assert "</ScRiPt>" not in html
    assert "\\u003c/ScRiPt\\u003e" in html


def test_studio_dashboard_endpoints_generate_run_status_and_stop(monkeypatch, tmp_path: Path):
    created_managers: list[_FakeRuntimeManager] = []

    def manager_factory() -> _FakeRuntimeManager:
        manager = _FakeRuntimeManager()
        created_managers.append(manager)
        return manager

    monkeypatch.setattr("protolink.devtools.server.StudioRuntimeManager", manager_factory)
    server, thread = _start_dashboard_server(monkeypatch, tmp_path / "traces.jsonl")
    base_url = f"http://127.0.0.1:{server.server_port}"
    blueprint = default_studio_blueprint()

    try:
        with urlopen(f"{base_url}/studio", timeout=3) as response:
            html = response.read().decode()
        assert "showView('studio')" in html

        with urlopen(f"{base_url}/api/studio/catalog", timeout=3) as response:
            catalog = json.loads(response.read())
        assert catalog["schema_version"] == 1

        generated = _post_json(base_url, "/api/studio/generate", {"blueprint": blueprint})
        assert generated["language"] == "python"
        assert generated["filename"].endswith(".py")
        assert generated["digest"]

        started = _post_json(base_url, "/api/studio/run", {"blueprint": blueprint}, expected_status=201)
        assert started["running"] is True

        with urlopen(f"{base_url}/api/studio/status", timeout=3) as response:
            status = json.loads(response.read())
            assert response.headers["Cache-Control"] == "no-store"
        assert status["run_id"] == "run-1"

        stopped = _post_json(base_url, "/api/studio/stop", {"run_id": "run-1"})
        assert stopped["state"] == "stopped"

        with pytest.raises(HTTPError) as missing_blueprint:
            _post_json(base_url, "/api/studio/generate", {})
        assert missing_blueprint.value.code == 400
    finally:
        server.shutdown()
        thread.join(timeout=3)

    assert created_managers[0].closed is True


class _FakeRuntimeManager:
    def __init__(self) -> None:
        self.running = False
        self.closed = False

    def start(self, blueprint: Any) -> dict[str, Any]:
        validate_studio_blueprint(blueprint)
        if self.running:
            raise RuntimeError("already running")
        self.running = True
        return self.status()

    def stop(self, run_id: str | None = None) -> dict[str, Any]:
        if run_id != "run-1":
            raise RuntimeError("stale")
        self.running = False
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "state": "running" if self.running else "stopped",
            "running": self.running,
            "run_id": "run-1",
            "project": "test",
            "pid": 123 if self.running else None,
            "started_at": None,
            "exit_code": None,
            "logs": [],
        }

    def close(self) -> None:
        self.closed = True
        self.running = False


def _post_json(base_url: str, path: str, payload: dict[str, Any], *, expected_status: int = 200):
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        assert response.status == expected_status
        return json.loads(response.read())


def _start_dashboard_server(monkeypatch, trace_path: Path):
    import protolink.devtools.server as server_module

    original_server = server_module.ThreadingHTTPServer
    ready = threading.Event()
    created = []

    class CapturingServer(original_server):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

        def serve_forever(self, *args, **kwargs):
            ready.set()
            return super().serve_forever(*args, **kwargs)

    monkeypatch.setattr(server_module, "ThreadingHTTPServer", CapturingServer)
    thread = threading.Thread(
        target=serve_dashboard,
        kwargs={"host": "127.0.0.1", "port": 0, "trace_path": trace_path},
        daemon=True,
    )
    thread.start()
    assert ready.wait(timeout=5)
    return created[0], thread
