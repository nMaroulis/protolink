"""Blueprint validation, code generation, and local execution for Studio.

Studio deliberately stores only declarative JSON.  The generator turns that
data into ordinary, editable Python that uses Protolink's public APIs; it never
evaluates user-provided Python snippets.  The runtime manager is intended for
the loopback-only dashboard endpoints in :mod:`protolink.devtools.server`.
"""

from __future__ import annotations

import hashlib
import json
import keyword
import math
import os
import pprint
import re
import subprocess
import sys
import tempfile
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

STUDIO_SCHEMA_VERSION = 1
STUDIO_NODE_KINDS = ("agent", "llm", "tool", "registry", "flow", "module")
STUDIO_TRANSPORTS = (
    "http",
    "websocket",
    "grpc",
    "runtime",
    "sse",
    "json-rpc",
    "sse-json-rpc",
)
STUDIO_LLM_PROVIDERS = (
    "mock",
    "openai",
    "anthropic",
    "gemini",
    "grok",
    "deepseek",
    "huggingface",
    "ollama",
    "lmstudio",
    "openai-compatible",
    "vllm",
    "llama.cpp-server",
    "llama.cpp-local",
)
STUDIO_BUILTIN_TOOLS = ("calculator", "current_datetime", "fetch_url", "web_search")
STUDIO_FLOW_TYPES = ("pipeline", "parallel", "router", "graph")
STUDIO_MODULE_TYPES = ("storage", "telemetry", "logger", "run_store", "policy", "knowledge", "auth")

_LLM_PROVIDER_KWARGS: dict[str, frozenset[str]] = {
    "mock": frozenset({"default_response", "mock_responses", "model", "model_params", "sequential_responses"}),
    "openai": frozenset({"api_key", "base_url", "model", "model_params"}),
    "anthropic": frozenset({"api_key", "base_url", "model", "model_params"}),
    "gemini": frozenset({"api_key", "base_url", "model", "model_params"}),
    "grok": frozenset({"api_key", "base_url", "model", "model_params", "supports_tool_calling"}),
    "deepseek": frozenset({"api_key", "base_url", "model", "model_params", "supports_tool_calling"}),
    "huggingface": frozenset({"api_key", "model", "model_params"}),
    "ollama": frozenset({"base_url", "headers", "model", "model_params", "supports_tool_calling"}),
    "lmstudio": frozenset({"api_key", "base_url", "headers", "model", "model_params", "supports_tool_calling"}),
    "openai-compatible": frozenset(
        {"api_key", "base_url", "headers", "model", "model_params", "supports_tool_calling"}
    ),
    "vllm": frozenset({"api_key", "base_url", "headers", "model", "model_params", "supports_tool_calling"}),
    "llama.cpp-server": frozenset({"base_url", "headers", "model", "model_params", "supports_tool_calling"}),
    "llama.cpp-local": frozenset({"model", "model_params", "supports_tool_calling"}),
}
_LLM_FACTORY_KWARGS = frozenset({"max_parse_failures", "metrics_enabled", "metrics_profile"})
_AGENT_CAPABILITY_FIELDS = frozenset(
    {
        "streaming",
        "push_notifications",
        "state_transition_history",
        "delegation",
        "has_llm",
        "max_concurrency",
        "message_batching",
        "tool_calling",
        "multi_step_reasoning",
        "timeout_support",
        "rag",
        "code_execution",
    }
)
_TRANSPORT_OPTION_FIELDS: dict[str, frozenset[str]] = {
    "http": frozenset({"timeout", "backend", "validate_schema", "log_level", "access_log"}),
    "sse": frozenset({"timeout", "backend", "validate_schema", "log_level", "access_log"}),
    "json-rpc": frozenset({"timeout", "backend", "validate_schema", "log_level", "access_log"}),
    "sse-json-rpc": frozenset({"timeout", "backend", "validate_schema", "log_level", "access_log"}),
    "websocket": frozenset({"timeout"}),
    "grpc": frozenset(
        {
            "timeout",
            "channel_options",
            "server_options",
            "maximum_concurrent_rpcs",
            "graceful_shutdown_timeout",
            "enable_health",
            "enable_reflection",
        }
    ),
    "runtime": frozenset(),
}
_COMMON_TRANSPORT_CONFIG_FIELDS = frozenset(
    {
        "transport",
        "url",
        "credentials_env",
        "transport_config",
        "transport_options",
        "timeout",
        "backend",
        "validate_schema",
        "log_level",
        "access_log",
    }
)
_NODE_CONFIG_FIELDS: dict[str, frozenset[str]] = {
    "agent": _COMMON_TRANSPORT_CONFIG_FIELDS
    | frozenset(
        {
            "name",
            "description",
            "role",
            "version",
            "system_prompt",
            "skills",
            "state",
            "verbosity",
            "discovery_ttl",
            "registry_heartbeat_interval",
            "expose_chat",
            "override_system_prompt",
            "a2a",
            "register",
            "retrieval",
            "capabilities",
            "security_schemes",
            "interfaces",
            "tags",
            "input_formats",
            "output_formats",
            "advanced",
        }
    ),
    "llm": frozenset(
        {
            "provider",
            "model",
            "api_key_env",
            "base_url",
            "headers",
            "default_response",
            "model_params",
            "temperature",
            "max_tokens",
            "supports_tool_calling",
            "metrics_enabled",
            "max_parse_failures",
            "advanced",
        }
    ),
    "tool": frozenset(
        {
            "implementation",
            "builtin",
            "name",
            "description",
            "input_schema",
            "output_schema",
            "tags",
            "capabilities",
            "args",
            "examples",
            "response_template",
        }
    ),
    "registry": _COMMON_TRANSPORT_CONFIG_FIELDS | frozenset({"verbosity", "entry_ttl_seconds", "advanced"}),
    "flow": frozenset({"name", "flow_type", "routing_prompt", "entry_node"}),
    "module": frozenset(
        {
            "module_type",
            "implementation",
            "name",
            "namespace",
            "path",
            "ttl",
            "table_name",
            "max_traces",
            "capture_payloads",
            "api_key_env",
            "project_name",
            "public_key_env",
            "secret_key_env",
            "host",
            "level",
            "table_prefix",
            "default_effect",
            "rules",
            "description",
            "sources",
            "default_k",
            "context_max_chars",
            "secret_env",
            "algorithm",
            "issuer",
            "audience",
            "leeway_seconds",
            "advanced",
        }
    ),
}

_MAX_BLUEPRINT_BYTES = 1024 * 1024
_MAX_NODES = 200
_MAX_EDGES = 400
_MAX_JSON_DEPTH = 16
_MAX_LOG_LINES = 500
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class StudioValidationError(ValueError):
    """Raised when a Studio blueprint is not safe or structurally valid."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issues))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready validation response."""
        return {"error": "Studio blueprint validation failed", "issues": list(self.issues)}


