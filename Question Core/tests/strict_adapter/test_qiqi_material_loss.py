# -*- coding: utf-8 -*-
"""七选五「材料正文丢失」回归测试（QCORE-QIQI-MATERIAL-LOSS-01）。

缺陷（2026-11-24，Owner 目视发现）：七选五 Unit 的 Manifest 把整段短文声明为
材料（如 177-189），同时把小问声明为段落内的空位行（179/181/183/187/189）。
旧实现把小问行区从材料中裁掉（material_sub_overlap_trimmed），又把「完全落在
材料内」的小问置为空结构占位（shared_material_sub_placeholders）——两条规则同时
生效时，短文正文既不在材料、也不在小问，整段静默丢失，学生端只剩选项。

规则：小问**完全落在材料区间内**时视为空位，材料是唯一载体，不得裁切。
本测试用合成源文锁定该不变量（不依赖封存 Run）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strict_adapter.mapper import MappingContext, map_unit  # noqa: E402

LINES = [
    "# 第二节",                                                        # 1
    "阅读下面短文，从短文后的选项中选出可以填入空白处的最佳选项。", # 2
    "## Personal Forgiveness",                                        # 3
    "Taking responsibility for mistakes is a positive step.  $ \\underline{16} $ You can use the exercise.",  # 4
    "",                                                               # 5
    "In a journal, put the heading \"Personal strengths.\"  $ \\underline{17} $ Are you caring?",  # 6
    "",                                                               # 7
    "A. A little self-forgiveness also goes a long way.",             # 8
    "",                                                               # 9
    "B. Now list all the characteristics you like about yourself.",   # 10
    "",                                                               # 11
    "C. They might even like to have a go at doing the exercise.",    # 12
]


def _unit() -> dict:
    return {
        "unit_id": "U5",
        "unit_type": "composite_question",
        "section": "第二部分 阅读 第二节",
        "printed_number": "16",
        "question_numbers": [16, 17],
        "original_question_type": "seven_to_five",
        "material_lines": [3, 6],
        "questions_lines": [2, 12],
        "options_lines": [8, 12],
        "materials": [
            {"material_id": "M01", "label": "Personal Forgiveness",
             "line_start": 3, "line_end": 6},
        ],
        "sub_questions": [
            {"sub_id": "S1", "label": "16", "label_kind": "printed_number",
             "parent_sub_id": None, "order": 1,
             "line_start": 4, "line_end": 4,
             "materials_used": ["M01"], "answer_refs": ["16#1"],
             "figure_refs": [], "answer_entry_count": 1, "uncertainty": None},
            {"sub_id": "S2", "label": "17", "label_kind": "printed_number",
             "parent_sub_id": None, "order": 2,
             "line_start": 6, "line_end": 6,
             "materials_used": ["M01"], "answer_refs": ["17#1"],
             "figure_refs": [], "answer_entry_count": 1, "uncertainty": None},
        ],
        "answers": [
            {"sub_ref": "S1", "sub_label": "16", "slot_id": "16#1",
             "value_text": "E", "form": "verbatim", "source_region": "answer_area",
             "evidence_lines": [4, 4], "status": "resolved",
             "missing_reason": None, "note": None},
            {"sub_ref": "S2", "sub_label": "17", "slot_id": "17#1",
             "value_text": "B", "form": "verbatim", "source_region": "answer_area",
             "evidence_lines": [6, 6], "status": "resolved",
             "missing_reason": None, "note": None},
        ],
        "answer_evidence": {"type": "answer_lines", "lines": [4, 6],
                            "value": None, "shared": False},
        "answer_completeness": "full",
    }


def _ctx(manifest) -> MappingContext:
    return MappingContext(
        lines=list(LINES),
        manifest=manifest,
        manifest_path="m.json",
        manifest_name="m.json",
        source_md_path="s.md",
        source_md_name="s.md",
        source_pdf_name="s.pdf",
        annotated_md_name="a.md",
        manifest_sha="1" * 64,
        source_md_sha="2" * 64,
        source_pdf_sha="3" * 64,
        annotated_md_sha="4" * 64,
        manifest_bytes=1,
        source_md_bytes=1,
        source_pdf_bytes=1,
        annotated_md_bytes=1,
        image_by_line={},
        paper_id="paper",
        subject="英语",
        run_id="qiqi-material-loss-tests",
    )


def _mapped():
    u = _unit()
    return map_unit(u, _ctx({"units": [u]}))


def test_material_keeps_passage_paragraphs_inside_sub_ranges():
    m = _mapped()
    mats = m.candidate.core.content.materials
    assert [x.material_id for x in mats] == ["M01"]
    text = "".join(b.text for b in mats[0].blocks)
    # 段落正文（小问行 4/6）必须由材料承载
    assert "Taking responsibility for mistakes" in text
    assert "Personal strengths" in text
    # 且标题行同样保留
    assert "Personal Forgiveness" in text


def test_sub_questions_stay_structural_placeholders():
    m = _mapped()
    bodies = {b.local_id: b for b in m.candidate.core.content.bodies}
    for sid in ("S1", "S2"):
        assert bodies[sid].stem_blocks
        assert all((b.text or "").strip() == "" for b in bodies[sid].stem_blocks), sid
    assert bodies["u5"].options and [o.label for o in bodies["u5"].options] == ["A", "B", "C"]


def test_no_source_line_is_silently_dropped():
    """材料正文 ∪ 父题面 ∪ 选项 必须覆盖全部声明源行（零静默丢失）。"""
    m = _mapped()
    content = m.candidate.core.content
    cover: set[int] = set()
    for mat in content.materials:
        for b in mat.blocks:
            if b.line_start is not None:
                cover.update(range(b.line_start, (b.line_end or b.line_start) + 1))
    for body in content.bodies:
        for b in body.stem_blocks:
            if (b.text or "").strip() and b.line_start is not None:
                cover.update(range(b.line_start, (b.line_end or b.line_start) + 1))
        for opt in body.options:
            for b in opt.blocks:
                if b.line_start is not None:
                    cover.update(range(b.line_start, (b.line_end or b.line_start) + 1))
    for ln in (2, 3, 4, 6, 8, 10, 12):
        assert ln in cover, f"source line {ln} not covered: {LINES[ln - 1]!r}"
