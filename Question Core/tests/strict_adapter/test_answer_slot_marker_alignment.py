"""Marker-aligned answer slot binding (Owner QCORE-175-FINAL-CLOSURE-01).

Regression gold cases:
  - chemistry 2022 p8: (3) uses (i)(ii)(iii) in the question but ①②③ in the
    answer area; binding must be by top marker group + within-group order, and
    must NOT leak the (2) math tail into (3).
  - chemistry 2023 山东 p16: `16.【答案】（1）①… ②…` on one line.
"""
from pathlib import Path

import pytest

from strict_adapter.mapper import (
    _canon_mark,
    _parse_answer_region,
    _slot_index,
    _slot_top,
)

P8_TEXT = """（1）①.  $ PbSO_4+CO_3^{2-}=PbCO_3+SO_4^{2-} $ ②. 反应  $ PbSO_4+C $ 的平衡常数
（2）反应  $ BaSO_4+CO_3^{2-}=BaCO_3+SO_4^{2-} $ 的平衡常数  $ K=0.04\\times10^5>10^5 $，反应正向进行的程度有限
(3) ①. Fe $ ^{2+} $ ②. Pb+H $ _{2} $O $ _{2} $+2HAc=Pb(Ac) $ _{2} $+2H $ _{2} $O ③. 作还原剂
（4） $ Fe(OH)_{3} $、 $ Al(OH)_{3} $
（5） $ Ba^{2+} $、 $ Na^{+} $
"""


def test_top_markers_are_parsed_per_group_and_decimals_are_not_markers():
    groups = _parse_answer_region(P8_TEXT)
    assert list(groups) == ["1", "2", "3", "4", "5"], groups
    assert len(groups["1"]) == 2
    assert len(groups["2"]) == 1
    assert len(groups["3"]) == 3
    # (2) 里的 0.04 不得产生题号组
    assert "0" not in groups


def test_group_three_binds_fe2_pb_and_reductant_in_order():
    g = _parse_answer_region(P8_TEXT)["3"]
    assert "Fe" in g[0]
    assert "Pb+" in g[1]
    assert "作还原剂" in g[2]


def test_inline_top_marker_after_answer_prefix():
    text = "16.【答案】（1）①. 分子晶体 ②. HF、 $ H_2O_2 $ 和  $ O_2 $\n（2）①.  $ sp^2 $ ②. > ③. 原因"
    groups = _parse_answer_region(text)
    assert len(groups["1"]) == 2
    assert len(groups["2"]) == 3


def test_marker_normalisation_and_slot_ids():
    assert _canon_mark("（３）") == "3"
    assert _canon_mark("16.") == "16"
    assert _slot_top("(3)(i)#1") == "3"
    assert _slot_top("10#1") == "10"
    assert _slot_index("(3)(ii)#2") == 2


RUN = Path(r"D:\Project\AITutors\runs\qcore_six_subject_accept_01\execution\papers_11.json")


@pytest.mark.skipif(not RUN.exists(), reason="run artifacts not available")
def test_real_chemistry_p8_sub_slots_are_not_cross_bound():
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
    values = {}
    for a in m.candidate.core.answers:
        for sub in a.answer_value or ():
            inner = sub.answer_value
            for v in getattr(inner, "answer_value", ()) or ():
                values.setdefault(sub.sub_label, []).append(str(v))
    assert "Fe" in values["(i)"][0]
    assert "Pb+" in values["(ii)"][0]
    assert "作还原剂" in values["(iii)"][0]
    # 组间不串位：(1) 的第一个值是方程式而不是 Fe2+
    assert "PbSO" in values["（1）"][0]