@dataclass(frozen=True, slots=True)
class StudioCode:
    """Generated Python and its normalized source blueprint."""

    source: str
    filename: str
    blueprint: dict[str, Any]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return the browser-facing generation payload."""
        return {
            "code": self.source,
            "filename": self.filename,
            "blueprint": self.blueprint,
            "warnings": list(self.warnings),
        }


def studio_catalog() -> dict[str, Any]:
    """Return stable choices used by the dependency-free Studio frontend."""
    return {
        "schema_version": STUDIO_SCHEMA_VERSION,
        "node_kinds": list(STUDIO_NODE_KINDS),
        "transports": list(STUDIO_TRANSPORTS),
        "llm_providers": list(STUDIO_LLM_PROVIDERS),
        "builtin_tools": list(STUDIO_BUILTIN_TOOLS),
        "flow_types": list(STUDIO_FLOW_TYPES),
        "module_types": list(STUDIO_MODULE_TYPES),
        "module_implementations": {
            "storage": ["memory", "sqlite"],
            "telemetry": ["local", "langsmith", "langfuse"],
            "logger": ["console", "file", "quiet"],
            "run_store": ["sqlite"],
            "policy": ["capability"],
            "knowledge": ["memory", "sqlite"],
            "auth": ["bearer"],
        },
    }


def default_studio_blueprint() -> dict[str, Any]:
    """Return an offline-safe starter topology that can run immediately."""
    return {
        "version": STUDIO_SCHEMA_VERSION,
        "project": {
            "name": "my_protolink_mesh",
            "description": "A visual Protolink agent mesh.",
        },
        "nodes": [
            {
                "id": "registry-1",
                "kind": "registry",
                "label": "Local Registry",
                "x": 1117,
                "y": 733,
                "config": {
                    "url": "runtime://studio-registry",
                    "transport": "runtime",
                    "verbosity": 1,
                },
            },
            {
                "id": "flow-1",
                "kind": "flow",
                "label": "Main Pipeline",
                "x": 1117,
                "y": 955,
                "config": {"name": "main_pipeline", "flow_type": "pipeline"},
            },
            {
                "id": "agent-1",
                "kind": "agent",
                "label": "Planner",
                "x": 1401,
                "y": 851,
                "config": {
                    "name": "planner",
                    "description": "Plans and completes user requests.",
                    "url": "runtime://planner",
                    "transport": "runtime",
                    "role": "worker",
                    "system_prompt": "Be concise, practical, and use tools when they help.",
                    "skills": "auto",
                    "state": ["conversation"],
                    "verbosity": 1,
                    "expose_chat": True,
                    "register": True,
                },
            },
            {
                "id": "llm-1",
                "kind": "llm",
                "label": "Mock LLM",
                "x": 1687,
                "y": 749,
                "config": {
                    "provider": "mock",
                    "model": "mock-gpt",
                    "default_response": "Studio mesh is running.",
                    "model_params": {"temperature": 0.2},
                },
            },
            {
                "id": "tool-1",
                "kind": "tool",
                "label": "Calculator",
                "x": 1687,
                "y": 947,
                "config": {"implementation": "builtin", "builtin": "calculator"},
            },
        ],
        "edges": [
            {"id": "edge-1", "from": "registry-1", "to": "agent-1", "relation": "registry"},
            {"id": "edge-2", "from": "llm-1", "to": "agent-1", "relation": "llm"},
            {"id": "edge-3", "from": "tool-1", "to": "agent-1", "relation": "tool"},
            {"id": "edge-4", "from": "flow-1", "to": "agent-1", "relation": "step", "order": 1},
            {"id": "edge-5", "from": "registry-1", "to": "flow-1", "relation": "registry"},
        ],
    }


def validate_studio_blueprint(value: Any) -> dict[str, Any]:
    """Validate and normalize a declarative Studio blueprint.

    Validation is intentionally strict at the process boundary.  Every emitted
    constructor argument maps to a public Protolink API; only LLM providers have
    a validated ``advanced`` option mapping.  Values must be bounded JSON data,
    and secrets must be referenced by environment-variable name rather than
    embedded in the blueprint.
    """
    issues: list[str] = []
    if not isinstance(value, dict):
        raise StudioValidationError(["blueprint must be a JSON object"])

    try:
        encoded = json.dumps(value, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise StudioValidationError([f"blueprint must contain finite JSON data: {exc}"]) from exc
    if len(encoded) > _MAX_BLUEPRINT_BYTES:
        issues.append(f"blueprint exceeds the {_MAX_BLUEPRINT_BYTES}-byte limit")
    _validate_json_value(value, "blueprint", issues)
    _find_embedded_secrets(value, "blueprint", issues)

    raw_version = value.get("version", STUDIO_SCHEMA_VERSION)
    if raw_version != STUDIO_SCHEMA_VERSION:
        issues.append(f"version must be {STUDIO_SCHEMA_VERSION}")

    raw_project = value.get("project") or {}
    if not isinstance(raw_project, dict):
        issues.append("project must be an object")
        raw_project = {}
    project_name = _clean_text(raw_project.get("name"), "my_protolink_mesh", limit=80)
    project_description = _clean_text(raw_project.get("description"), "A Protolink Studio project.", limit=500)
    if not _python_slug(project_name):
        issues.append("project.name must contain at least one letter or number")

    raw_nodes = value.get("nodes", [])
    if not isinstance(raw_nodes, list):
        issues.append("nodes must be an array")
        raw_nodes = []
    if len(raw_nodes) > _MAX_NODES:
        issues.append(f"nodes contains more than {_MAX_NODES} items")

    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for index, raw_node in enumerate(raw_nodes[:_MAX_NODES]):
        path = f"nodes[{index}]"
        if not isinstance(raw_node, dict):
            issues.append(f"{path} must be an object")
            continue
        node_id = str(raw_node.get("id") or "").strip()
        if not _NODE_ID_RE.fullmatch(node_id):
            issues.append(f"{path}.id must match {_NODE_ID_RE.pattern}")
            continue
        if node_id in node_ids:
            issues.append(f"{path}.id duplicates {node_id!r}")
            continue
        node_ids.add(node_id)

        kind = str(raw_node.get("kind") or "").strip().lower()
        if kind not in STUDIO_NODE_KINDS:
            issues.append(f"{path}.kind must be one of {', '.join(STUDIO_NODE_KINDS)}")
            continue
        label = _clean_text(raw_node.get("label"), kind.title(), limit=100)
        x = _finite_coordinate(raw_node.get("x", 80), f"{path}.x", issues)
        y = _finite_coordinate(raw_node.get("y", 80), f"{path}.y", issues)
        raw_config = raw_node.get("config") or {}
        if not isinstance(raw_config, dict):
            issues.append(f"{path}.config must be an object")
            raw_config = {}
        config = {**_node_defaults(kind, label, node_id), **raw_config}
        _validate_node_config(kind, config, path, issues)
        nodes.append({"id": node_id, "kind": kind, "label": label, "x": x, "y": y, "config": config})

    raw_edges = value.get("edges", [])
    if not isinstance(raw_edges, list):
        issues.append("edges must be an array")
        raw_edges = []
    if len(raw_edges) > _MAX_EDGES:
        issues.append(f"edges contains more than {_MAX_EDGES} items")

    edges: list[dict[str, Any]] = []
    edge_ids: set[str] = set()
    edge_pairs: set[tuple[str, str, str]] = set()
    for index, raw_edge in enumerate(raw_edges[:_MAX_EDGES]):
        path = f"edges[{index}]"
        if not isinstance(raw_edge, dict):
            issues.append(f"{path} must be an object")
            continue
        edge_id = str(raw_edge.get("id") or f"edge-{index + 1}").strip()
        if not _NODE_ID_RE.fullmatch(edge_id):
            issues.append(f"{path}.id must match {_NODE_ID_RE.pattern}")
            continue
        if edge_id in edge_ids:
            issues.append(f"{path}.id duplicates {edge_id!r}")
            continue
        edge_ids.add(edge_id)
        source = str(raw_edge.get("from") or "").strip()
        target = str(raw_edge.get("to") or "").strip()
        if source not in node_ids:
            issues.append(f"{path}.from references missing node {source!r}")
        if target not in node_ids:
            issues.append(f"{path}.to references missing node {target!r}")
        if source and source == target:
            issues.append(f"{path} cannot connect a node to itself")
        if source in node_ids and target in node_ids:
            source_node = next(node for node in nodes if node["id"] == source)
            target_node = next(node for node in nodes if node["id"] == target)
            if not _connection_allowed(source_node, target_node):
                issues.append(f"{path} cannot connect {source_node['kind']} to {target_node['kind']}")
        relation = _clean_text(raw_edge.get("relation"), "auto", limit=32).lower().replace(" ", "_")
        label = _clean_text(raw_edge.get("label"), "", limit=80)
        raw_order = raw_edge.get("order", index + 1)
        try:
            order = int(raw_order)
        except (TypeError, ValueError, OverflowError):
            issues.append(f"{path}.order must be an integer")
            order = index + 1
        pair = (source, target, relation)
        if pair in edge_pairs:
            issues.append(f"{path} duplicates the {source!r} -> {target!r} {relation!r} connection")
        edge_pairs.add(pair)
        edges.append(
            {
                "id": edge_id,
                "from": source,
                "to": target,
                "relation": relation,
                "label": label,
                "order": order,
            }
        )

    if not issues:
        node_map = {node["id"]: node for node in nodes}
        try:
            _order_flow_nodes([node for node in nodes if node["kind"] == "flow"], node_map, edges)
        except StudioValidationError as exc:
            issues.extend(exc.issues)

    if issues:
        raise StudioValidationError(issues[:100])
    return {
        "version": STUDIO_SCHEMA_VERSION,
        "project": {"name": project_name, "description": project_description},
        "nodes": nodes,
        "edges": edges,
    }


def load_studio_blueprint(path: str | Path) -> dict[str, Any]:
    """Load, parse, and validate a Studio blueprint from a JSON file.

    Args:
        path: Path to the Studio blueprint JSON file.

    Returns:
        The validated and normalized blueprint dictionary.

    Raises:
        FileNotFoundError: If the blueprint file does not exist.
        ValueError: If the file is not a .json file, path is not a file,
            JSON is malformed, or the blueprint violates schema/safety constraints.
    """
    file_path = Path(path).expanduser()
    if file_path.suffix.lower() != ".json":
        raise ValueError(f"Studio blueprint file must be a .json file: {file_path}")
    if not file_path.exists():
        raise FileNotFoundError(f"Studio blueprint file not found: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Studio blueprint path is not a file: {file_path}")
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Failed to read Studio blueprint file: {exc}") from exc
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid JSON in Studio blueprint file: {exc}") from exc
    return validate_studio_blueprint(data)


def generate_studio_code(value: Any) -> StudioCode:
    """Generate a readable, directly runnable module using public Protolink APIs."""
    blueprint = validate_studio_blueprint(value)
    warnings = _blueprint_warnings(blueprint)
    project_slug = _python_slug(blueprint["project"]["name"]) or "protolink_studio"
    nodes = blueprint["nodes"]
    edges = blueprint["edges"]
    node_map = {node["id"]: node for node in nodes}
    runtime_names = _runtime_names(nodes)
    registry_nodes = [node for node in nodes if node["kind"] == "registry"]
    module_nodes = [node for node in nodes if node["kind"] == "module"]
    llm_nodes = [node for node in nodes if node["kind"] == "llm"]
    tool_nodes = [node for node in nodes if node["kind"] == "tool"]
    agent_nodes = [node for node in nodes if node["kind"] == "agent"]
    flow_nodes = [node for node in nodes if node["kind"] == "flow"]

    module_pairs = {(node["config"]["module_type"], node["config"]["implementation"]) for node in module_nodes}
    flow_class_names = {
        "pipeline": "Pipeline",
        "parallel": "Parallel",
        "router": "Router",
        "graph": "Graph",
    }
    flow_imports = [
        flow_class_names[flow_type]
        for flow_type in STUDIO_FLOW_TYPES
        if any(node["config"]["flow_type"] == flow_type for node in flow_nodes)
    ]
    logger_imports = [
        class_name
        for implementation, class_name in (
            ("console", "ConsoleLogger"),
            ("file", "FileLogger"),
            ("quiet", "QuietLogger"),
        )
        if ("logger", implementation) in module_pairs
    ]
    storage_imports = [
        class_name
        for pair, class_name in (
            (("storage", "memory"), "InMemoryStorage"),
            (("storage", "sqlite"), "SQLiteStorage"),
            (("run_store", "sqlite"), "SQLiteRunStore"),
        )
        if pair in module_pairs
    ]
    telemetry_imports = [
        class_name
        for implementation, class_name in (
            ("local", "LocalTraceTelemetry"),
            ("langsmith", "LangSmithTelemetry"),
            ("langfuse", "LangfuseTelemetry"),
        )
        if ("telemetry", implementation) in module_pairs
    ]
    if sum(node["config"]["module_type"] == "telemetry" for node in module_nodes) > 1:
        telemetry_imports.append("MultiTelemetry")
    builtin_imports = [
        name
        for name in STUDIO_BUILTIN_TOOLS
        if any(
            node["config"]["implementation"] == "builtin" and node["config"]["builtin"] == name for node in tool_nodes
        )
    ]
    uses_environment = any(
        key.endswith("_env") and bool(item) for node in nodes for key, item in node["config"].items()
    )
    uses_transport = bool(agent_nodes or registry_nodes)

    protolink_imports: list[str] = []
    if agent_nodes:
        protolink_imports.append("from protolink.agents import Agent")
    if any(node["config"]["module_type"] == "policy" for node in module_nodes):
        protolink_imports.append("from protolink.core.policy import CapabilityPolicy")
    if registry_nodes:
        protolink_imports.append("from protolink.discovery import Registry")
    if flow_imports:
        protolink_imports.append(f"from protolink.flows import {', '.join(flow_imports)}")
    if llm_nodes:
        protolink_imports.append("from protolink.llms import create_llm")
    if logger_imports:
        protolink_imports.append(f"from protolink.logging import {', '.join(logger_imports)}")
    model_imports = [name for name, present in (("AgentCard", agent_nodes), ("Task", flow_nodes)) if present]
    if model_imports:
        protolink_imports.append(f"from protolink.models import {', '.join(model_imports)}")
    if any(node["config"]["module_type"] == "knowledge" for node in module_nodes):
        protolink_imports.append("from protolink.rag import create_knowledge")
    if any(node["config"]["module_type"] == "auth" for node in module_nodes):
        protolink_imports.append("from protolink.security import BearerTokenAuth")
    if storage_imports:
        protolink_imports.append(f"from protolink.storage import {', '.join(storage_imports)}")
    if telemetry_imports:
        protolink_imports.append(f"from protolink.telemetry import {', '.join(telemetry_imports)}")
    if any(node["config"]["implementation"] == "custom" for node in tool_nodes):
        protolink_imports.append("from protolink.tools import Tool")
    if builtin_imports:
        protolink_imports.append(f"from protolink.tools.builtins import {', '.join(builtin_imports)}")
    if uses_transport:
        protolink_imports.append("from protolink.transport import TransportConfig, get_transport")

    lines: list[str] = [
        '"""Runnable Protolink topology generated by Protolink Studio."""',
        "",
        "from __future__ import annotations",
        "",
        *(["import os"] if uses_environment else []),
        "import signal",
        "import threading",
        "from typing import Any",
        "",
        *protolink_imports,
        "",
    ]
    collection_specs = (
        ("registries", "Registry", registry_nodes),
        ("llms", "Any", llm_nodes),
        ("tools", "Any", tool_nodes),
        ("modules", "Any", module_nodes),
        ("agents", "Agent", agent_nodes),
        ("flows", "Any", flow_nodes),
    )
    for collection, item_type, collection_nodes in collection_specs:
        if collection_nodes:
            lines.append(f"{collection}: dict[str, {item_type}] = {{}}")
    if any(spec[2] for spec in collection_specs):
        lines.append("")
    lines.extend(
        [
            "_built = False",
            "_shutdown = threading.Event()",
            "",
            "",
            "def build() -> None:",
            '    """Construct the configured Protolink objects once."""',
            "    global _built",
            "    if _built:",
            "        return",
        ]
    )
    for collection, _item_type, collection_nodes in collection_specs:
        if collection_nodes:
            lines.append(f"    {collection}.clear()")
    if not nodes:
        lines.append("    pass")

    for node in module_nodes:
        _emit_module(lines, node, runtime_names)
    for node in registry_nodes:
        _emit_registry(lines, node, node_map, edges, runtime_names)
    for node in llm_nodes:
        _emit_llm(lines, node, runtime_names)
    for node in tool_nodes:
        _emit_tool(lines, node, runtime_names)
    for node in agent_nodes:
        _emit_agent(lines, node, node_map, edges, runtime_names)
    for node in _order_flow_nodes(flow_nodes, node_map, edges):
        _emit_flow(lines, node, node_map, edges, runtime_names)

    lines.append("    _built = True")
    if flow_nodes:
        lines.extend(
            [
                "",
                "",
                "async def run_flow(flow_name: str, prompt: str) -> Task:",
                '    """Execute a configured flow by name."""',
                "    build()",
                "    flow = flows.get(flow_name)",
                "    if flow is None:",
                "        raise KeyError(f'Unknown flow: {flow_name}')",
                "    return await flow.execute(Task.create_infer(prompt=prompt))",
            ]
        )

    lines.extend(
        [
            "",
            "",
            "def start() -> None:",
            '    """Start configured registries and agents in the background."""',
            "    build()",
        ]
    )
    if registry_nodes:
        lines.extend(["    for registry in registries.values():", "        registry.start(background=True)"])
    for node in agent_nodes:
        name = runtime_names[node["id"]]
        register = bool(node["config"].get("register", True))
        lines.append(f"    agents[{_literal(name)}].start(register={register!r}, background=True)")
    lines.append(
        "    print(" + _literal(f"Protolink project {blueprint['project']['name']} is running.") + ", flush=True)"
    )
    if agent_nodes:
        lines.extend(
            [
                "    for agent_name, agent in agents.items():",
                "        print(f'  agent {agent_name}: {agent.card.url}', flush=True)",
            ]
        )

    lines.extend(
        [
            "",
            "",
            "def stop() -> None:",
            '    """Stop agents before registries so unregister calls can complete."""',
        ]
    )
    if agent_nodes:
        lines.extend(["    for agent in reversed(list(agents.values())):", "        agent.stop()"])
    if registry_nodes:
        lines.extend(["    for registry in reversed(list(registries.values())):", "        registry.stop()"])
    if not agent_nodes and not registry_nodes:
        lines.append("    pass")
    lines.extend(
        [
            "",
            "",
            "def _request_shutdown(_signum: int, _frame: Any) -> None:",
            "    _shutdown.set()",
            "",
            "",
            "def main() -> None:",
            '    """Run the topology until SIGINT or SIGTERM."""',
            "    signal.signal(signal.SIGINT, _request_shutdown)",
            "    signal.signal(signal.SIGTERM, _request_shutdown)",
            "    try:",
            "        start()",
            "        while not _shutdown.wait(0.25):",
            "            pass",
            "    finally:",
            "        stop()",
            "        print('Protolink project stopped.', flush=True)",
            "",
            "",
            'if __name__ == "__main__":',
            "    main()",
            "",
        ]
    )
    source = "\n".join(lines)
    filename = f"protolink_studio_{project_slug}.py"
    compile(source, filename, "exec")
    return StudioCode(source=source, filename=filename, blueprint=blueprint, warnings=tuple(warnings))


class StudioRuntimeManager:
    """Own at most one generated Studio subprocess for a dashboard server."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        self._reader: threading.Thread | None = None
        self._logs: deque[str] = deque(maxlen=_MAX_LOG_LINES)
        self._run_id: str | None = None
        self._project: str | None = None
        self._started_at: str | None = None
        self._last_exit_code: int | None = None

    def start(self, blueprint: Any) -> dict[str, Any]:
        """Generate and start a topology, rejecting concurrent Studio runs."""
        generated = generate_studio_code(blueprint)
        with self._lock:
            self._refresh_locked()
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("A Studio project is already running; stop it before starting another")
            self._cleanup_files_locked()
            temporary_directory = tempfile.TemporaryDirectory(prefix="protolink-studio-")
            script_path = Path(temporary_directory.name) / generated.filename
            script_path.write_text(generated.source, encoding="utf-8")
            environment = os.environ.copy()
            python_paths = [entry for entry in sys.path if entry]
            existing_python_path = environment.get("PYTHONPATH")
            if existing_python_path:
                python_paths.append(existing_python_path)
            environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(python_paths))
            environment["PYTHONUNBUFFERED"] = "1"
            try:
                process = subprocess.Popen(
                    [sys.executable, str(script_path)],
                    cwd=os.getcwd(),
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
            except Exception:
                temporary_directory.cleanup()
                raise
            run_id = uuid.uuid4().hex
            self._temporary_directory = temporary_directory
            self._process = process
            self._logs.clear()
            self._run_id = run_id
            self._project = generated.blueprint["project"]["name"]
            self._started_at = datetime.now(UTC).isoformat()
            self._last_exit_code = None
            self._reader = threading.Thread(
                target=self._read_output,
                args=(process, run_id),
                daemon=True,
            )
            self._reader.start()
            status = self._status_locked()
            status["warnings"] = list(generated.warnings)
            return status

    def stop(self, run_id: str | None = None) -> dict[str, Any]:
        """Gracefully terminate the active generated process, if any.

        ``run_id`` protects a newly started topology from a delayed Stop request
        that belonged to an older browser action.
        """
        with self._lock:
            if run_id is not None and self._run_id is not None and run_id != self._run_id:
                raise RuntimeError("Studio run changed before the stop request completed")
            process = self._process
            if process is None:
                return self._status_locked()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            self._last_exit_code = process.poll()
            self._process = None
            self._cleanup_files_locked()
            return self._status_locked()

    def status(self) -> dict[str, Any]:
        """Return bounded lifecycle state and recent combined output."""
        with self._lock:
            self._refresh_locked()
            return self._status_locked()

    def close(self) -> None:
        """Stop the child process during dashboard shutdown."""
        self.stop()

    def _read_output(self, process: subprocess.Popen[str], run_id: str) -> None:
        """Capture bounded output without leaking lines between successive runs."""
        stream = process.stdout
        if stream is None:
            return
        try:
            while line := stream.readline(4001):
                clean = _ANSI_ESCAPE_RE.sub("", line.rstrip("\r\n"))
                clean = "".join(character for character in clean if character == "\t" or ord(character) >= 32)
                with self._lock:
                    if self._run_id == run_id:
                        self._logs.append(clean[:4000])
        finally:
            stream.close()

    def _refresh_locked(self) -> None:
        if self._process is not None and self._process.poll() is not None:
            self._last_exit_code = self._process.returncode
            self._process = None
            self._cleanup_files_locked()

    def _cleanup_files_locked(self) -> None:
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
            self._temporary_directory = None

    def _status_locked(self) -> dict[str, Any]:
        running = self._process is not None and self._process.poll() is None
        if running:
            state = "running"
        elif self._run_id is None:
            state = "idle"
        elif self._last_exit_code in {None, 0, -15}:
            state = "stopped"
        else:
            state = "error"
        return {
            "state": state,
            "running": running,
            "run_id": self._run_id,
            "project": self._project,
            "pid": self._process.pid if running and self._process is not None else None,
            "started_at": self._started_at,
            "exit_code": None if running else self._last_exit_code,
            "logs": list(self._logs),
        }


def _node_defaults(kind: str, label: str, _node_id: str) -> dict[str, Any]:
    slug = _python_slug(label) or kind
    if kind == "agent":
        return {
            "name": slug,
            "description": f"{label} agent.",
            "url": f"runtime://{slug}",
            "transport": "runtime",
            "role": "worker",
            "version": "1.0.0",
            "system_prompt": "",
            "skills": "auto",
            "state": [],
            "verbosity": 1,
            "discovery_ttl": 0,
            "registry_heartbeat_interval": None,
            "expose_chat": True,
            "override_system_prompt": False,
            "a2a": False,
            "register": True,
            "retrieval": "auto",
            "capabilities": {},
            "tags": [],
            "input_formats": ["text/plain"],
            "output_formats": ["text/plain"],
            "transport_config": {},
            "transport_options": {},
        }
    if kind == "llm":
        return {
            "provider": "mock",
            "model": "mock-gpt",
            "api_key_env": "",
            "base_url": "",
            "model_params": {},
            "supports_tool_calling": False,
            "metrics_enabled": True,
            "advanced": {},
        }
    if kind == "tool":
        return {
            "implementation": "custom",
            "builtin": "calculator",
            "name": slug,
            "description": f"{label} tool.",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": True},
            "output_schema": {"type": "object"},
            "tags": [],
            "capabilities": [],
            "args": {},
            "examples": [],
            "response_template": f"{label} completed.",
        }
    if kind == "registry":
        return {
            "url": f"runtime://{slug}",
            "transport": "runtime",
            "verbosity": 1,
            "entry_ttl_seconds": None,
            "transport_config": {},
            "transport_options": {},
        }
    if kind == "flow":
        return {"name": slug, "flow_type": "pipeline", "routing_prompt": "Choose the best route."}
    return {
        "module_type": "storage",
        "implementation": "memory",
        "name": slug,
        "namespace": slug,
    }


def _validate_node_config(kind: str, config: dict[str, Any], path: str, issues: list[str]) -> None:
    unsupported_fields = sorted(set(config).difference(_NODE_CONFIG_FIELDS[kind]))
    if unsupported_fields:
        issues.append(f"{path}.config contains unsupported fields: {', '.join(unsupported_fields)}")
    for mapping_name in ("advanced", "transport_config", "transport_options"):
        if mapping_name in config and not isinstance(config[mapping_name], dict):
            issues.append(f"{path}.config.{mapping_name} must be an object")
    for secret_name in ("api_key", "secret", "password", "token", "credentials"):
        if config.get(secret_name):
            issues.append(
                f"{path}.config.{secret_name} must not contain a secret; use the matching *_env field instead"
            )
    advanced = config.get("advanced")
    if kind in {"agent", "registry", "module"} and isinstance(advanced, dict) and advanced:
        issues.append(
            f"{path}.config.advanced is not supported for {kind} nodes; "
            "use the explicit Studio fields for public constructor arguments"
        )
    if kind in {"agent", "registry"}:
        transport = str(config.get("transport") or "").lower()
        if transport not in STUDIO_TRANSPORTS:
            issues.append(f"{path}.config.transport must be one of {', '.join(STUDIO_TRANSPORTS)}")
        _validate_transport_url(config.get("url"), transport, f"{path}.config.url", issues)
        _validate_transport_settings(config, transport, path, issues)
    if kind == "agent":
        if not str(config.get("name") or "").strip():
            issues.append(f"{path}.config.name is required")
        if not str(config.get("description") or "").strip():
            issues.append(f"{path}.config.description is required")
        if config.get("skills") not in {"auto", "fixed"}:
            issues.append(f"{path}.config.skills must be 'auto' or 'fixed'")
        if config.get("retrieval") not in {"auto", "always", "required"}:
            issues.append(f"{path}.config.retrieval must be auto, always, or required")
        if config.get("role") not in {"gateway", "interface", "observer", "orchestrator", "worker"}:
            issues.append(f"{path}.config.role is not a supported agent role")
        if config.get("a2a") and config.get("transport") != "http":
            issues.append(f"{path}.config.a2a requires the http transport")
        for key in ("capabilities", "security_schemes"):
            if key in config and not isinstance(config[key], dict):
                issues.append(f"{path}.config.{key} must be an object")
        for key in ("state", "tags", "input_formats", "output_formats", "interfaces"):
            if key in config and not isinstance(config[key], list):
                issues.append(f"{path}.config.{key} must be an array")
        capabilities = config.get("capabilities")
        if isinstance(capabilities, dict):
            unsupported = sorted(set(capabilities).difference(_AGENT_CAPABILITY_FIELDS))
            if unsupported:
                issues.append(f"{path}.config.capabilities contains unsupported fields: {', '.join(unsupported)}")
            for name, value in capabilities.items():
                if name == "max_concurrency":
                    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                        issues.append(f"{path}.config.capabilities.max_concurrency must be an integer of at least 1")
                elif name in _AGENT_CAPABILITY_FIELDS and not isinstance(value, bool):
                    issues.append(f"{path}.config.capabilities.{name} must be a boolean")
        interfaces = config.get("interfaces")
        if isinstance(interfaces, list):
            _validate_agent_interfaces(interfaces, path, issues)
        state = config.get("state")
        if isinstance(state, list) and any(item not in {"conversation", "tools", "task", "flow"} for item in state):
            issues.append(f"{path}.config.state contains an unsupported state module")
        _validate_integer(config, "verbosity", path, issues, minimum=0, maximum=2)
        _validate_integer(config, "discovery_ttl", path, issues, minimum=0)
        _validate_number(config, "registry_heartbeat_interval", path, issues, minimum=0.001, optional=True)
        for key in ("a2a", "expose_chat", "override_system_prompt", "register"):
            _validate_boolean(config, key, path, issues)
    elif kind == "llm":
        provider = str(config.get("provider") or "").lower()
        if provider not in STUDIO_LLM_PROVIDERS:
            issues.append(f"{path}.config.provider must be a supported LLM provider")
        allowed_options = _LLM_PROVIDER_KWARGS.get(provider, frozenset()) | _LLM_FACTORY_KWARGS
        if provider in {"vllm", "llama.cpp-local"} and not str(config.get("model") or "").strip():
            issues.append(f"{path}.config.model is required for {provider}")
        for key in ("model_params", "headers"):
            if key in config and not isinstance(config[key], dict):
                issues.append(f"{path}.config.{key} must be an object")
        _validate_number(config, "temperature", path, issues, optional=True)
        _validate_integer(config, "max_tokens", path, issues, minimum=1, optional=True)
        _validate_integer(config, "max_parse_failures", path, issues, minimum=0, optional=True)
        for key in ("metrics_enabled", "supports_tool_calling"):
            _validate_boolean(config, key, path, issues)
        if config.get("api_key_env") and "api_key" not in allowed_options:
            issues.append(f"{path}.config.api_key_env is not supported by {provider}")
        if config.get("base_url") and "base_url" not in allowed_options:
            issues.append(f"{path}.config.base_url is not supported by {provider}")
        if config.get("headers") and "headers" not in allowed_options:
            issues.append(f"{path}.config.headers is not supported by {provider}")
        if config.get("supports_tool_calling") and "supports_tool_calling" not in allowed_options:
            issues.append(f"{path}.config.supports_tool_calling is not configurable for {provider}")
        advanced = config.get("advanced")
        if isinstance(advanced, dict):
            unsupported = sorted(set(advanced).difference(allowed_options))
            if unsupported:
                issues.append(
                    f"{path}.config.advanced contains unsupported {provider} options: {', '.join(unsupported)}"
                )
    elif kind == "tool":
        implementation = config.get("implementation")
        if implementation not in {"builtin", "custom"}:
            issues.append(f"{path}.config.implementation must be builtin or custom")
        if implementation == "builtin" and config.get("builtin") not in STUDIO_BUILTIN_TOOLS:
            issues.append(f"{path}.config.builtin must be a public Protolink built-in tool")
        for key in ("input_schema", "output_schema"):
            if not isinstance(config.get(key), dict):
                issues.append(f"{path}.config.{key} must be an object")
        for key in ("tags", "capabilities"):
            if key in config and not isinstance(config[key], list):
                issues.append(f"{path}.config.{key} must be an array")
        if "args" in config and not isinstance(config["args"], dict):
            issues.append(f"{path}.config.args must be an object")
        if "examples" in config and not isinstance(config["examples"], list):
            issues.append(f"{path}.config.examples must be an array")
    elif kind == "flow":
        if config.get("flow_type") not in STUDIO_FLOW_TYPES:
            issues.append(f"{path}.config.flow_type must be one of {', '.join(STUDIO_FLOW_TYPES)}")
        if not str(config.get("name") or "").strip():
            issues.append(f"{path}.config.name is required")
    elif kind == "module":
        module_type = config.get("module_type")
        if module_type not in STUDIO_MODULE_TYPES:
            issues.append(f"{path}.config.module_type must be one of {', '.join(STUDIO_MODULE_TYPES)}")
        implementations = studio_catalog()["module_implementations"].get(module_type, [])
        if config.get("implementation") not in implementations:
            issues.append(f"{path}.config.implementation is not available for {module_type}")
        if module_type == "auth" and not config.get("secret_env"):
            issues.append(f"{path}.config.secret_env is required for bearer authentication")
        if module_type == "storage":
            _validate_integer(config, "ttl", path, issues, minimum=1, optional=True)
        elif module_type == "telemetry" and config.get("implementation") == "local":
            _validate_integer(config, "max_traces", path, issues, minimum=1, optional=True)
            _validate_boolean(config, "capture_payloads", path, issues)
        elif module_type == "knowledge":
            _validate_integer(config, "default_k", path, issues, minimum=1, maximum=50, optional=True)
            _validate_integer(config, "context_max_chars", path, issues, minimum=1, optional=True)
        elif module_type == "auth":
            _validate_integer(config, "leeway_seconds", path, issues, minimum=0, optional=True)
        elif module_type == "policy" and "rules" in config and not isinstance(config["rules"], dict):
            issues.append(f"{path}.config.rules must be an object")

    if kind == "registry":
        _validate_integer(config, "verbosity", path, issues, minimum=0, maximum=2)
        _validate_number(config, "entry_ttl_seconds", path, issues, minimum=0.001, optional=True)


def _validate_transport_url(value: Any, transport: str, path: str, issues: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        issues.append(f"{path} is required")
        return
    if len(value) > 2048 or any(character.isspace() or ord(character) < 32 for character in value):
        issues.append(f"{path} is invalid")
        return
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        issues.append(f"{path} is invalid")
        return
    schemes = {
        "http": {"http", "https"},
        "sse": {"http", "https"},
        "json-rpc": {"http", "https"},
        "sse-json-rpc": {"http", "https"},
        "websocket": {"ws", "wss"},
        "grpc": {"grpc", "grpcs"},
        "runtime": {"runtime"},
    }.get(transport, set())
    if parsed.scheme not in schemes or not parsed.hostname:
        issues.append(f"{path} must use a {transport} URL")
    if parsed.scheme in {"https", "wss", "grpcs"}:
        issues.append(f"{path} uses TLS, which requires a concrete TLSConfig that Studio does not expose yet")
    if parsed.username is not None or parsed.password is not None:
        issues.append(f"{path} must not contain credentials")


def _validate_transport_settings(
    config: dict[str, Any],
    transport: str,
    path: str,
    issues: list[str],
) -> None:
    """Validate transport data against the public factory and config APIs."""
    raw_options = config.get("transport_options")
    if isinstance(raw_options, dict):
        raw_options = _transport_options(config)
        allowed = _TRANSPORT_OPTION_FIELDS.get(transport, frozenset())
        unsupported = sorted(set(raw_options).difference(allowed))
        if unsupported:
            issues.append(
                f"{path}.config.transport_options contains unsupported {transport} options: {', '.join(unsupported)}"
            )
        timeout = raw_options.get("timeout")
        if timeout is not None and (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not math.isfinite(float(timeout))
            or timeout <= 0
        ):
            issues.append(f"{path}.config.transport_options.timeout must be greater than zero")
        if "backend" in raw_options and raw_options["backend"] not in {"starlette", "fastapi"}:
            issues.append(f"{path}.config.transport_options.backend must be starlette or fastapi")
        if "log_level" in raw_options and raw_options["log_level"] not in {
            "critical",
            "error",
            "warning",
            "info",
            "debug",
            "trace",
        }:
            issues.append(f"{path}.config.transport_options.log_level is invalid")
        for name in ("validate_schema", "access_log", "enable_health", "enable_reflection"):
            if name in raw_options and not isinstance(raw_options[name], bool):
                issues.append(f"{path}.config.transport_options.{name} must be a boolean")
        maximum_concurrent_rpcs = raw_options.get("maximum_concurrent_rpcs")
        if maximum_concurrent_rpcs is not None and (
            not isinstance(maximum_concurrent_rpcs, int)
            or isinstance(maximum_concurrent_rpcs, bool)
            or maximum_concurrent_rpcs < 1
        ):
            issues.append(f"{path}.config.transport_options.maximum_concurrent_rpcs must be a positive integer")
        for name in ("channel_options", "server_options"):
            if name in raw_options and not _valid_grpc_options(raw_options[name]):
                issues.append(f"{path}.config.transport_options.{name} must be an array of [name, value] pairs")

    if transport == "runtime" and config.get("credentials_env"):
        issues.append(f"{path}.config.credentials_env is not supported by the runtime transport")

    raw_transport_config = config.get("transport_config")
    if not isinstance(raw_transport_config, dict):
        return
    try:
        from protolink.transport import TransportConfig

        TransportConfig.from_dict(raw_transport_config)
    except (TypeError, ValueError) as exc:
        issues.append(f"{path}.config.transport_config is invalid: {exc}")


def _valid_grpc_options(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, list)
        and len(item) == 2
        and isinstance(item[0], str)
        and bool(item[0])
        and isinstance(item[1], (str, int))
        and not isinstance(item[1], bool)
        for item in value
    )


def _validate_agent_interfaces(interfaces: list[Any], path: str, issues: list[str]) -> None:
    """Validate additional AgentCard interfaces before code generation."""
    allowed = {"url", "transport", "protocolVersion"}
    for index, interface in enumerate(interfaces):
        interface_path = f"{path}.config.interfaces[{index}]"
        if not isinstance(interface, dict):
            issues.append(f"{interface_path} must be an object")
            continue
        unsupported = sorted(set(interface).difference(allowed))
        if unsupported:
            issues.append(f"{interface_path} contains unsupported fields: {', '.join(unsupported)}")
        transport = str(interface.get("transport") or "http").lower()
        if transport not in STUDIO_TRANSPORTS:
            issues.append(f"{interface_path}.transport must be a supported transport")
            continue
        _validate_transport_url(interface.get("url"), transport, f"{interface_path}.url", issues)
        if "protocolVersion" in interface and not isinstance(interface["protocolVersion"], str):
            issues.append(f"{interface_path}.protocolVersion must be a string")


def _validate_integer(
    config: dict[str, Any],
    key: str,
    path: str,
    issues: list[str],
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    optional: bool = False,
) -> None:
    value = config.get(key)
    if optional and not _is_present(value):
        return
    if isinstance(value, bool) or not isinstance(value, int):
        issues.append(f"{path}.config.{key} must be an integer")
        return
    if minimum is not None and value < minimum:
        issues.append(f"{path}.config.{key} must be at least {minimum}")
    if maximum is not None and value > maximum:
        issues.append(f"{path}.config.{key} must be at most {maximum}")


def _validate_number(
    config: dict[str, Any],
    key: str,
    path: str,
    issues: list[str],
    *,
    minimum: float | None = None,
    optional: bool = False,
) -> None:
    value = config.get(key)
    if optional and not _is_present(value):
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        issues.append(f"{path}.config.{key} must be a finite number")
        return
    if minimum is not None and value < minimum:
        issues.append(f"{path}.config.{key} must be at least {minimum}")


def _validate_boolean(config: dict[str, Any], key: str, path: str, issues: list[str]) -> None:
    if key in config and not isinstance(config[key], bool):
        issues.append(f"{path}.config.{key} must be true or false")


def _validate_json_value(value: Any, path: str, issues: list[str], depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        issues.append(f"{path} exceeds the maximum JSON nesting depth")
        return
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str):
            if len(value) > 200_000:
                issues.append(f"{path} contains a string longer than 200000 characters")
            if "\x00" in value or any(0xD800 <= ord(character) <= 0xDFFF for character in value):
                issues.append(f"{path} contains invalid Unicode or NUL characters")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            issues.append(f"{path} must contain finite numbers")
        return
    if isinstance(value, list):
        if len(value) > 5000:
            issues.append(f"{path} contains too many array items")
        for index, item in enumerate(value[:5000]):
            _validate_json_value(item, f"{path}[{index}]", issues, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 2000:
            issues.append(f"{path} contains too many object fields")
        for key, item in list(value.items())[:2000]:
            if not isinstance(key, str):
                issues.append(f"{path} contains a non-string object key")
                continue
            _validate_json_value(item, f"{path}.{key}", issues, depth + 1)
        return
    issues.append(f"{path} contains unsupported value type {type(value).__name__}")


def _find_embedded_secrets(value: Any, path: str, issues: list[str]) -> None:
    """Reject common secret-bearing keys while allowing ``*_env`` references."""
    secret_keys = {
        "access_token",
        "api_key",
        "auth_token",
        "authorization",
        "client_secret",
        "cookie",
        "credentials",
        "passphrase",
        "password",
        "private_key",
        "proxy_authorization",
        "refresh_token",
        "secret",
        "secret_key",
        "session_token",
        "set_cookie",
        "token",
        "x_api_key",
    }
    if isinstance(value, list):
        for index, item in enumerate(value):
            _find_embedded_secrets(item, f"{path}[{index}]", issues)
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
        if (
            normalized.endswith("_env")
            and _is_present(item)
            and (not isinstance(item, str) or not _ENV_NAME_RE.fullmatch(item))
        ):
            issues.append(f"{path}.{key} must be an environment variable name")
            continue
        if normalized in secret_keys and not normalized.endswith("_env") and item is not None and item != "":
            issues.append(f"{path}.{key} must use an environment-variable reference instead of a secret value")
            continue
        _find_embedded_secrets(item, f"{path}.{key}", issues)


def _connection_allowed(source: dict[str, Any], target: dict[str, Any]) -> bool:
    """Return whether the generator has declarative semantics for a node pair."""
    pair = {source["kind"], target["kind"]}
    if pair in (
        {"agent", "llm"},
        {"agent", "tool"},
        {"agent", "registry"},
        {"flow", "registry"},
        {"agent", "module"},
        {"agent", "flow"},
        {"flow"},
        {"agent"},
    ):
        return True
    if pair == {"module", "registry"}:
        module = source if source["kind"] == "module" else target
        return module["config"].get("module_type") == "storage"
    return False


def _emit_registry(
    lines: list[str],
    node: dict[str, Any],
    node_map: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    runtime_names: dict[str, str],
) -> None:
    config = node["config"]
    name = runtime_names[node["id"]]
    storage_ids = [
        target["id"]
        for target, _edge in _connected_nodes(node["id"], node_map, edges)
        if target["kind"] == "module" and target["config"].get("module_type") == "storage"
    ]
    lines.extend(["", f"    # Registry: {_comment_text(node['label'])}"])
    transport_var = f"registry_transport_{name}"
    _emit_transport(lines, transport_var, config)
    storage_expr = f"modules[{_literal(runtime_names[storage_ids[0]])}]" if storage_ids else "None"
    _emit_call(
        lines,
        f"registries[{_literal(name)}]",
        "Registry",
        kwargs=(
            ("transport", transport_var),
            ("storage", storage_expr),
            ("verbosity", repr(int(config.get("verbosity", 1)))),
            ("entry_ttl_seconds", _literal(config.get("entry_ttl_seconds"))),
        ),
    )


def _emit_module(lines: list[str], node: dict[str, Any], runtime_names: dict[str, str]) -> None:
    config = node["config"]
    module_type = config["module_type"]
    implementation = config["implementation"]
    name = str(config.get("name") or _python_slug(node["label"]))
    target = f"modules[{_literal(runtime_names[node['id']])}]"
    callable_name: str
    positional: tuple[str, ...] = ()
    kwargs: tuple[tuple[str, str], ...]
    if module_type == "storage" and implementation == "memory":
        callable_name = "InMemoryStorage"
        kwargs = (
            ("namespace", _literal(config.get("namespace", name))),
            ("ttl", _literal(config.get("ttl"))),
        )
    elif module_type == "storage":
        callable_name = "SQLiteStorage"
        kwargs = (
            ("db_path", _literal(config.get("path") or "storage.db")),
            ("table_name", _literal(config.get("table_name", "storage"))),
            ("namespace", _literal(config.get("namespace", name))),
        )
    elif module_type == "telemetry" and implementation == "local":
        callable_name = "LocalTraceTelemetry"
        kwargs = (
            ("path", _literal(config.get("path") or "traces.jsonl")),
            ("capture_payloads", repr(bool(config.get("capture_payloads", True)))),
            ("max_traces", repr(int(config.get("max_traces", 1000)))),
        )
    elif module_type == "telemetry" and implementation == "langsmith":
        callable_name = "LangSmithTelemetry"
        kwargs = (
            ("api_key", _env_expression(config.get("api_key_env"))),
            ("project_name", _literal(config.get("project_name"))),
        )
    elif module_type == "telemetry":
        callable_name = "LangfuseTelemetry"
        kwargs = (
            ("public_key", _env_expression(config.get("public_key_env"))),
            ("secret_key", _env_expression(config.get("secret_key_env"))),
            ("host", _literal(config.get("host"))),
        )
    elif module_type == "logger" and implementation == "console":
        callable_name = "ConsoleLogger"
        kwargs = (("name", _literal(name)), ("level", _literal(config.get("level", "INFO"))))
    elif module_type == "logger" and implementation == "file":
        callable_name = "FileLogger"
        kwargs = (
            ("filepath", _literal(config.get("path") or "protolink.log")),
            ("name", _literal(name)),
            ("level", _literal(config.get("level", "INFO"))),
        )
    elif module_type == "logger":
        callable_name = "QuietLogger"
        kwargs = (("name", _literal(name)),)
    elif module_type == "run_store":
        callable_name = "SQLiteRunStore"
        kwargs = (
            ("db_path", _literal(config.get("path") or "runs.db")),
            ("table_prefix", _literal(config.get("table_prefix", "protolink"))),
        )
    elif module_type == "policy":
        callable_name = "CapabilityPolicy"
        kwargs = (
            ("rules", _literal(config.get("rules") or {})),
            ("default_effect", _literal(config.get("default_effect", "allow"))),
            ("name", _literal(name)),
        )
    elif module_type == "knowledge":
        callable_name = "create_knowledge"
        positional = (_literal(implementation),)
        knowledge_kwargs: list[tuple[str, str]] = [
            ("name", _literal(name)),
            ("description", _literal(config.get("description") or f"Knowledge source {name}")),
            ("sources", _literal(config.get("sources") or [])),
            ("default_k", repr(int(config.get("default_k", 5)))),
            ("context_max_chars", repr(int(config.get("context_max_chars", 12000)))),
        ]
        if implementation == "sqlite":
            knowledge_kwargs.extend(
                [
                    ("path", _literal(config.get("path") or "knowledge.db")),
                    ("namespace", _literal(config.get("namespace", name))),
                ]
            )
        kwargs = tuple(knowledge_kwargs)
    else:
        callable_name = "BearerTokenAuth"
        kwargs = (
            ("secret", _env_expression(config.get("secret_env"))),
            ("algorithm", _literal(config.get("algorithm", "HS256"))),
            ("issuer", _literal(config.get("issuer"))),
            ("audience", _literal(config.get("audience"))),
            ("leeway_seconds", repr(int(config.get("leeway_seconds", 0)))),
        )
    lines.extend(
        [
            "",
            f"    # Module: {_comment_text(node['label'])} ({module_type}/{implementation})",
        ]
    )
    _emit_call(lines, target, callable_name, positional=positional, kwargs=kwargs)


def _emit_llm(lines: list[str], node: dict[str, Any], runtime_names: dict[str, str]) -> None:
    config = node["config"]
    options = dict(config.get("advanced") or {})
    if config.get("model"):
        options["model"] = config["model"]
    model_params = dict(config.get("model_params") or {})
    if _is_present(config.get("temperature")):
        model_params["temperature"] = config["temperature"]
    if _is_present(config.get("max_tokens")):
        model_params["max_tokens"] = config["max_tokens"]
    if model_params:
        options["model_params"] = model_params
    if config.get("base_url"):
        options["base_url"] = config["base_url"]
    if config.get("headers"):
        options["headers"] = config["headers"]
    if (
        config.get("provider")
        in {
            "deepseek",
            "grok",
            "ollama",
            "lmstudio",
            "openai-compatible",
            "vllm",
            "llama.cpp-server",
            "llama.cpp-local",
        }
        and "supports_tool_calling" in config
    ):
        options["supports_tool_calling"] = bool(config["supports_tool_calling"])
    if "metrics_enabled" in config:
        options["metrics_enabled"] = bool(config["metrics_enabled"])
    if _is_present(config.get("max_parse_failures")):
        options["max_parse_failures"] = int(config["max_parse_failures"])
    if config.get("provider") == "mock":
        options["default_response"] = config.get("default_response", "Studio mock response")
    option_expressions = {key: _literal(value) for key, value in options.items()}
    if config.get("api_key_env"):
        option_expressions["api_key"] = _env_expression(config["api_key_env"])
    lines.extend(["", f"    # LLM: {_comment_text(node['label'])}"])
    _emit_call(
        lines,
        f"llms[{_literal(runtime_names[node['id']])}]",
        "create_llm",
        positional=(_literal(config["provider"]),),
        kwargs=tuple((key, option_expressions[key]) for key in sorted(option_expressions)),
    )


def _emit_tool(lines: list[str], node: dict[str, Any], runtime_names: dict[str, str]) -> None:
    config = node["config"]
    name = runtime_names[node["id"]]
    if config["implementation"] == "builtin":
        lines.extend(
            [
                "",
                f"    # Tool: {_comment_text(node['label'])}",
                f"    tools[{_literal(name)}] = {config['builtin']}()",
            ]
        )
        return
    lines.extend(
        [
            "",
            f"    # Tool: {_comment_text(node['label'])}",
            f"    def handle_{name}(**kwargs: Any) -> dict[str, Any]:",
            '        """Generated safe placeholder; replace its body with application logic."""',
            "        return {",
            '            "ok": True,',
            f'            "tool": {_literal(config.get("name"))},',
            '            "input": kwargs,',
            f'            "message": {_literal(config.get("response_template"))},',
            "        }",
            f"    tools[{_literal(name)}] = Tool(",
            f"        name={_literal(config.get('name'))},",
            f"        description={_literal(config.get('description'))},",
            f"        input_schema={_literal(config.get('input_schema'))},",
            f"        output_schema={_literal(config.get('output_schema'))},",
            f"        tags={_literal(config.get('tags') or [])},",
            f"        args={_literal(config.get('args') or {})},",
            f"        examples={_literal(config.get('examples') or [])},",
            f"        capabilities={_literal(config.get('capabilities') or [])},",
            f"        func=handle_{name},",
            "    )",
        ]
    )


def _emit_agent(
    lines: list[str],
    node: dict[str, Any],
    node_map: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    runtime_names: dict[str, str],
) -> None:
    config = node["config"]
    name = runtime_names[node["id"]]
    connected = _connected_nodes(node["id"], node_map, edges)
    llm_ids = [item[0]["id"] for item in connected if item[0]["kind"] == "llm"]
    tool_ids = [item[0]["id"] for item in connected if item[0]["kind"] == "tool"]
    registry_ids = [item[0]["id"] for item in connected if item[0]["kind"] == "registry"]
    module_ids = [item[0]["id"] for item in connected if item[0]["kind"] == "module"]
    modules_by_type: dict[str, list[str]] = {}
    for module_id in module_ids:
        module_type = node_map[module_id]["config"]["module_type"]
        modules_by_type.setdefault(module_type, []).append(module_id)

    capabilities = dict(config.get("capabilities") or {})
    capabilities.setdefault("has_llm", bool(llm_ids))
    capabilities.setdefault("tool_calling", bool(tool_ids))
    capabilities.setdefault("streaming", config.get("transport") in {"websocket", "grpc", "runtime", "sse"})
    card = {
        "name": config["name"],
        "description": config["description"],
        "url": config["url"],
        "transport": config["transport"],
        "version": config.get("version", "1.0.0"),
        "capabilities": capabilities,
        "input_formats": config.get("input_formats") or ["text/plain"],
        "output_formats": config.get("output_formats") or ["text/plain"],
        "security_schemes": config.get("security_schemes") or {},
        "role": config.get("role", "worker"),
        "tags": config.get("tags") or [],
        "interfaces": config.get("interfaces") or [],
    }
    lines.extend(["", f"    # Agent: {_comment_text(node['label'])}"])
    transport_var = f"agent_transport_{name}"
    card_var = f"card_{name}"
    _emit_transport(lines, transport_var, config)
    _emit_call(
        lines,
        card_var,
        "AgentCard",
        kwargs=tuple((key, _literal(value)) for key, value in card.items()),
    )
    special = {
        "storage": _module_expression(modules_by_type, "storage", runtime_names),
        "telemetry": _module_expression(modules_by_type, "telemetry", runtime_names),
        "logger": _module_expression(modules_by_type, "logger", runtime_names),
        "run_store": _module_expression(modules_by_type, "run_store", runtime_names),
        "policy": _module_expression(modules_by_type, "policy", runtime_names),
        "authenticator": _module_expression(modules_by_type, "auth", runtime_names),
    }
    registry_expr = f"registries[{_literal(runtime_names[registry_ids[0]])}]" if registry_ids else "None"
    llm_expr = f"llms[{_literal(runtime_names[llm_ids[0]])}]" if llm_ids else "None"
    agent_kwargs: list[tuple[str, str]] = [
        ("card", card_var),
        ("transport", transport_var),
        ("registry", registry_expr),
        ("llm", llm_expr),
        *special.items(),
        ("system_prompt", _literal(config.get("system_prompt") or None)),
        ("state", _literal(config.get("state") or None)),
        ("skills", _literal(config.get("skills", "auto"))),
        ("discovery_ttl", repr(int(config.get("discovery_ttl", 0)))),
        ("override_system_prompt", repr(bool(config.get("override_system_prompt", False)))),
        ("verbosity", repr(int(config.get("verbosity", 1)))),
        ("expose_chat", repr(bool(config.get("expose_chat", True)))),
        ("a2a", repr(bool(config.get("a2a", False)))),
        ("retrieval", _literal(config.get("retrieval", "auto"))),
        ("registry_heartbeat_interval", _literal(config.get("registry_heartbeat_interval"))),
    ]
    knowledge_ids = modules_by_type.get("knowledge", [])
    if knowledge_ids:
        knowledge_expr = ", ".join(f"modules[{_literal(runtime_names[item])}]" for item in knowledge_ids)
        agent_kwargs.append(("knowledge", f"[{knowledge_expr}]"))
    if config.get("credentials_env"):
        agent_kwargs.append(("credentials", _env_expression(config["credentials_env"])))
    _emit_call(lines, f"agents[{_literal(name)}]", "Agent", kwargs=tuple(agent_kwargs))
    for tool_id in tool_ids:
        lines.append(f"    agents[{_literal(name)}].add_tool(tools[{_literal(runtime_names[tool_id])}])")


def _emit_flow(
    lines: list[str],
    node: dict[str, Any],
    node_map: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    runtime_names: dict[str, str],
) -> None:
    config = node["config"]
    name = runtime_names[node["id"]]
    connected = _connected_nodes(node["id"], node_map, edges)
    registry_ids = [item[0]["id"] for item in connected if item[0]["kind"] == "registry"]
    targets: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for edge in edges:
        if edge["from"] == node["id"] and edge["to"] in node_map:
            target = node_map[edge["to"]]
            if target["kind"] in {"agent", "flow"}:
                targets.append((target, edge))
        elif edge["to"] == node["id"] and edge["from"] in node_map:
            target = node_map[edge["from"]]
            if target["kind"] == "agent":
                targets.append((target, edge))
    targets.sort(
        key=lambda item: (
            item[1].get("order", 0),
            item[1]["id"],
            runtime_names[item[0]["id"]],
        )
    )
    target_expressions = [_target_expression(target, runtime_names) for target, _edge in targets]
    registry_expr = f"registries[{_literal(runtime_names[registry_ids[0]])}]" if registry_ids else "None"
    flow_type = config["flow_type"]
    lines.extend(["", f"    # Flow: {_comment_text(node['label'])} ({flow_type})"])
    if flow_type == "pipeline":
        targets_expr = ", ".join(target_expressions)
        lines.append(f"    flows[{_literal(name)}] = Pipeline(steps=[{targets_expr}], registry={registry_expr})")
    elif flow_type == "parallel":
        targets_expr = ", ".join(target_expressions)
        lines.append(f"    flows[{_literal(name)}] = Parallel(branches=[{targets_expr}], registry={registry_expr})")
    elif flow_type == "router":
        routes: list[str] = []
        for target, edge in targets:
            route_key = edge.get("label") or target["config"].get("name") or target["label"]
            route_name = _python_slug(str(route_key)) or runtime_names[target["id"]]
            routes.append(f"{_literal(route_name)}: {_target_expression(target, runtime_names)}")
        lines.append(
            f"    flows[{_literal(name)}] = Router(routes={{{', '.join(routes)}}}, "
            f"routing_prompt={_literal(config.get('routing_prompt') or 'Choose the best route.')}, "
            f"registry={registry_expr})"
        )
    else:
        graph_var = f"graph_{name}"
        lines.append(f"    {graph_var} = Graph(registry={registry_expr})")
        graph_names: dict[str, str] = {}
        for target, _edge in targets:
            graph_name = runtime_names[target["id"]]
            graph_names[target["id"]] = graph_name
            lines.append(
                f"    {graph_var}.add_node({_literal(graph_name)}, {_target_expression(target, runtime_names)})"
            )
        if targets:
            requested_entry = str(config.get("entry_node") or "")
            entry_id = next(
                (
                    target_id
                    for target_id, graph_name in graph_names.items()
                    if requested_entry in {target_id, graph_name}
                ),
                targets[0][0]["id"],
            )
            lines.append(f"    {graph_var}.set_entry_point({_literal(graph_names[entry_id])})")
        graph_edges = [edge for edge in edges if edge["from"] in graph_names and edge["to"] in graph_names]
        if graph_edges:
            for edge in graph_edges:
                source_name = _literal(graph_names[edge["from"]])
                target_name = _literal(graph_names[edge["to"]])
                lines.append(f"    {graph_var}.add_edge({source_name}, {target_name})")
        else:
            for (first, _), (second, _) in pairwise(targets):
                source_name = _literal(graph_names[first["id"]])
                target_name = _literal(graph_names[second["id"]])
                lines.append(f"    {graph_var}.add_edge({source_name}, {target_name})")
        lines.append(f"    flows[{_literal(name)}] = {graph_var}")


def _connected_nodes(
    node_id: str,
    node_map: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    connected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for edge in edges:
        other_id: str | None = None
        if edge["from"] == node_id:
            other_id = edge["to"]
        elif edge["to"] == node_id:
            other_id = edge["from"]
        if other_id in node_map:
            connected.append((node_map[other_id], edge))
    return connected


def _order_flow_nodes(
    flow_nodes: list[dict[str, Any]],
    node_map: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    remaining = {node["id"]: node for node in flow_nodes}
    ordered: list[dict[str, Any]] = []
    while remaining:
        ready = []
        for node_id in remaining:
            dependency_ids = {
                edge["to"]
                for edge in edges
                if edge["from"] == node_id and edge["to"] in remaining and node_map[edge["to"]]["kind"] == "flow"
            }
            if not dependency_ids:
                ready.append(remaining[node_id])
        if not ready:
            raise StudioValidationError(["flow connections contain a cycle; nested flows must be acyclic"])
        ready.sort(key=lambda item: (str(item["config"].get("name") or item["label"]), item["id"]))
        for node in ready:
            remaining.pop(node["id"], None)
            ordered.append(node)
    return ordered


def _blueprint_warnings(blueprint: dict[str, Any]) -> list[str]:
    nodes = blueprint["nodes"]
    edges = blueprint["edges"]
    node_map = {node["id"]: node for node in nodes}
    warnings: list[str] = []
    for node in nodes:
        connected = _connected_nodes(node["id"], node_map, edges)
        connected_kinds = {item[0]["kind"] for item in connected}
        if node["kind"] == "agent" and "llm" not in connected_kinds:
            warnings.append(f"Agent {node['label']!r} has no LLM; it can still run deterministic tools and handlers.")
        if node["kind"] == "agent":
            llm_count = sum(item[0]["kind"] == "llm" for item in connected)
            registry_count = sum(item[0]["kind"] == "registry" for item in connected)
            if llm_count > 1:
                warnings.append(f"Agent {node['label']!r} uses the first of {llm_count} connected LLM nodes.")
            if registry_count > 1:
                warnings.append(f"Agent {node['label']!r} uses the first of {registry_count} connected Registry nodes.")
            module_counts: dict[str, int] = {}
            for connected_node, _edge in connected:
                if connected_node["kind"] == "module":
                    module_type = connected_node["config"]["module_type"]
                    module_counts[module_type] = module_counts.get(module_type, 0) + 1
            for module_type, count in sorted(module_counts.items()):
                if count > 1 and module_type not in {"knowledge", "telemetry"}:
                    warnings.append(
                        f"Agent {node['label']!r} uses the first of {count} connected {module_type} modules."
                    )
        if node["kind"] == "flow" and not connected_kinds.intersection({"agent", "flow"}):
            warnings.append(f"Flow {node['label']!r} has no connected steps or branches.")
        if node["kind"] == "flow" and sum(item[0]["kind"] == "registry" for item in connected) > 1:
            warnings.append(f"Flow {node['label']!r} uses only its first connected Registry node.")
        if node["kind"] == "tool" and "agent" not in connected_kinds:
            warnings.append(f"Tool {node['label']!r} is not attached to an agent.")
        if node["kind"] == "module" and not connected_kinds.intersection({"agent", "registry"}):
            warnings.append(f"Module {node['label']!r} is not attached to an agent or registry.")
        if node["kind"] == "registry":
            storage_count = sum(
                item[0]["kind"] == "module" and item[0]["config"].get("module_type") == "storage" for item in connected
            )
            if storage_count > 1:
                warnings.append(f"Registry {node['label']!r} uses only its first connected storage module.")
    for edge in edges:
        source = node_map[edge["from"]]
        target = node_map[edge["to"]]
        pair = {source["kind"], target["kind"]}
        directly_wired_pairs = (
            {"agent", "llm"},
            {"agent", "tool"},
            {"agent", "registry"},
            {"flow", "registry"},
            {"agent", "module"},
            {"registry", "module"},
        )
        useful = (
            pair in directly_wired_pairs
            or ("flow" in pair and bool(pair.intersection({"agent", "flow"})))
            or pair == {"agent"}
        )
        if not useful:
            warnings.append(
                f"Connection {source['label']!r} -> {target['label']!r} is preserved in the blueprint "
                "but does not affect generated wiring."
            )
    return warnings


def _transport_options(config: dict[str, Any]) -> dict[str, Any]:
    options = dict(config.get("transport_options") or {})
    options.pop("config", None)
    options.pop("url", None)
    for key in ("timeout", "backend", "validate_schema", "log_level", "access_log"):
        if _is_present(config.get(key)):
            options[key] = config[key]
    return options


def _target_expression(node: dict[str, Any], runtime_names: dict[str, str]) -> str:
    collection = "agents" if node["kind"] == "agent" else "flows"
    return f"{collection}[{_literal(runtime_names[node['id']])}]"


def _module_expression(
    modules_by_type: dict[str, list[str]],
    module_type: str,
    runtime_names: dict[str, str],
) -> str:
    ids = modules_by_type.get(module_type) or []
    if module_type == "telemetry" and len(ids) > 1:
        expressions = ", ".join(f"modules[{_literal(runtime_names[item])}]" for item in ids)
        return f"MultiTelemetry([{expressions}])"
    return f"modules[{_literal(runtime_names[ids[0]])}]" if ids else "None"


def _runtime_names(nodes: list[dict[str, Any]]) -> dict[str, str]:
    """Allocate stable, human-readable names without exposing canvas node IDs."""
    names: dict[str, str] = {}
    used: set[str] = set()
    for node in nodes:
        config = node["config"]
        if node["kind"] in {"agent", "flow", "module"}:
            preferred = config.get("name") or node["label"]
        elif node["kind"] == "tool":
            preferred = config.get("builtin") if config.get("implementation") == "builtin" else config.get("name")
        else:
            preferred = node["label"]
        base = _python_slug(str(preferred or node["kind"])) or node["kind"]
        if keyword.iskeyword(base):
            base = f"{base}_"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        names[node["id"]] = candidate
    return names


def _emit_transport(lines: list[str], target: str, config: dict[str, Any]) -> None:
    """Emit one direct call to the public transport factory."""
    kwargs: list[tuple[str, str]] = [
        ("url", _literal(config["url"])),
        (
            "config",
            f"TransportConfig.from_dict({_literal(config.get('transport_config') or {})})",
        ),
    ]
    kwargs.extend((key, _literal(value)) for key, value in sorted(_transport_options(config).items()))
    if config.get("credentials_env"):
        kwargs.append(("credentials", _env_expression(config["credentials_env"])))
    _emit_call(
        lines,
        target,
        "get_transport",
        positional=(_literal(config["transport"]),),
        kwargs=tuple(kwargs),
    )


def _emit_call(
    lines: list[str],
    target: str,
    callable_name: str,
    *,
    positional: tuple[str, ...] = (),
    kwargs: tuple[tuple[str, str], ...] = (),
) -> None:
    """Append a readable, explicitly-keyworded constructor assignment."""
    lines.append(f"    {target} = {callable_name}(")
    lines.extend(f"        {expression}," for expression in positional)
    lines.extend(f"        {key}={expression}," for key, expression in kwargs)
    lines.append("    )")


def _env_expression(env_name: Any) -> str:
    return f"os.getenv({_literal(env_name)})" if env_name else "None"


def _literal(value: Any) -> str:
    formatted = pprint.pformat(value, width=100, sort_dicts=True, compact=True)
    return formatted.replace("\n", "\n    ")


def _clean_text(value: Any, fallback: str, *, limit: int) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return (text or fallback)[:limit]


def _comment_text(value: Any) -> str:
    """Return one bounded source-comment line without executable newlines."""
    one_line = " ".join(str(value).splitlines())
    return "".join(
        character if character.isprintable() and not 0xD800 <= ord(character) <= 0xDFFF else "�"
        for character in one_line
    )[:100]


def _is_present(value: Any) -> bool:
    return value is not None and value != ""


def _python_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_").lower()
    if slug and slug[0].isdigit():
        slug = f"studio_{slug}"
    return slug[:80]


def _finite_coordinate(value: Any, path: str, issues: list[str]) -> float:
    try:
        coordinate = float(value)
    except (TypeError, ValueError, OverflowError):
        issues.append(f"{path} must be a finite number")
        return 0.0
    if not math.isfinite(coordinate) or abs(coordinate) > 100_000:
        issues.append(f"{path} must be finite and between -100000 and 100000")
        return 0.0
    return round(coordinate, 2)


def studio_code_digest(code: str) -> str:
    """Return a short deterministic digest useful to clients and tests."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
