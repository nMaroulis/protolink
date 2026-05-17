from collections.abc import Callable

from protolink.client import AgentClient, RegistryClient
from protolink.discovery import Registry
from protolink.models import Task
from protolink.types import FlowTarget

from .base import Flow


class Graph(Flow):
    """A directed graph-based state machine flow.

    Enables graph-like complexities including cyclical loops and deeply conditional
    branching topologies by registering explicit nodes and edges.

    Nodes can execute:
    - **Local Agent Instances**: Direct execution of agent logic.
    - **Remote Agent Identifiers**: Strings resolved via the registry layer.
    - **Nested Flows**: Encapsulated standard flows (Pipelines, Parallel, Routers)
      acting as a single node in the graph.
    """

    def __init__(
        self,
        client: AgentClient | None = None,
        registry: Registry | RegistryClient | None = None,
    ) -> None:
        """Initialize an empty Graph.

        Args:
            client: Optional `AgentClient` for executing remote pathing.
            registry: Optional registry configuration for mapping agent discovery.
        """
        super().__init__(client=client, registry=registry)

        self.nodes: dict[str, FlowTarget] = {}

        # Edges map a node name to exactly one destination node name.
        self.edges: dict[str, str] = {}

        # Conditional edges map a node name to a tuple of (condition_callable, mapping_dict)
        self.conditional_edges: dict[str, tuple[Callable[[Task], str], dict[str, str]]] = {}

        self.entry_point: str | None = None
        self.finish_point: str = "__END__"

    def add_node(self, node_name: str, target: FlowTarget) -> "Graph":
        """Add a computational node to the graph.

        Args:
            node_name: The unique string identifier for the node.
            target: The executing unit (`Agent`, string URL/name, or nested `Flow`).

        Returns:
            The `Graph` instance to allow connection chaining.
        """
        if node_name == self.finish_point:
            raise ValueError(f"Cannot map custom node to reserved name '{self.finish_point}'")
        self.nodes[node_name] = target
        return self

    def add_edge(self, from_node: str, to_node: str) -> "Graph":
        """Add a constant, deterministic edge between two nodes.

        Args:
            from_node: The name of the originating node.
            to_node: The name of the destination node, or "__END__" to terminate.

        Returns:
            The `Graph` instance to allow connection chaining.
        """
        self._validate_node_existence(from_node)
        if to_node != self.finish_point:
            self._validate_node_existence(to_node)

        if from_node in self.conditional_edges:
            raise ValueError(
                f"Node '{from_node}' already manifests a conditional edge. A node can only have one outbound edge type."
            )

        self.edges[from_node] = to_node
        return self

    def add_conditional_edge(
        self, from_node: str, condition_fn: Callable[[Task], str], path_map: dict[str, str]
    ) -> "Graph":
        """Add a conditionally evaluated edge originating from a node.

        The `condition_fn` evaluates the Task state after `from_node` completes.
        It returns a key which must map closely to a destination node inside `path_map`.

        Args:
            from_node: The name of the originating node.
            condition_fn: A synchronous callable evaluating the `Task` to return a map key.
            path_map: A dictionary linking the potential condition keys to valid destination
                node identifiers (or "__END__").

        Returns:
            The `Graph` instance.
        """
        self._validate_node_existence(from_node)
        for dest in path_map.values():
            if dest != self.finish_point:
                self._validate_node_existence(dest)

        if from_node in self.edges:
            raise ValueError(
                f"Node '{from_node}' already possesses a standard edge. A node can only have one outbound edge type."
            )

        self.conditional_edges[from_node] = (condition_fn, path_map)
        return self

    def set_entry_point(self, node_name: str) -> "Graph":
        """Define the initial starting node of the graph.

        Args:
            node_name: The name of the starting node.

        Returns:
            The `Graph` instance.
        """
        self._validate_node_existence(node_name)
        self.entry_point = node_name
        return self

    async def execute(self, task: Task) -> Task:
        """Execute the graph traversal sequence based on connections and state logic.

        This method implements Semantic Context Injection. Before executing each node, it checks if a deterministic,
        non-conditional edge exists pointing to a subsequent node. If found, it pre-builds a context-aware LLM prompt
        using `_build_flow_prompt` and populates `task.flow_state["prompt"]`. This allows the executing agent to
        dynamically format its output specifically for the downstream receiver without knowing the graph's structure.

        Args:
            task: The original `Task` payload to flow through the machine.

        Returns:
            The finalized `Task` payload once the graph reaches "__END__".

        Raises:
            RuntimeError: If graph entry point is unassigned or a destination is unreachable.
        """
        if not self.entry_point:
            raise RuntimeError("Graph cannot execute without a declared entry point.")

        current_node_name = self.entry_point
        current_task = task

        iteration_count = 0
        max_iterations = 50  # Prevents absolute infinite loops blindly locking the system

        while current_node_name != self.finish_point:
            iteration_count += 1
            if iteration_count > max_iterations:
                raise RuntimeError(
                    f"Graph depth exceeded safety threshold of {max_iterations} iterations. "
                    "You may have an infinite loop in your edge configuration."
                )

            self._logger.info(f"Graph orchestrating node: [{current_node_name}]")
            target = self.nodes[current_node_name]

            # Determine deterministic subsequent destination if applicable
            next_target = None
            if current_node_name in self.edges:
                next_target = self.edges[current_node_name]
                if next_target == self.finish_point:
                    current_task.flow_state.clear()
                    current_task.flow_state["prompt"] = await self._build_flow_prompt(is_final=True)
                else:
                    target_obj = self.nodes[next_target]
                    current_task.flow_state.clear()
                    current_task.flow_state["prompt"] = await self._build_flow_prompt(next_target=target_obj)
            else:
                # Conditional edges are non-deterministic before execution.
                current_task.flow_state.clear()

            current_task = await self._execute_target(target, current_task)

            # Determine the subsequent destination
            if current_node_name in self.edges:
                current_node_name = self.edges[current_node_name]
            elif current_node_name in self.conditional_edges:
                cond_fn, path_map = self.conditional_edges[current_node_name]
                route_key = cond_fn(current_task)

                if route_key not in path_map:
                    raise ValueError(f"Conditional boundary resulted in key '{route_key}' undefined in mapping.")
                current_node_name = path_map[route_key]
            else:
                self._logger.warning(
                    f"Node '{current_node_name}' implies a dead end without outbound edges. "
                    f"Auto-closing graph traversal to '{self.finish_point}'."
                )
                current_node_name = self.finish_point

        self._logger.info("Graph reached terminal __END__ state.")
        return current_task

    def _validate_node_existence(self, node_name: str) -> None:
        """Internal helper validating if node is historically mapped."""
        if node_name not in self.nodes:
            raise ValueError(f"Node '{node_name}' does not structurally exist in the graph.")
