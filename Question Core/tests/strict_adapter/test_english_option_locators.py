"""R1 B3：英语选项块级行定位测试（合成 + 真卷 U4/U9）。

断言：parse_cloze_option_rows / parse_ag_pool / parse_reading_stems 全链
携带真实行号；OptionItem/TextBlock 块级 line_start/line_end 非空且指向
真实来源行；U9 共享池只在父级且逐块定位。不得用 Unit 级行区冒充块级定位。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strict_adapter.english_composite import (  # noqa: E402
    _split_option_markers_located,
    parse_ag_pool,
    parse_cloze_option_rows,
    parse_reading_stems,
)

# ---------------------------------------------------------------------------
# 合成用例
# ---------------------------------------------------------------------------


class TestSplitOptionMarkersLocated:
    def test_single_line_same_line_shared(self):
        parts = [("A. 甲 B. 乙 C. 丙 D. 丁", 7)]
        out = _split_option_markers_located(parts)
        assert out is not None
        assert [(lb, ls, le) for lb, _, ls, le in out] == [
            ("A", 7, 7), ("B", 7, 7), ("C", 7, 7), ("D", 7, 7),
        ]
        assert [t for _, t, _, _ in out] == ["甲", "乙", "丙", "丁"]

    def test_multi_line_options_real_ranges(self):
        parts = [("A. 甲", 10), ("B. 乙丙", 12), ("C. 丁", 13), ("D. 戊", 15)]
        out = _split_option_markers_located(parts)
        assert [(lb, ls, le) for lb, _, ls, le in out] == [
            ("A", 10, 10), ("B", 12, 12), ("C", 13, 13), ("D", 15, 15),
        ]

    def test_option_spanning_two_lines(self):
        parts = [("A. 甲甲", 5), ("乙乙 B. 丙", 6), ("C. 丁 D. 戊", 7)]
        out = _split_option_markers_located(parts)
        assert out is not None
        a, b, c, d = out
        assert a[0] == "A" and a[2] == 5 and a[3] == 6 and a[1] == "甲甲\n乙乙"
        assert b[0] == "B" and (b[2], b[3]) == (6, 6)
        assert (c[2], c[3]) == (7, 7) and (d[2], d[3]) == (7, 7)

    def test_missing_marker_fail_closed(self):
        assert _split_option_markers_located([("A. 甲 C. 乙", 1)]) is None

    def test_empty_text_fail_closed(self):
        assert _split_option_markers_located(
            [("A. 甲 B.  C. 丙 D. 丁", 1)]) is None


class TestClozeRows:
    def test_rows_carry_line_numbers(self):
        lines = [
            "11. A. 甲 B. 乙 C. 丙 D. 丁",
            "12. A. 戊 B. 己 C. 庚 D. 辛",
        ]
        rows, errors = parse_cloze_option_rows(lines, 1, 2, ["11", "12"])
        assert errors == []
        assert sorted(rows) == ["11", "12"]
        for want_ln, label in ((1, "11"), (2, "12")):
            for lb, txt, ls, le in rows[label]:
                assert txt
                assert ls == want_ln and le == want_ln
            assert [r[0] for r in rows[label]] == ["A", "B", "C", "D"]


class TestAgPool:
    def test_pool_carry_line_numbers(self):
        lines = ["", "A. 甲", "B. 乙", "C. 丙", "D. 丁", "E. 戊", "F. 己", "G. 庚"]
        pool, errors = parse_ag_pool(lines, 1, 8)
        assert errors == []
        assert [(lb, ls, le) for lb, _, ls, le in pool] == [
            ("A", 2, 2), ("B", 3, 3), ("C", 4, 4), ("D", 5, 5),
            ("E", 6, 6), ("F", 7, 7), ("G", 8, 8),
        ]
        assert all(t for _, t, _, _ in pool)


class TestReadingStems:
    def test_options_carry_line_numbers(self):
        lines = [
            "31. 题干甲？",
            "A. 选项一",
            "B. 选项二",
            "C. 选项三",
            "D. 选项四",
            "32. 题干乙？",
            "A. 选项五",
            "B. 选项六",
            "C. 选项七",
            "D. 选项八",
        ]
        stems, errors = parse_reading_stems(lines, 1, 10, ["31", "32"])
        assert errors == []
        s1, s2 = stems
        assert [(lb, ls, le) for lb, _, ls, le in s1.options] == [
            ("A", 2, 2), ("B", 3, 3), ("C", 4, 4), ("D", 5, 5),
        ]
        assert [(lb, ls, le) for lb, _, ls, le in s2.options] == [
            ("A", 7, 7), ("B", 8, 8), ("C", 9, 9), ("D", 10, 10),
        ]


# ---------------------------------------------------------------------------
# 真卷 U4/U9（PREIMPORT-02 封存输入；缺失则跳过）
# ---------------------------------------------------------------------------

RUN02 = Path(r"D:\Project\AITutors\Preprocessing\runs\qcore_preimport_02\english")
SRC_MD = RUN02 / "ocr_output" / "高三" / "英语" / "2019北京高考真题英语（教师版）(1).md"
MANIFEST = RUN02 / "manifest_output" / "2019北京高考真题英语（教师版）(1).manifest.json"

@pytest.mark.skipif(
    not (SRC_MD.is_file() and MANIFEST.is_file()),
    reason="PREIMPORT-02 english sealed inputs not found",
)
class TestRealEnglishOptionLocators:
    def _map_units(self):
        from strict_adapter.extract import load_source_lines
        from strict_adapter.mapper import MappingContext, map_unit

        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        lines = load_source_lines(str(SRC_MD))
        ctx = MappingContext(
            lines=lines,
            manifest=manifest,
            manifest_path=str(MANIFEST),
            manifest_name=MANIFEST.name,
            source_md_path=str(SRC_MD),
            source_md_name=SRC_MD.name,
            source_pdf_name="2019北京高考真题英语（教师版）(1).pdf",
            annotated_md_name=MANIFEST.with_suffix(".annotated.md").name,
            manifest_sha="0" * 64, source_md_sha="1" * 64,
            source_pdf_sha="c3ec6db14b5781296395c6e7bf0c5538dd12971073fc503adefe490e13895ebd",
            annotated_md_sha="3" * 64,
            manifest_bytes=MANIFEST.stat().st_size,
            source_md_bytes=SRC_MD.stat().st_size,
            source_pdf_bytes=1,
            annotated_md_bytes=1,
            image_by_line={a["line_no"]: a for a in manifest.get("image_assets", [])},
            paper_id="2019北京高考真题英语（教师版）(1)",
            subject="英语",
            run_id="r1-locator-test",
        )
        return {u["unit_id"]: map_unit(u, ctx) for u in manifest["units"]}

    def test_all_option_blocks_have_real_locators(self):
        """147 个选项块全部块级定位（U4-U9）；其余单元也不得缺定位。"""
        maps = self._map_units()
        src_len = len(SRC_MD.read_text(encoding="utf-8").splitlines())
        total = 0
        for uid, m in maps.items():
            for body in m.candidate.core.content.bodies:
                for o in body.options:
                    assert o.line_start is not None, (uid, o.label)
                    assert o.line_end is not None, (uid, o.label)
                    assert 1 <= o.line_start <= o.line_end <= src_len, (uid, o.label)
                    for blk in o.blocks:
                        total += 1
                        assert getattr(blk, "line_start", None) is not None, (uid, o.label)
                        assert getattr(blk, "line_end", None) is not None, (uid, o.label)
                        assert getattr(blk, "text", "").strip(), (uid, o.label)
        assert total == 147, total

    def test_u9_shared_pool_on_parent_only(self):
        maps = self._map_units()
        u9 = maps["U9"].candidate.core.content
        parent = [b for b in u9.bodies if b.parent_question_ref is None][0]
        assert [o.label for o in parent.options] == list("ABCDEFG")
        for o in parent.options:
            assert o.line_start == o.line_end and o.line_start >= 1
        for b in u9.bodies:
            if b.parent_question_ref is not None:
                assert b.options == ()
