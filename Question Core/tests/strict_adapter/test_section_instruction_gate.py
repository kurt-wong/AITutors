# -*- coding: utf-8 -*-
"""Admission soft-gate H（QCORE-QIQI-SECTION-INSTRUCTION-01）。

带节指令的题型（seven_to_five / cloze / grammar_fill）的卷面指令必须出现在
题面（题干或材料）里；漏在单元区间外时学生端就是「没有题干」——2022 甲卷
15/16/17 都曾如此。

H 是**软门**：不阻断准入（内容不丢），但 admission 强制 incomplete/not_ready，
使其不可发布；声明补齐后重导即恢复 complete。
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


def _soft(rec):
    return audit_unit(rec).get("soft_problems") or []


def _problems(rec):
    return audit_unit(rec)["problems"]


def test_seven_to_five_without_instruction_is_soft_blocked():
    rec = _rec(qtype="seven_to_five", stem_texts=["15. (10分)"])
    res = audit_unit(rec)
    assert res["status"] == "ok", res  # 软门不阻断准入
    assert any(p.startswith("H:") for p in res["soft_problems"]), res


def test_seven_to_five_with_instruction_passes():
    rec = _rec(
        qtype="seven_to_five",
        stem_texts=["阅读下面短文，从短文后的选项中选出可以填入空白处的最佳选项。选项中有两项为多余选项。"],
    )
    assert not _soft(rec)


def test_cloze_and_grammar_fill_are_covered():
    assert _soft(_rec(qtype="cloze", stem_texts=[""]))
    assert _soft(_rec(qtype="grammar_fill", stem_texts=[""]))
    cloze_ok = _rec(
        qtype="cloze",
        stem_texts=["阅读下面短文，从每题所给的 A、B、C、D 四个选项中选出可以填入空白处的最佳选项。"],
    )
    grammar_ok = _rec(
        qtype="grammar_fill",
        stem_texts=["阅读下面短文，在空白处填入1个适当的单词或括号内单词的正确形式。"],
    )
    assert not _soft(cloze_ok)
    assert not _soft(grammar_ok)


def test_instruction_in_material_also_counts():
    rec = _rec(
        qtype="cloze",
        stem_texts=[""],
        material_texts=["阅读下面短文，从短文后各题所给的 A、B、C 和 D 四个选项中，选出可以填入空白处的最佳选项。"],
    )
    assert not _soft(rec)


def test_other_question_types_are_not_checked():
    for qtype in ("reading", "single_choice", "short_answer", "essay", ""):
        rec = _rec(qtype=qtype, stem_texts=["18. （10分）假定英语课上老师要求同学之间交换修改作文。"])
        assert not _soft(rec), qtype


def test_wording_variants_across_papers_pass():
    """2019 北京卷：语法填空「阅读下列短文，根据短文内容填空。在未给提示词的空白处仅填写
    1个适当的单词……」/ 完形「阅读下面短文，掌握其大意，从每题所给的……」。"""
    grammar = _rec(
        qtype="grammar_fill",
        stem_texts=[
            "第一节 语法填空（共10小题；每小题1.5分，共15分）",
            "阅读下列短文，根据短文内容填空。在未给提示词的空白处仅填写1个适当的单词，"
            "在给出提示词的空白处用括号内所给词的正确形式填空。",
        ],
    )
    cloze = _rec(
        qtype="cloze",
        stem_texts=[
            "第二节 完形填空（共20小题；每小题1.5分，共30分）",
            "阅读下面短文，掌握其大意，从每题所给的 A、B、C、D 四个选项中，选出最佳选项，"
            "并在答题卡上将该项涂黑。",
        ],
    )
    assert not _soft(grammar)
    assert not _soft(cloze)
