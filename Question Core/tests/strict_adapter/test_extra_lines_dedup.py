from types import SimpleNamespace

from strict_adapter.mapper import _merge_extras_and_figures


def _run(extra_lines, consumed_lines, text="same text"):
    ctx = SimpleNamespace(lines=[text, text, text, text, text])
    unit = {"extra_lines": extra_lines, "figures": []}
    raw = [{"kind": "text", "text": text, "line_start": 1, "line_end": 1}]
    log = {}
    out = _merge_extras_and_figures(
        unit, ctx, raw, log=log, where="root", target="u1",
        extra_text_dedup=True, extra_text_cutoff=10,
        consumed_lines=consumed_lines,
    )
    return out, log


def test_same_source_line_already_consumed_is_suppressed():
    out, log = _run([2, 2], {1, 2})
    assert len(out) == 1
    assert any(x["reason"] == "same_source_line_already_consumed"
               for x in log.get("extra_text_suppressed", []))


def test_different_source_lines_with_identical_text_are_both_kept():
    out, log = _run([2, 2], {1})
    assert len(out) == 2
    assert out[1].get("line_start") == 2
    assert not log.get("extra_text_suppressed")


def test_insufficient_line_evidence_is_kept():
    ctx = SimpleNamespace(lines=["same text", "same text"])
    unit = {"extra_lines": [2, 2], "figures": []}
    raw = [{"kind": "text", "text": "same text"}]  # no line evidence
    log = {}
    out = _merge_extras_and_figures(
        unit, ctx, raw, log=log, where="root", target="u1",
        extra_text_dedup=True, extra_text_cutoff=10, consumed_lines={1},
    )
    assert len(out) == 2
    assert not log.get("extra_text_suppressed")
