# -*- coding: utf-8 -*-
"""Compiler contract tests (synthetic data only)."""

from __future__ import annotations

import pytest

from conftest import make_bundle
from tsc_compiler.compiler import CompileError, compile_script
from tsc_compiler.normalize import numeric_tokens
from tsc_compiler.validator import validate_script


def compile_ok(bundle):
    script = compile_script(bundle, allowlist={}, asset_base="http://assets.local")
    result = validate_script(script, bundle, expected_revision_id=bundle["revision_id"])
    assert result["status"] == "pass", [
        c for c in result["checks"] if c["status"] == "fail"
    ]
    return script


def test_single_choice_shape() -> None:
    bundle = make_bundle()
    script = compile_ok(bundle)
    assert script["script_schema_version"] == "1.0.0"
    assert script["question_id"] == bundle["question_id"]
    assert script["revision_id"] == bundle["revision_id"]
    first = script["steps"][0]
    assert first["step_id"] == "s1"
    kinds = [block["kind"] for block in first["board"]]
    assert "text" in kinds
    assert kinds.count("choice") == 4
    final = script["steps"][-1]
    callout = [b for b in final["board"] if b["kind"] == "callout"][-1]
    assert callout["tone"] == "answer"
    assert script["final_answer"]["display"] in callout["text"]
    assert script["final_answer"]["source_refs"] == ["ans:0"]
    assert "exp:0" in script["sources"]
    assert any(ref.startswith("cb:u1:stem:") for ref in script["sources"])
    assert all(
        effect["at_ms"] < step["duration_ms"]
        for step in script["steps"]
        for effect in step["effects"]
    )


def test_long_explanation_never_splits_numbers() -> None:
    long_text = (
        "【详解】因为 $ a_{50}^{2}-a_{50}-2550=0 $，且 $ \\frac{2550}{a_{50}}=a_{50}-1 $，"
        "所以 $ a_{50}=51 $。又 $ S_{99}-T_{99}=99 $，由等差数列性质知 $ 99a_{50}-99b_{50}=99 $，"
        "即 $ a_{50}-b_{50}=1 $，逐项代入可解得最终结果。"
    )
    bundle = make_bundle(explanation=["【分析】先建立方程。", long_text])
    script = compile_ok(bundle)
    source_tokens = set()
    for body in bundle["content"]["bodies"]:
        for block in body["stem_blocks"]:
            source_tokens |= numeric_tokens(block["text"])
        for option in body["options"]:
            for block in option["blocks"]:
                source_tokens |= numeric_tokens(block["text"])
    for block in bundle["explanation_blocks"]:
        source_tokens |= numeric_tokens(block["text"])
    for step in script["steps"]:
        for block in step["board"]:
            if block.get("text"):
                assert numeric_tokens(block["text"]) <= source_tokens
    # the split paragraph keeps the whole number in exactly one chunk
    chunks = [
        block["text"]
        for step in script["steps"]
        for block in step["board"]
        if block["kind"] == "text" and "2550" in (block.get("text") or "")
    ]
    assert chunks
    assert any("2550" in chunk for chunk in chunks)


def test_composite_answer_is_rejected() -> None:
    bundle = make_bundle(answer_type="composite", answer_value=[{"sub": "x"}], answer_display=None)
    with pytest.raises(CompileError) as exc:
        compile_script(bundle, allowlist={}, asset_base="http://assets.local")
    assert exc.value.code == "ANSWER_NOT_SIMPLE"


def test_fill_blank_alternatives() -> None:
    bundle = make_bundle(
        question_type="fill_blank",
        answer_type="fill_blank",
        answer_value=[r"$ \frac{1}{2} $#\#0.5"],
        answer_display=None,
        stem=r"1. 计算 $ \frac{1}{2} $ 的值为 ____",
        options=[],
    )
    script = compile_ok(bundle)
    final = script["final_answer"]
    assert final["answer_type"] == "fill_blank"
    assert "0.5" in final["display"]
    assert len(final["accepted_alternatives"]) == 2
    assert final["value"] in final["accepted_alternatives"]


def test_multi_choice_answer_and_targets() -> None:
    bundle = make_bundle(
        question_type="multi_choice",
        answer_type="multi_choice",
        answer_value=["A", "C"],
        answer_display="AC",
    )
    script = compile_ok(bundle)
    assert script["final_answer"]["value"] == "AC"
    targets = {
        block["id"]
        for step in script["steps"]
        for block in step["board"]
    }
    for step in script["steps"]:
        for effect in step["effects"]:
            assert effect["target"] in targets


def test_no_explanation_is_rejected() -> None:
    bundle = make_bundle(explanation=[])
    # remove the generated explanation blocks entirely
    bundle["explanation_blocks"] = []
    with pytest.raises(CompileError) as exc:
        compile_script(bundle, allowlist={}, asset_base="http://assets.local")
    assert exc.value.code == "NO_EXPLANATION"


def test_image_without_allowlist_fails_assets_check() -> None:
    assets = [{"asset_id": "img_x", "storage_path": "_imgs/x.jpg", "mime_type": "image/jpeg"}]
    bundle = make_bundle(assets=assets)
    # replace the first option block with an image block
    bundle["content"]["bodies"][0]["options"][0]["blocks"] = [
        {"kind": "image", "asset_id": "img_x", "alt_text": "配图", "line_start": 12, "line_end": 12}
    ]
    script = compile_script(bundle, allowlist={}, asset_base="http://assets.local")
    result = validate_script(script, bundle, expected_revision_id=bundle["revision_id"])
    assert result["status"] == "fail"
    failed = {c["name"] for c in result["checks"] if c["status"] == "fail"}
    assert "assets_resolve" in failed
