AGENT_LIST_PROMPT: str = """
Other agents are available to you.

Each agent has:
- name
- description
- capabilities
- tools it owns

You may delegate work by returning an agent_call.
An agent_call routes the Task to another agent and declares what you want that agent to do.

There are two supported agent_call actions.


## 1. Call a tool owned by another agent

Format:
{{
  "type": "agent_call",
  "action": "tool_call",
  "agent": "<agent_name>",
  "tool": "<tool_name>",
  "args": {{ ... }}
}}

Rules:
- The action for a tool call is ALWAYS -> tool_call
- agent MUST exist in the agent list
- tool MUST be owned by the agent
- args MUST conform to the tool schema
- The target agent executes the tool

Example:
{{
  "type": "agent_call",
  "action": "tool_call",
  "agent": "weather_forecaster",
  "tool": "get_weather",
  "args": {{
    "location": "Athens"
  }}
}}

## 2. Ask another agent to generate a response using inference from its LLM

Format:
{{
  "type": "agent_call",
  "action": "infer",
  "agent": "<agent_name>",
  "prompt": "<prompt>"
}}

Rules:
- The action for an inference request is ALWAYS -> infer
- agent MUST exist in the agent list
- The target agent decides how to respond
- The response may include plans, tool_calls, or text

Example:
{{
  "type": "agent_call",
  "action": "infer",
  "agent": "weather_forecaster",
  "prompt": "Determine whether weather conditions are suitable for travel in Athens tomorrow."
}}

Do NOT assume agent internals.
Do NOT execute tools yourself when delegating.

Available agents:
{{agent_cards_from_registry}}
"""
