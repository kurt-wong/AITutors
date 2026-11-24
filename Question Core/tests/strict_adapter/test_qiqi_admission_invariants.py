# -*- coding: utf-8 -*-
"""Admission invariants F / G（QCORE-QIQI-MATERIAL-LOSS-01 / REREOCR-01）。

F：单元声明范围内，非空、非分隔线、非媒体/页脚的源行必须被某个内容块承载
   —— 正文静默丢失（七选五材料被裁、小问被清空、答案区错位）都会命中。
G：同一选项内多个文本块去掉标号后文本相同 = OCR 抽取重复（PDF 只印一次）
   —— 2023 I 卷七选五选项 G 的重复行即此形态。

两条都是 fail-closed：命中即 unit FAIL，阻断准入与发布。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strict_adapter.content_audit import audit_unit  # noqa: E402


def _rec(source_lines, *, unit_lines, stem_blocks, options, materials=None):
    return {
        "unit_id": "U-test",
        "source_lines": list(source_lines),
        "source_line_count": len(source_lines),
        "unit_lines": [tuple(x) for x in unit_lines],
        "manifest_option_lines": [],
        "options": options,
        "stem_blocks": stem_blocks,
        "material_blocks": materials or [],
        "explanation_blocks": [],
        "options_shape": "option_items" if options else "stem_text",
    }


def _fg(rec):
    res = audit_unit(rec)
    return [p for p in res["problems"] if p.startswith(("F:", "G:"))], res


# ---------------- G: 选项自重复 ----------------


def test_option_self_repeat_is_blocked():
    lines = [
        "G. Whatever the mistake, remember it isn't a fixed aspect.",
        "G. Whatever the mistake, remember it isn’t a fixed aspect.",
    ]
    rec = _rec(
        lines,
        unit_lines=[(1, 2)],
        stem_blocks=[],
        options=[{
            "label": "G",
            "line_start": 1,
            "line_end": 2,
            "blocks": [
                {"kind": "text", "text": "Whatever the mistake, remember it isn't a fixed aspect.",
                 "line_start": 1, "line_end": 1},
                {"kind": "text", "text": "G. Whatever the mistake, remember it isn’t a fixed aspect.",
                 "line_start": 2, "line_end": 2},
            ],
        }],
    )
    fg, res = _fg(rec)
    assert res["status"] == "FAIL"
    assert any(p.startswith("G:") for p in fg), fg


def test_distinct_option_blocks_pass():
    lines = [
        "A. A little self-forgiveness also goes a long way.",
        "B. Now list all the characteristics you like about yourself.",
    ]
    rec = _rec(
        lines,
        unit_lines=[(1, 2)],
        stem_blocks=[],
        options=[
            {"label": "A", "line_start": 1, "line_end": 1,
             "blocks": [{"kind": "text", "text": "A little self-forgiveness also goes a long way.",
                         "line_start": 1, "line_end": 1}]},
            {"label": "B", "line_start": 2, "line_end": 2,
             "blocks": [{"kind": "text", "text": "Now list all the characteristics you like about yourself.",
                         "line_start": 2, "line_end": 2}]},
        ],
    )
    fg, res = _fg(rec)
    assert not fg, fg
    assert res["status"] == "ok"


# ---------------- F: 单元行覆盖 ----------------


def test_uncovered_unit_line_is_blocked():
    lines = ["Question stem line.", "Option line.", "Lost passage line."]
    rec = _rec(
        lines,
        unit_lines=[(1, 3)],
        stem_blocks=[{"kind": "text", "text": "Question stem line.", "line_start": 1, "line_end": 1}],
        options=[{"label": "A", "line_start": 2, "line_end": 2,
                  "blocks": [{"kind": "text", "text": "Option line.", "line_start": 2, "line_end": 2}]}],
    )
    fg, res = _fg(rec)
    assert res["status"] == "FAIL"
    assert any(p.startswith("F:") for p in fg), fg
    assert rec.get("unit_lines") == [(1, 3)]


def test_full_coverage_passes():
    lines = ["Stem line.", "Passage paragraph."]
    rec = _rec(
        lines,
        unit_lines=[(1, 2)],
        stem_blocks=[{"kind": "text", "text": "Stem line.", "line_start": 1, "line_end": 1}],
        materials=[{"kind": "text", "text": "Passage paragraph.", "line_start": 2, "line_end": 2}],
        options=[],
    )
    fg, res = _fg(rec)
    assert not fg, fg
    assert res["status"] == "ok"


def test_media_and_furniture_lines_are_exempt():
    lines = [
        "Stem line.",
        '<div style="text-align: center;"><img src="imgs/x.jpg" /></div>',
        "7 / 20",
    ]
    rec = _rec(
        lines,
        unit_lines=[(1, 3)],
        stem_blocks=[{"kind": "text", "text": "Stem line.", "line_start": 1, "line_end": 1}],
        options=[],
    )
    fg, res = _fg(rec)
    assert not fg, fg
    assert res["status"] == "ok"


def test_thematic_break_line_is_exempt():
    lines = ["Stem line.", "---"]
    rec = _rec(
        lines,
        unit_lines=[(1, 2)],
        stem_blocks=[{"kind": "text", "text": "Stem line.", "line_start": 1, "line_end": 1}],
        options=[],
    )
    fg, _res = _fg(rec)
    assert not fg, fg
