"""D8 root cause: declared-answer representation must not depend on marker syntax."""
from question_core.contracts.v1.candidate import (
    _declared_tokens,
    _match_declared_set,
)
from question_core.contracts.v1.answer import CompositeAnswer, CompositeSubAnswer, FillBlankAnswer


def _composite(*groups):
    return CompositeAnswer(
        answer_value=tuple(
            CompositeSubAnswer(
                sub_label=f"（{i}）",
                answer_value=FillBlankAnswer(
                    answer_value=tuple(vals),
                    grading_rule="manual",
                    completeness="full",
                    visibility="review_only",
                ),
                grading_rule="exact",
                completeness="full",
                visibility="review_only",
            )
            for i, vals in enumerate(groups, start=1)
        ),
        grading_rule="exact",
        completeness="full",
        visibility="review_only",
    )


def test_circled_markers_match_parenthesised_sub_labels():
    ans = _composite(["$ A_{1} $", "60"], ["100"], ["无"])
    assert _match_declared_set(ans, "①. $A_{1} $ ②.60 ③.100 ④.无") is True


def test_full_width_semicolon_separator_is_tolerated():
    ans = _composite(["$ 0.06m^{2} $", "$ 0.39m^{3} $"], ["0.97"], ["1209m^{3}"])
    assert _match_declared_set(ans, "（1）$ 0.06m^{2} $；$ 0.39m^{3} $（2）0.97（3）1209m^{3}") is True


def test_prose_answer_split_by_punctuation_still_matches():
    prose = "第一处主语“我”只出现一次，表明说话人语速极快；第二处主语“你”再三出现"
    ans = _composite(["顺理成章"], ["难以言喻"], ["迫不及待"], [prose])
    declared = "17.①顺理成章 ②难以言喻 ③迫不及待 18." + prose
    assert _match_declared_set(ans, declared) is True


def test_absent_value_is_rejected():
    ans = _composite(["顺理成章"], ["难以言喻"])
    assert _match_declared_set(ans, "①顺理成章 ②完全不存在的答案") is False


def test_tokens_drop_marker_punctuation():
    toks = _declared_tokens("①. $A_{1} $ ②.60")
    assert toks and all(not t.startswith(".") for t in toks)


def test_missing_fragments_are_rejected_when_tree_is_short():
    ans = _composite(["A"])
    assert _match_declared_set(ans, "①A ②B ③C") is False


def test_single_short_leaf_cannot_cover_multiple_fragments():
    ans = _composite(["答案"])
    assert _match_declared_set(ans, "①答案 ②解析") is False


def test_long_prose_leaf_may_be_reused_for_fragments_inside_it():
    ans = _composite(["第一处主语“我”只出现一次，表明说话人语速极快，情绪急迫，表明照相时的紧张"])
    declared = "①第一处主语“我”只出现一次 ②表明说话人语速极快 ③情绪急迫"
    assert _match_declared_set(ans, declared) is True


def test_math_span_with_comma_is_one_token():
    """数学 p20 回归：$ (0,-2) $ 不能被逗号切成 (0 和 -2)。"""
    toks = _declared_tokens("（1）$ \\frac{y^{2}}{4}+\\frac{x^{2}}{3}=1 $（2）$ (0,-2) $")
    assert any("(0,-2)" in t for t in toks), toks


def test_coordinate_math_span_matches_its_leaf():
    ans = _composite(["$ \\frac{y^{2}}{4}+\\frac{x^{2}}{3}=1 $"], ["$ (0,-2) $"])
    assert _match_declared_set(ans, "（1）$ \\frac{y^{2}}{4}+\\frac{x^{2}}{3}=1 $（2）$ (0,-2) $") is True
