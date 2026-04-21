# Refactoring Protolink Structured Flows

Based on our analysis, here is the exact technical plan to clean up and enhance the composability of the flows architecture.

## Proposed Changes

---

### flows/base.py

#### [MODIFY] base.py

- Add type hint definitions: `FlowTarget = Agent | str | "Flow"` for reusability.
- Introduce `_execute_target(self, target: FlowTarget, task: Task) -> Task` inside the `Flow` base class. This method will centralize the `isinstance` checks (Agent, URL string, Nested Flow) and delegation logic.

---

### flows/pipeline.py

#### [MODIFY] pipeline.py

- **Type updates**: Update `steps` list to accept the new centralized `FlowTarget` type, officially enabling nested flows inside pipelines.
- **Fluid API**: Implement `def add_step(self, step: FlowTarget) -> "Pipeline"` to allow chaining initialization.
- **Refactoring**: Replace the manually coded `isinstance` branching in the `execute` method with a simple loop calling the base `_execute_target` method.

---

### flows/parallel.py

#### [MODIFY] parallel.py

- **Type updates**: Update `branches` list to accept `FlowTarget` types.
- **Refactoring**: Remove custom `_execute_local` and `_execute_remote` helper methods.
- **Execution**: Map all branches via `self._execute_target`, allowing execution of isolated local agents, remote agents, and entirely nested pipelines concurrently.
- **Aggregation Safety**: Update the fan-in logic. Instead of comparing array lengths (which is dangerous if tasks diverge in deep structures), use `msg.id` and `art.id` to merge strictly new `Messages` and `Artifacts` to the original task state.

---

### flows/router.py

#### [MODIFY] router.py

- **Refactoring**: Strip out the 20 lines of `route_destination` resolution logic in the `execute` method and replace it with a single call to `await self._execute_target(route_destination, task)`.

---

### flows/graph.py

#### [MODIFY] graph.py

- **Type updates**: Replace its custom `FlowNodeTarget` with the centralized `FlowTarget` from base.
- **Refactoring**: Delete the `_execute_node` custom dispatcher. Replace its invocation natively with `await self._execute_target()`.


## Verification Plan

Because this touches the core flow execution engine, we need to ensure backwards compatibility with your existing tasks.
- Ensure the `examples/structured_flows/run.py` still effectively runs the standard `Pipeline`.
- Ensure `examples/structured_flows/advanced_run.py` correctly handles Parallel, Router, and Graph execution with the new underlying `_execute_target` and ID-based parallel merge logic.
