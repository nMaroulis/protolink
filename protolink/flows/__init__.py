"""
Protolink Pipeline Module.

This package provides deterministic, programmatic orchestration tools that integrate seamlessly with the Protolink
Agent-to-Agent (A2A) architecture. By encapsulating task execution logic within `Flow` implementations, developers can
enforce complex logic topologies like sequential chains, fan-out parallelization, or state graphs, without relying on
the heuristic variations of LLM token inference.

Core Primitives
---------------
    * :class:`Pipeline`:
        Linearly propagates a `Task` through a strict sequence of target Agents.
    * :class:`Parallel`:
        Execute multiple branches concurrently (Fan-out) and safely aggregate all resulting state updates back into a
        synchronized `Task` instance (Fan-in).
    * :class:`Router`:
        Provides programmatic branch evaluation (if/else). Evaluates the `Task` through a deterministic callable,
        mapping the result directly to the designated downstream path.
    * :class:`Graph`:
        Creates LangGraph-style robust state machines. Define discrete execution nodes, setup cyclic boundaries with
        deterministic or dynamically computed edges, and tightly control flow limits.

Composition
-----------
All flow primitives implement the :class:`Flow` abstract contract, guaranteeing an `execute(task: Task) -> Task`
behavior. Because of this uniformity, flows are highly composable. A `Graph` can utilize an `Pipeline` as a
computational Node, which can subsequently branch execution using a `Router`.

Integration
-----------
To construct entirely autonomous microservices out of predefined flows, wrap any instantiated flow sequence inside a
:class:`StructuredAgent` (`protolink.agents.builtins.StructuredAgent`). The resulting agent automatically inherits
network discovery and fully exposes the flow globally to the broader A2A ecosystem.
"""

from .base import Flow
from .graph import Graph
from .parallel import Parallel
from .pipeline import Pipeline
from .router import Router

__all__ = [
    "Flow",
    "Graph",
    "Parallel",
    "Pipeline",
    "Router",
]
