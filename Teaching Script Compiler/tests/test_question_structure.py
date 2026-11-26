# -*- coding: utf-8 -*-
"""Structure recovery regression for the four real-photo False Exact cases."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tsc_compiler.semantic.question_structure import (
    StructureStatus,
    analyze_page,
)

FIXTURE = Path(__file__).parent / "fixtures" / "question_structure_v11.json"


def _case(qid: str):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data[qid]


@pytest.mark.parametrize("qid", ["RP05", "RP39", "RP40", "RP43"])
def test_four_false_exact_require_selection(qid):
    case = _case(qid)
    structure = analyze_page(case["text"])
    assert structure.requires_selection, qid
    assert structure.status in {StructureStatus.AMBIGUOUS, StructureStatus.INCOMPLETE, StructureStatus.INVALID}
    assert structure.units, qid


def test_rp05_does_not_create_query_for_missing_q16_q17():
    structure = analyze_page(_case("RP05")["text"])
    assert structure.prefix
    assert structure.status == StructureStatus.AMBIGUOUS
    # The first numbered unit is Q18; Q16/Q17 are not silently invented as units.
    assert structure.units[0].number == "18"
    with pytest.raises(ValueError):
        structure.query_for([])


def test_rp39_multiple_units_and_material_flagged():
    structure = analyze_page(_case("RP39")["text"])
    assert structure.status == StructureStatus.AMBIGUOUS
    assert [u.number for u in structure.units] == ["5", "6", "7", "8"]
    assert "SHARED_MATERIAL_PRESENT" in structure.reasons


def test_rp40_multiple_units():
    structure = analyze_page(_case("RP40")["text"])
    assert structure.status == StructureStatus.AMBIGUOUS
    assert [u.number for u in structure.units] == ["19", "20", "21", "22"]


def test_rp43_tail_prefix_excluded_from_query():
    structure = analyze_page(_case("RP43")["text"])
    assert structure.prefix_is_tail
    assert structure.status == StructureStatus.AMBIGUOUS
    query = structure.query_for([0])
    assert query.startswith("33.")
    assert "（4）" not in query and "(4)" not in query


def test_single_complete_question_is_reliable():
    text = "1. 已知函数 $f(x)=x^2$，求最小值。\nA. 0 B. 1"
    structure = analyze_page(text)
    assert structure.status == StructureStatus.RELIABLE
    assert structure.requires_selection is False
    assert structure.query_for([0]) == text


def test_no_number_is_incomplete():
    text = "阅读下面材料，回答问题。请分析作者的观点。"
    structure = analyze_page(text)
    assert structure.status == StructureStatus.INCOMPLETE
    assert structure.units == []
    assert structure.requires_selection is True


def test_raw_material_is_attached_to_following_units():
    blocks = [
        {"block_label": "text", "block_content": "5. 前一道题\nA. 甲 B. 乙"},
        {
            "block_label": "text",
            "block_content": "长江经济带发展已经上升为国家战略。据此完成下面小题。",
        },
        {"block_label": "text", "block_content": "6. 第一问的完整题目内容\nA. 甲 B. 乙"},
        {"block_label": "text", "block_content": "7. 第二问的完整题目内容\nA. 甲 B. 乙"},
    ]
    raw = json.dumps(
        {
            "result": {
                "layoutParsingResults": [
                    {"prunedResult": {"parsing_res_list": blocks}},
                ]
            }
        },
        ensure_ascii=False,
    )
    text = "\n".join(block["block_content"] for block in blocks)
    structure = analyze_page(text, raw_jsonl=raw)
    assert structure.units[1].context.startswith("长江经济带")
    assert structure.units[2].context.startswith("长江经济带")
    query = structure.query_for([1, 2])
    assert "长江经济带" in query
    assert "5. 前一道题" not in query

