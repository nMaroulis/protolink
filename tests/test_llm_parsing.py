"""Focused tests for prompt-fallback JSON response extraction."""

import json

import pytest

from protolink.llms.actions import FinalAction, ToolCallAction
from protolink.llms.parsing import parse_infer_response


def test_embedded_object_extraction_is_string_and_escape_aware():
    payload = {
        "type": "final",
        "content": 'Keep literal braces { and }, plus an escaped "quote".',
    }
    response = f"Model note: {{not valid JSON}}\n```json\n{json.dumps(payload)}\n```"

    action = parse_infer_response(response)

    assert isinstance(action, FinalAction)
    assert action.content == payload["content"]


def test_embedded_nested_object_is_one_top_level_action():
    payload = {
        "type": "tool_call",
        "tool": "search",
        "args": {"filters": {"kind": "docs", "literal": "}"}},
    }

    action = parse_infer_response(f"Action follows:\n{json.dumps(payload)}\nDone.")

    assert isinstance(action, ToolCallAction)
    assert action.args == payload["args"]


def test_multiple_valid_top_level_objects_are_rejected():
    response = "\n".join(
        [
            json.dumps({"type": "final", "content": "first"}),
            json.dumps({"type": "final", "content": "second"}),
        ]
    )

    with pytest.raises(ValueError, match=r"found 2 valid top-level JSON objects"):
        parse_infer_response(response)


def test_invalid_json_raw_response_diagnostic_is_bounded():
    response = "invalid-start-" + ("x" * 10_000) + "-invalid-end"

    with pytest.raises(ValueError) as exc_info:
        parse_infer_response(response)

    diagnostic = str(exc_info.value)
    assert "Raw response (truncated;" in diagnostic
    assert "characters omitted" in diagnostic
    assert "invalid-start-" in diagnostic
    assert "-invalid-end" in diagnostic
    assert len(diagnostic) < 2_500


def test_schema_validation_parsed_data_diagnostic_is_stable_and_bounded():
    payload = {
        "zeta": "validation-start-" + ("x" * 10_000) + "-validation-end",
        "type": "final",
        "alpha": "first",
    }

    with pytest.raises(ValueError) as exc_info:
        parse_infer_response(json.dumps(payload))

    diagnostic = str(exc_info.value)
    assert "Action validation failed. Field-level errors:" in diagnostic
    assert "Field 'final -> content'" in diagnostic
    assert "Parsed data (truncated;" in diagnostic
    assert "characters omitted" in diagnostic
    assert '{"alpha":"first","type":"final","zeta":"validation-start-' in diagnostic
    assert "-validation-end" in diagnostic
    assert len(diagnostic) < 2_500
