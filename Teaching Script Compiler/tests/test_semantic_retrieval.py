# -*- coding: utf-8 -*-
"""Semantic Retrieval V1 decision contract (no torch required)."""

from __future__ import annotations

from tsc_compiler.semantic.retrieval import SemanticConfig, SemanticIndex


def _entry(qid: str, stem: str, *, subject: str = "数学", number: str = "1") -> dict:
    return {
        "question_id": qid,
        "revision_id": qid + "-r1",
        "subject": subject,
        "question_type": "single_choice",
        "printed_number": number,
        "source_document_id": f"paper-{qid}",
        "stem_text": stem,
        "material_text": "",
        "options_text": "A. 1 B. 2 C. 3 D. 4",
        "explanation_text": "",
        "has_image": False,
        "has_table": False,
        "has_math": True,
        "published": True,
    }


def test_exact_identity_on_identical_text() -> None:
    stem = "已知函数 $f(x)=x^2-4x+3$，求 $f(x)$ 在区间 $[0,3]$ 上的最小值。"
    index = SemanticIndex.from_catalog([_entry("q1", stem), _entry("q2", "完全不同的另一道物理题，关于电场强度。")])
    result = index.search(stem)
    assert result["decision"] == "exact"
    assert result["exact"]["question_id"] == "q1"


def test_identical_duplicates_are_one_identity() -> None:
    stem = "已知函数 $f(x)=x^2-4x+3$，求 $f(x)$ 在区间 $[0,3]$ 上的最小值。"
    index = SemanticIndex.from_catalog([_entry("q1", stem), _entry("q2", stem)])
    result = index.search(stem)
    # Same content under two IDs: retrieval may teach the top one, but it must
    # tag the duplicate group so identity can be merged upstream.
    assert result["decision"] == "exact"
    assert result["duplicate_group"] is True


def test_unrelated_query_is_unknown() -> None:
    index = SemanticIndex.from_catalog(
        [_entry("q1", "已知函数 $f(x)=x^2-4x+3$，求最小值。"), _entry("q2", "电场中带电粒子的运动。")]
    )
    result = index.search("《红楼梦》中贾宝玉的人物形象分析。", top_k=5)
    assert result["decision"] == "unknown"
    assert result["exact"] is None


def test_expanded_corpus_has_an_exact_ceiling() -> None:
    # Adding unrelated documents must not turn an unrelated query into exact.
    docs = [_entry(f"q{i}", f"第{i}道数学题：求函数 $y=x^{i}$ 的导数。") for i in range(1, 20)]
    index = SemanticIndex.from_catalog(docs, config=SemanticConfig(top_k=5))
    result = index.search("请分析《乡土中国》中差序格局的概念。")
    assert result["decision"] == "unknown"


def test_config_thresholds_are_reported() -> None:
    index = SemanticIndex.from_catalog([_entry("q1", "已知函数 $f(x)=x^2$，求导。")])
    result = index.search("已知函数 $f(x)=x^2$，求导。")
    assert result["thresholds"]["exact_dense"] == 0.84
    assert result["dense_enabled"] is False  # no embedder supplied -> lexical fallback
