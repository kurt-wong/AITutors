"""Sub/superscript semantics must survive text extraction (Owner 4.2)."""
from strict_adapter.extract import visible_text


def test_sub_sup_become_underscore_caret():
    assert visible_text("大π键(Π<sub>3</sub><sup>4</sup>)") == "大π键(Π_3^4)"


def test_nested_markup_inside_sub_sup_is_preserved_as_text():
    assert visible_text("x<sub>2</sub>") == "x_2"


def test_layout_tags_are_still_stripped():
    assert visible_text("<div>text</div>") == "text"


def test_plain_math_less_than_is_not_treated_as_tag():
    # 数学里的裸 < 不能被吞掉
    assert "K_{sp}(A)<K_{sp}(B)" in visible_text("已知 $K_{sp}(A)<K_{sp}(B)$")
