"""Regression: declared option spans must not leak into the stem, and an option
span must not swallow the next option / the next question marker."""
from types import SimpleNamespace

from strict_adapter.mapper import (
    _clamp_option_spans,
    _drop_option_line_blocks,
    _refine_option_specs,
)


# ---------------------------------------------------------------- clamp ------
def _ctx(lines):
    return SimpleNamespace(lines=lines)


def test_last_option_is_not_extended_over_next_subquestion():
    # 2022 全国甲卷英语 U6: sub-question (2) starts on line 5 inside the
    # declared options region [1,7]; option C must stop before it.
    lines = [
        "(1) What are the speakers going to do tonight?",  # 1
        "A.Eat out.",  # 2
        "B.Go shopping.",  # 3
        "C.Do sports.",  # 4
        "(2) What is the probable relationship?",  # 5
        "A. Boss and secretary.",  # 6
        "B. Hostess and guest.",  # 7
    ]
    specs = [{"label": "C", "start": 4, "end": 7}]
    log = {}
    out = _clamp_option_spans(specs, lines, log, "U6")
    assert out[0]["end"] == 4
    assert log["option_span_clamped"][0]["after"] == [4, 4]


def test_option_never_crosses_the_next_option_label():
    lines = ["A. one", "B. two", "C. three"]
    specs = [
        {"label": "A", "start": 1, "end": 3},
        {"label": "B", "start": 2, "end": 3},
        {"label": "C", "start": 3, "end": 3},
    ]
    out = _clamp_option_spans(specs, lines, {}, "u")
    assert [o["end"] for o in out] == [1, 2, 3]


def test_clamp_never_widens_and_keeps_label_order():
    lines = ["A. one", "B. two"]
    specs = [{"label": "B", "start": 2, "end": 2}, {"label": "A", "start": 1, "end": 1}]
    out = _clamp_option_spans(specs, lines, {}, "u")
    assert [o["label"] for o in out] == ["B", "A"]
    assert [o["end"] for o in out] == [2, 1]


def test_refine_fail_open_still_clamps():
    # D is absent from the region -> fail-open path, but the span must still not
    # swallow the following question marker.
    lines = ["D. four", "", "2. next question", "", ""]
    unit = {
        "unit_id": "U1",
        "options_lines": [1, 5],
        "options": [{"label": "D", "start_line": 1, "end_line": 5}],
    }
    out = _refine_option_specs(unit, _ctx(lines), {})
    assert out[0]["end"] < 3, "must stop before the next question marker on line 3"


# ------------------------------------------------------------- stem dedupe ---
def test_option_lines_are_dropped_from_stem():
    raw = [
        {"kind": "text", "text": "1. 生活中处处有化学，下列叙述正确的是", "line_start": 5, "line_end": 5},
        {"kind": "text", "text": "A. HB 铅笔芯的成分为二氧化铅", "line_start": 7, "line_end": 7},
        {"kind": "text", "text": "B. 碳酸氢钠可做食品膨松剂", "line_start": 9, "line_end": 9},
        {"kind": "image", "asset_id": "img_x", "line_start": 11, "line_end": 11},
    ]
    log = {}
    out = _drop_option_line_blocks(raw, [(7, 7), (9, 9)], log, "u1/stem")
    texts = [b.get("text") for b in out if b.get("kind") == "text"]
    assert texts == ["1. 生活中处处有化学，下列叙述正确的是"]
    # an image block inside a declared option span is NOT dropped here
    assert any(b.get("kind") == "image" for b in out)
    assert log["option_lines_removed_from_stem"][0]["where"] == "u1/stem"


def test_non_option_text_inside_span_is_kept():
    # fail-open: a block that does not look like an option keeps its place.
    raw = [{"kind": "text", "text": "passage sentence", "line_start": 7, "line_end": 7}]
    out = _drop_option_line_blocks(raw, [(7, 7)], {}, "u")
    assert len(out) == 1


def test_block_straddling_the_span_is_kept():
    raw = [{"kind": "text", "text": "A. an option that runs on", "line_start": 7, "line_end": 12}]
    out = _drop_option_line_blocks(raw, [(7, 9)], {}, "u")
    assert len(out) == 1
