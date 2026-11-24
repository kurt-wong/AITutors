# -*- coding: utf-8 -*-
"""Admission rule H（QCORE-QIQI-SECTION-INSTRUCTION-01）。

带节指令的题型（seven_to_five / cloze / grammar_fill）的卷面指令必须出现在
题面（题干或材料）里；Manifest 把指令行漏在单元区间外时，学生端就是「没有
题干」——2022 甲卷 15/16/17 都曾如此。规则只对这三类题型生效。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strict_adapter.content_audit import audit_unit  # noqa: E402


def _rec(*, qtype, stem_texts, material_texts=()):
    lines = list(stem_texts) + list(material_texts)
    stem_blocks = [{"kind": "text", "text": t, "line_start": i + 1, "line_end": i + 1}
                   for i, t in enumerate(stem_texts)]
    material_blocks = [
        {"kind": "text", "text": t, "line_start": len(stem_texts) + i + 1,
         "line_end": len(stem_texts) + i + 1}
        for i, t in enumerate(material_texts)
    ]
    return {
        "unit_id": "U-test",
        "question_type": qtype,
        "source_lines": lines,
        "source_line_count": len(lines),
        "unit_lines": [(1, len(lines))] if lines else [],
        "manifest_option_lines": [],
        "options": [],
        "stem_blocks": stem_blocks,
        "material_blocks": material_blocks,
        "explanation_blocks": [],
        "options_shape": "stem_text",
    }


def _problems(rec):
    return audit_unit(rec)["problems"]


def test_seven_to_five_without_instruction_is_blocked():
    rec = _rec(qtype="seven_to_five", stem_texts=["15. (10分)"])
    probs = _problems(rec)
    assert any(p.startswith("H:") for p in probs), probs


def test_seven_to_five_with_instruction_passes():
    rec = _rec(
        qtype="seven_to_five",
        stem_texts=["阅读下面短文，从短文后的选项中选出可以填入空白处的最佳选项。选项中有两项为多余选项。"],
    )
    probs = _problems(rec)
    assert not any(p.startswith("H:") for p in probs), probs


def test_cloze_and_grammar_fill_are_covered():
    cloze_bad = _rec(qtype="cloze", stem_texts=[""])
    grammar_bad = _rec(qtype="grammar_fill", stem_texts=[""])
    assert any(p.startswith("H:") for p in _problems(cloze_bad))
    assert any(p.startswith("H:") for p in _problems(grammar_bad))
    cloze_ok = _rec(
        qtype="cloze",
        stem_texts=["阅读下面短文，从每题所给的 A、B、C、D 四个选项中选出可以填入空白处的最佳选项。"],
    )
    grammar_ok = _rec(
        qtype="grammar_fill",
        stem_texts=["阅读下面短文，在空白处填入1个适当的单词或括号内单词的正确形式。"],
    )
    assert not any(p.startswith("H:") for p in _problems(cloze_ok))
    assert not any(p.startswith("H:") for p in _problems(grammar_ok))


def test_instruction_in_material_also_counts():
    rec = _rec(
        qtype="cloze",
        stem_texts=[""],
        material_texts=["阅读下面短文，从短文后各题所给的 A、B、C 和 D 四个选项中，选出可以填入空白处的最佳选项。"],
    )
    assert not any(p.startswith("H:") for p in _problems(rec))


def test_other_question_types_are_not_checked():
    for qtype in ("reading", "single_choice", "short_answer", "essay", ""):
        rec = _rec(qtype=qtype, stem_texts=["18. （10分）假定英语课上老师要求同学之间交换修改作文。"])
        probs = _problems(rec)
        assert not any(p.startswith("H:") for p in probs), (qtype, probs)
