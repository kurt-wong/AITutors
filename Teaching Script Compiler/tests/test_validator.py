# -*- coding: utf-8 -*-
"""Validator tests: every check must fail closed when the script drifts."""

from __future__ import annotations

import copy

from conftest import make_bundle
from tsc_compiler.compiler import compile_script
from tsc_compiler.validator import schema_errors, validate_script


def build():
    bundle = make_bundle()
    script = compile_script(bundle, allowlist={}, asset_base="http://assets.local")
    validate_script(script, bundle, expected_revision_id=bundle["revision_id"])
    return script, bundle


def failed(script, bundle):
    result = validate_script(script, bundle, expected_revision_id=bundle["revision_id"])
    return {c["name"] for c in result["checks"] if c["status"] == "fail"}


def test_clean_script_passes() -> None:
    script, bundle = build()
    result = validate_script(script, bundle, expected_revision_id=bundle["revision_id"])
    assert result["status"] == "pass"
    assert schema_errors(script) == []


def test_answer_tamper_fails() -> None:
    script, bundle = build()
    script = copy.deepcopy(script)
    script["final_answer"]["display"] = "B"
    script["final_answer"]["value"] = "B"
    assert "answer_consistent" in failed(script, bundle)


def test_new_number_fails_fact_check() -> None:
    script, bundle = build()
    script = copy.deepcopy(script)
    script["steps"][1]["board"].append(
        {"id": "b299", "kind": "text", "text": "补充条件：42 是质数"}
    )
    assert "no_unsupported_facts" in failed(script, bundle)


def test_missing_source_ref_fails() -> None:
    script, bundle = build()
    script = copy.deepcopy(script)
    ref = script["steps"][0]["source_refs"][0]
    script["sources"].pop(ref)
    assert "refs_declared" in failed(script, bundle)


def test_dangling_effect_target_fails() -> None:
    script, bundle = build()
    script = copy.deepcopy(script)
    script["steps"][0]["effects"][0]["target"] = "b999"
    assert "board_targets" in failed(script, bundle)


def test_wrong_revision_binding_fails() -> None:
    script, bundle = build()
    result = validate_script(script, bundle, expected_revision_id="9" * 8 + "-0000-0000-0000-000000000000")
    assert result["status"] == "fail"
    assert any(c["name"] == "revision_binding" and c["status"] == "fail" for c in result["checks"])


def test_schema_rejects_unknown_block_kind() -> None:
    script, _bundle = build()
    script = copy.deepcopy(script)
    script["steps"][0]["board"][0]["kind"] = "video"
    assert schema_errors(script)


def test_chunk_text_must_come_from_source() -> None:
    script, bundle = build()
    script = copy.deepcopy(script)
    first_text = next(
        block
        for step in script["steps"]
        for block in step["board"]
        if block["kind"] == "text" and block.get("ref")
    )
    first_text["text"] = "这一句不是源文本"
    assert "board_text_from_source" in failed(script, bundle)

def test_section_marker_is_layout_not_content():
    from tsc_compiler.validator import _strip_section_markers

    # \u3010\u5206\u6790\u3011 = the CJK section marker; escapes keep this file ASCII.
    assert _strip_section_markers("5.\u3010\u5206\u6790\u3011X") == "5.X"
    assert _strip_section_markers("\u3010\u8be6\u89e3\u3011A") == "A"
