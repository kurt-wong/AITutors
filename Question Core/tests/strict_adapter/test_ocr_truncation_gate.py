# -*- coding: utf-8 -*-
"""OCR↔PDF 截断门（QCORE-OCR-TRUNCATION-GATE-01 / MIMO ②a）。

只查「OCR 行是 PDF 行的严格前缀」这一种形态（历史唯一真缺陷：2022 甲卷 15
选项 B 被截断）；重复行不做判定（假阳性高，由 Admission 规则 G 与人工负责）。
门只作用于新导入的卷，不回溯已发布数据。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strict_adapter.generic_executor import (  # noqa: E402
    find_truncated_lines,
    ocr_question_area,
)


def test_truncated_ocr_line_is_detected():
    md = [
        "B. The more time you spend in any given co",
        "C. Mexicans consider it inappropriate to eat with utensils",
    ]
    pdf = [
        "B.The more time you spend in any given country",
        "C.Mexicans consider it inappropriate to eat with utensils",
    ]
    hits = find_truncated_lines(md, pdf)
    assert len(hits) == 1, hits
    assert hits[0]["line"] == 1
    assert "country" in hits[0]["pdf"]


def test_exact_line_is_not_flagged():
    md = ["B. The more time you spend in any given country"]
    pdf = ["B.The more time you spend in any given country"]
    assert find_truncated_lines(md, pdf) == []


def test_short_line_is_not_flagged():
    md = ["A. Odd word"]
    pdf = ["A.Odd wording continues here"]
    assert find_truncated_lines(md, pdf) == []


def test_pdf_longer_but_not_prefix_is_not_flagged():
    md = ["The quick brown fox jumps over"]
    pdf = ["The quick brown cat jumps over the lazy dog"]
    assert find_truncated_lines(md, pdf) == []


def test_media_and_markup_lines_are_skipped():
    md = [
        '<div style="text-align: center;"><img src="imgs/x.jpg" /></div>',
        "![image](imgs/y.jpg)",
    ]
    pdf = ["some pdf line that begins with a div wrapper text long enough"]
    assert find_truncated_lines(md, pdf) == []


def test_answer_area_is_excluded():
    md = [
        "B. The more time you spend in any given co",
        "参考答案",
        "【解析】B.The more time you spend in any given country",
    ]
    pdf = ["B.The more time you spend in any given country"]
    area = ocr_question_area(md)
    assert [ln for ln, _ in area] == [1]
    hits = find_truncated_lines(md, pdf)
    assert len(hits) == 1 and hits[0]["line"] == 1
