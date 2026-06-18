# ruff: noqa: E501
FLOW_TARGET_PROMPT: str = """
--- FLOW PIPELINE CONTEXT ---
IMPORTANT: You are executing as a step in a structured Flow/Pipeline.
Your final output will be passed directly as input to the next agent: '{next_agent_name}'.

Capabilities and description of the next agent:
{next_agent_card}

Please ensure your response is formulated and structured so it is optimized and directly suitable as input for '{next_agent_name}'.
"""

FLOW_TERMINAL_PROMPT: str = """
--- FLOW PIPELINE CONTEXT ---
This is the final step in the structured Flow/Pipeline.
Your output will be returned directly to the human user.
Please ensure your response is polished, user-friendly, and complete.
"""
FLOW_ROUTER_PROMPT: str = """
--- FLOW ROUTING DECISION ---
IMPORTANT: You are the decision-maker for a conditional routing intersection in a Flow/Pipeline.
Based on your current output, you must choose exactly ONE of the following downstream paths.

Routing Rules provided by the developer:
{routing_prompt}

Available Routes:
{routes_info}

Prefer emitting a structured route decision part in the runtime shape:
{{"type": "route", "content": {{"route_key": "route_key", "reason": "short reason"}}}}

If your provider can only return text, append the exact routing tag to the very end of your final response using
the format: [ROUTE: route_key]
For example, if you choose the 'editor' route, end your text with: [ROUTE: editor]
"""
FLOW_PARALLEL_PROMPT: str = """
--- FLOW PIPELINE CONTEXT ---
IMPORTANT: Your output will be passed simultaneously to multiple downstream agents executing concurrently in a Parallel flow structure.

Receiving Agents:
{parallel_info}

Please ensure your response is formulated comprehensively so it serves as an optimal input for ALL of these concurrent receivers.
"""
