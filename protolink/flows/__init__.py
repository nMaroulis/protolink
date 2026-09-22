"""
Protolink Pipeline Module.

This package provides deterministic, programmatic orchestration tools that integrate seamlessly with the ProtoLink
runtime architecture. By encapsulating task execution logic within `Flow` implementations, developers can
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

Convenience
-----------
Use ``flow.invoke(prompt)`` for final content, or ``execute(task)`` for complete task
history. ``Step`` adapts a Task-to-Task callable, ``ToolStep`` executes a registered
tool through its agent, and ``RepeatUntil`` bounds repetition by completion checks.
"""

from .base import Flow
from .graph import Graph
from .limits import WorkflowLimitError
from .parallel import Parallel
from .pipeline import Pipeline
from .responses import StructuredResponseError
from .router import Router
from .steps import RepeatUntil, Step, ToolStep

__all__ = [
    "Flow",
    "Graph",
    "Parallel",
    "Pipeline",
    "RepeatUntil",
    "Router",
    "Step",
    "StructuredResponseError",
    "ToolStep",
    "WorkflowLimitError",
]
