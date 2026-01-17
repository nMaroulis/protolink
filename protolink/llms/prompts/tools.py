TOOL_CALL_PROMPT: str = """
TOOLS AVAILABLE TO YOU:

Each tool you own has:
- name
- description
- input arguments schema
- output format

To call a tool, generate a Part of type "tool_call" using this format:

{{
  "type": "tool_call",
  "tool": "<tool_name>",
  "args": {{ ... }}
}}

Rules:
- tool_name MUST match an available tool
- args MUST conform to the tool schema
- Return ONLY the JSON object, nothing else

Example:
{{
  "type": "tool_call",
  "tool": "get_weather",
  "args": {{
    "location": "Athens"
  }}
}}

Available tools:
{{tools}}
"""
