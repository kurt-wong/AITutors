# -*- coding: utf-8 -*-
"""Candidate retrieval / fail-closed decision tests (synthetic catalog)."""

from __future__ import annotations

from conftest import make_bundle, write_snapshot
from tsc_compiler.photo.index import SearchIndex
from tsc_compiler.photo.search import _decide, search_text


def catalog_entry(question_id, revision_id, stem, *, image=False, table=False):
    return {
        "question_id": question_id,
        "revision_id": revision_id,
        "stem_text": stem,
        "material_text": "",
        "options_text": "甲 乙 丙 丁",
        "explanation_text": "官方解析",
        "has_image": image,
        "has_table": table,
        "has_math": True,
        "printed_number": "1",
        "question_type": "single_choice",
        "source_document_id": "synthetic",
    }


def test_index_ranks_the_exact_question_first() -> None:
    docs = [
        catalog_entry("q1", "r1", "已知集合 $ M=\\{1,2\\} $，则 $ M\\cup\\{3\\}= $（ ）"),
        catalog_entry("q2", "r2", "已知函数 $ f(x)=x^{2}+2x $ 的单调区间是（ ）"),
        catalog_entry("q3", "r3", "某工厂生产零件的合格率为 0.95，抽检 3 件（ ）"),
    ]
    index = SearchIndex.from_catalog(docs)
    hits = index.query("1. 已知集合 M={1,2}，则 M∪{3}=（ ）", limit=3)
    assert hits[0]["question_id"] == "q1"
    assert hits[0]["score"] > hits[1]["score"]


def test_decision_high_confidence_requires_margin_and_evidence() -> None:
    candidate = {
        "score": 0.8,
        "match_evidence": [{"type": "number", "value": "1"}] * 3,
        "llm": {"verdict": "match", "match": 0.9},
    }
    other = {"score": 0.4, "match_evidence": [], "llm": None}
    decision = _decide([candidate, other], llm_enabled=True, llm_error=None)
    assert decision["decision"] == "high_confidence"
    assert decision["may_teach"] is True


def test_decision_ambiguous_when_margins_are_thin() -> None:
    a = {"score": 0.7, "match_evidence": [{}] * 3, "llm": {"verdict": "match", "match": 0.9}}
    b = {"score": 0.66, "match_evidence": [{}] * 3, "llm": {"verdict": "match", "match": 0.9}}
    decision = _decide([a, b], llm_enabled=True, llm_error=None)
    assert decision["decision"] == "ambiguous"
    assert decision["may_teach"] is False


def test_decision_low_confidence_and_no_match() -> None:
    low = {"score": 0.2, "match_evidence": [], "llm": None}
    assert _decide([low], llm_enabled=False, llm_error=None)["decision"] == "low_confidence"
    # Real-phone handwriting/noise can score ~0.35; it must stay non-clickable.
    noisy = {"score": 0.40, "match_evidence": [], "llm": None}
    assert _decide([noisy], llm_enabled=False, llm_error=None)["decision"] == "low_confidence"
    assert _decide([], llm_enabled=False, llm_error=None)["decision"] == "no_match"


def test_llm_disagreement_blocks_auto_teach() -> None:
    a = {"score": 0.9, "match_evidence": [{}] * 4, "llm": {"verdict": "partial", "match": 0.5}}
    decision = _decide([a], llm_enabled=True, llm_error=None)
    assert decision["decision"] == "ambiguous"
    assert decision["may_teach"] is False


def test_search_text_returns_no_answers_and_rejects_gibberish(settings) -> None:
    bundles = [
        make_bundle(
            question_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            revision_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        )
    ]
    write_snapshot(settings, bundles)
    good = search_text(settings, bundles[0]["content"]["bodies"][0]["stem_blocks"][0]["text"], use_llm=False)
    assert good["candidates"]
    assert good["candidates"][0]["question_id"] == bundles[0]["question_id"]
    for candidate in good["candidates"]:
        assert "answer" not in candidate
        assert "explanation" not in candidate
    gibberish = search_text(settings, "zzzz qqqq xxxx 9999", use_llm=False)
    assert gibberish["decision"] in {"no_match", "low_confidence"}
    assert gibberish["may_teach"] is False
