"""Focused tests for prompt-fallback JSON response extraction."""

import json

import pytest

from protolink.llms.actions import FinalAction, ToolCallAction
from protolink.llms.parsing import ActionParseError, parse_infer_response


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


def test_structured_final_content_is_serialized_losslessly():
    content = {
        "statement": "Verdict reached — café",
        "evidence_ids": ["E2"],
        "nested": {"values": [1, True, None]},
    }

    action = parse_infer_response(json.dumps({"type": "final", "content": content}, ensure_ascii=False))

    assert isinstance(action, FinalAction)
    assert json.loads(action.content) == content


def test_list_final_content_is_serialized_losslessly():
    content = [{"id": "E1"}, {"id": "E7"}]

    action = parse_infer_response(json.dumps({"type": "final", "content": content}))

    assert isinstance(action, FinalAction)
    assert json.loads(action.content) == content


def test_bare_application_object_becomes_final_json_content():
    content = {"statement": "Plain application response", "evidence_ids": ["E4"]}

    action = parse_infer_response(json.dumps(content))

    assert isinstance(action, FinalAction)
    assert json.loads(action.content) == content


def test_bare_application_move_does_not_collide_with_runtime_action_fields():
    content = {
        "move": "attempt_persuasion",
        "target_id": "juror_ruben",
        "message": "Consider the deployment evidence.",
    }

    action = parse_infer_response(json.dumps(content))

    assert isinstance(action, FinalAction)
    assert json.loads(action.content) == content


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "unknown", "statement": "not a final action"},
        {"tool": "search", "args": {}},
        {"agent": "researcher", "prompt": "investigate"},
        {"content": {"statement": "missing action type"}},
        {},
    ],
)
def test_action_shaped_or_empty_objects_are_not_silently_finalized(payload):
    with pytest.raises(ValueError, match="Action validation failed"):
        parse_infer_response(json.dumps(payload))


def test_literal_reasoning_tags_inside_valid_json_are_preserved():
    content = "Keep literal <think>{not hidden}</think> text."

    action = parse_infer_response(json.dumps({"type": "final", "content": content}))

    assert isinstance(action, FinalAction)
    assert action.content == content


def test_complete_leading_reasoning_block_is_ignored_after_strict_decode_fails():
    response = (
        '<think>{"type":"final","content":"analysis decoy"}</think>\n{"type":"final","content":"observable answer"}'
    )

    action = parse_infer_response(response)

    assert isinstance(action, FinalAction)
    assert action.content == "observable answer"


def test_action_inside_reasoning_block_is_not_dispatched_without_public_output():
    response = '<think>{"type":"tool_call","tool":"dangerous","args":{}}</think>'

    with pytest.raises(ValueError, match="Invalid JSON"):
        parse_infer_response(response)


def test_unclosed_leading_reasoning_block_fails_safely():
    response = '<think>unfinished analysis\n{"type":"final","content":"observable answer"}'

    with pytest.raises(ValueError, match=r"unterminated leading reasoning block"):
        parse_infer_response(response)


def test_trailing_comma_repair_is_string_aware():
    response = '{"type":"final","content":"literal comma before close: ,}",}'

    action = parse_infer_response(response)

    assert isinstance(action, FinalAction)
    assert action.content == "literal comma before close: ,}"


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


def test_action_parse_error_retains_structured_context_for_correction():
    payload = {
        "type": "agent_call",
        "action": "attempt_persuasion",
        "target_id": "juror_ruben",
        "message": "Consider E3.",
    }

    with pytest.raises(ActionParseError) as exc_info:
        parse_infer_response(json.dumps(payload))

    assert exc_info.value.action_type == "agent_call"
    assert exc_info.value.parsed_data == payload
    assert exc_info.value.raw_response == json.dumps(payload)
    assert "Field-level errors" in exc_info.value.feedback
    assert "Parsed data" not in exc_info.value.feedback


def test_json_decode_error_retains_exact_empty_response():
    with pytest.raises(ActionParseError) as exc_info:
        parse_infer_response("")

    assert exc_info.value.raw_response == ""
    assert exc_info.value.parsed_data is None
    assert exc_info.value.feedback.startswith("Invalid JSON:")
    assert "Raw response" not in exc_info.value.feedback
    assert "Raw response: <empty>" in str(exc_info.value)
