"""C2: essay completeness must not pass vacuously when no answer is located."""
from strict_adapter.mapper import _essay_model_text_covered


def test_essay_without_any_located_answer_is_not_covered():
    unit = {"explanation_lines": [10, 40], "answers": []}
    log = {}
    assert _essay_model_text_covered(unit, log) is False
    assert log.get("essay_no_located_answer") is True


def test_essay_answer_without_evidence_lines_is_not_covered():
    unit = {"explanation_lines": [10, 40], "answers": [{"slot_id": None, "evidence_lines": None}]}
    assert _essay_model_text_covered(unit, {}) is False


def test_essay_answer_inside_explanation_is_covered():
    unit = {"explanation_lines": [10, 40], "answers": [{"slot_id": None, "evidence_lines": [12, 20]}]}
    assert _essay_model_text_covered(unit, {}) is True


def test_essay_answer_outside_explanation_is_not_covered():
    unit = {"explanation_lines": [10, 40], "answers": [{"slot_id": None, "evidence_lines": [50, 60]}]}
    log = {}
    assert _essay_model_text_covered(unit, log) is False
    assert log.get("essay_uncovered_items")
