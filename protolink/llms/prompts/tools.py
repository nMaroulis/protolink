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
Output Schema Requirements:
- The response MUST be a single valid JSON object.
- Do NOT include any additional text, markdown, or explanations.
- Do NOT wrap the output in code fences.
- Any deviation from this format is considered an invalid response.

Example:
{{
  "type": "tool_call",
  "tool": "get_weather",
  "args": {{
    "location": "Athens"
  }}
}}

Important:
Tool results will be provided to you as SYSTEM messages
with the following structure:

{
  "type": "tool_result",
  "tool": "<tool_name>",
  "result": <tool_output>
}

After receiving a tool_result:
- You MUST decide the next action
- Either call another tool, another agent, or return a final response


You can ONLY call tools that are listed below.
DO NOT call tools that are not listed or invent new tools.

The Following tools are available to you:
{{tools}}
"""
