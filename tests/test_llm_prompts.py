"""Tests for the portable JSON action prompt fragments."""

import json

from protolink.llms.prompts import AGENT_LIST_PROMPT, TOOL_CALL_PROMPT


def test_tool_prompt_renders_single_brace_valid_json_examples():
    prompt = TOOL_CALL_PROMPT.replace("{{tools}}", "[]")
    call_format = prompt.split("using this format:\n", 1)[1].split("\n\nRules:", 1)[0]
    example = prompt.split("Example:\n", 1)[1].split("\n\nImportant:", 1)[0]
    result_format = prompt.split("with the following structure:\n", 1)[1].split("\n\nAfter receiving", 1)[0]

    assert json.loads(call_format)["type"] == "tool_call"
    assert json.loads(example)["tool"] == "get_weather"
    assert json.loads(result_format)["type"] == "tool_result"
    assert "{{" not in prompt
    assert "JSON metadata" in prompt


def test_agent_prompt_renders_single_brace_valid_json_examples():
    prompt = AGENT_LIST_PROMPT.replace("{{agent_cards_from_registry}}", "[]")
    tool_call_format = prompt.split("## 1.", 1)[1].split("Format:\n", 1)[1].split("\n\nRules:", 1)[0]
    infer_section = prompt.split("## 2.", 1)[1]
    infer_format = infer_section.split("Format:\n", 1)[1].split("\n\nRules:", 1)[0]
    result_format = prompt.split("as an `agent_result` message:\n", 1)[1].split("\n\n**IMPORTANT**", 1)[0]

    assert json.loads(tool_call_format)["action"] == "tool_call"
    assert json.loads(infer_format)["action"] == "infer"
    assert json.loads(result_format)["type"] == "agent_result"
    assert "{{" not in prompt
    assert "JSON metadata" in prompt
