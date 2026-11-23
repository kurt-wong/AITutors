"""Essay rules (no model essay required) and image-answer placeholder cleanup."""
from strict_adapter.mapper import _essay_content_complete, _essay_model_text_covered


def test_essay_with_stem_range_is_complete_without_model_essay():
    unit = {"stem_lines": [10, 20], "answers": []}
    log = {}
    assert _essay_content_complete(unit, log) is True
    # 范文存在与否只作为附加信息
    assert _essay_model_text_covered(unit, {}) is False


def test_essay_without_any_content_range_is_incomplete():
    assert _essay_content_complete({}, {}) is False


def test_essay_material_only_is_complete():
    assert _essay_content_complete({"material_lines": [5, 9]}, {}) is True
