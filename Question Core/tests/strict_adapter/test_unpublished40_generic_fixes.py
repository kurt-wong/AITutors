"""Generic fixes from the unpublished-40 root-cause round (Owner 2026-11-22)."""
from pathlib import Path

import pytest

from strict_adapter.mapper import _dedupe_option_text, _gap_ranges

LONG = "若卵细胞为 E 且第一极体不含 E，则第二极体最多有 4 种可能"


def _opt(label, line, text):
    return {
        "label": label,
        "line_start": line,
        "line_end": line,
        "blocks": [{"kind": "text", "text": text, "line_start": line, "line_end": line}],
    }


def test_option_without_source_marker_is_dropped_as_hallucination():
    lines = ["A. 甲", "B. 乙", f"C. {LONG}", "D. 丁"]
    opts = [_opt("C", 3, f"C. {LONG}"), _opt("E", 3, f"C. {LONG}")]
    log = {}
    out = _dedupe_option_text(opts, log, "U6", lines, [1, 4])
    assert [o["label"] for o in out] == ["C"]
    assert log["option_duplicate_text_dropped"][0]["marker_in_source"] is False


def test_option_with_source_marker_is_kept_but_emptied():
    lines = ["A. 甲", "B. 乙", f"C. {LONG}", f"E. {LONG}", "D. 丁"]
    opts = [_opt("C", 3, f"C. {LONG}"), _opt("E", 3, f"C. {LONG}")]
    log = {}
    out = _dedupe_option_text(opts, log, "U6", lines, [1, 5])
    assert [o["label"] for o in out] == ["C", "E"]
    assert out[1]["text"] == ""
    assert log["option_duplicate_text_dropped"][0]["marker_in_source"] is True


def test_gap_ranges_subtracts_children():
    assert _gap_ranges((202, 204), [(202, 202), (204, 204)]) == [(203, 203)]


RUN = Path(r"D:\Project\AITutors\runs\qcore_six_subject_accept_01\execution\papers_11.json")


@pytest.mark.skipif(not RUN.exists(), reason="run artifacts not available")
def test_material_blocks_stay_in_declared_range_on_real_chemistry_p8():
    import json
    import sys

    sys.path.insert(0, r"D:\Project\AITutors\Question Core")
    from strict_adapter import generic_executor as G

    papers = json.loads(RUN.read_text(encoding="utf-8"))
    d = next(p for p in papers if p["paper_id"].startswith("2022全国乙卷高考真题化学"))
    paper = G.PaperInput.from_dict(d, RUN.parent)
    ctx, _ = G.build_context(paper, "test")
    man = json.loads(Path(d["manifest_path"]).read_text(encoding="utf-8"))
    unit = next(u for u in man["units"] if str(u.get("printed_number")) == "8")
    m = G.map_unit(unit, ctx)
    for mat in m.candidate.core.content.materials:
        for blk in mat.blocks:
            ln = getattr(blk, "line_start", None)
            if isinstance(ln, int):
                assert mat.line_start <= ln <= mat.line_end, (mat.material_id, ln)
