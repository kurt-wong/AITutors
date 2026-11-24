"""Same-line option groups must be split per label, not copied wholesale."""
from strict_adapter.extract import OptionSpec, extract_options

# 2022 全国乙卷数学（理）Q2: A/B share line 21, C/D share line 23
MATH = [
    "",
    "2. 已知  $ z = 1 - 2i $，且  $ z + a\\overline{z} + b = 0 $，其中  $ a, b $ 为实数，则（）",
    "A. a=1, b=-2 B. a=-1, b=2",
    "",
    "C. a=1, b=2 D. a=-1, b=-2",
]


def test_two_option_groups_on_two_lines_are_split_per_label():
    opts = [
        OptionSpec("A", 3, 3),
        OptionSpec("B", 3, 3),
        OptionSpec("C", 5, 5),
        OptionSpec("D", 5, 5),
    ]
    out, _ = extract_options(MATH, opts)
    by = {o["label"]: "".join(b.get("text", "") for b in o["blocks"]).strip() for o in out}
    assert by["A"] == "a=1, b=-2"
    assert by["B"] == "a=-1, b=2"
    assert by["C"] == "a=1, b=2"
    assert by["D"] == "a=-1, b=-2"


def test_single_option_line_is_unchanged():
    lines = ["", "A. only", "B. second"]
    opts = [OptionSpec("A", 2, 2), OptionSpec("B", 3, 3)]
    out, _ = extract_options(lines, opts)
    by = {o["label"]: "".join(b.get("text", "") for b in o["blocks"]).strip() for o in out}
    # independent ranges keep the printed label; stripping happens at the body layer
    assert by == {"A": "A. only", "B": "B. second"}


# ---------------------------------------------------------------------------
# Sub-label + same-line options (2022 全国甲卷 完形 U16: ``（1）A.ownership …``)
# ---------------------------------------------------------------------------


def test_sublabel_and_options_on_one_line_keep_only_printed_label():
    from strict_adapter.mapper import _drop_option_line_blocks

    raw = [
        {
            "kind": "text",
            "text": "（1）A.ownership B.membership C.companionship D.leadership",
            "line_start": 461,
            "line_end": 461,
        }
    ]
    log: dict = {}
    out = _drop_option_line_blocks(
        raw,
        [(461, 461)],
        log,
        "u16/S1/stem",
        option_texts=["ownership", "membership", "companionship", "leadership"],
    )
    assert [b["text"] for b in out] == ["（1）"]
    assert out[0]["line_start"] == 461
    assert log["option_text_trimmed_from_stem"]


def test_option_label_line_is_still_dropped():
    from strict_adapter.mapper import _drop_option_line_blocks

    raw = [{"kind": "text", "text": "A. ownership", "line_start": 461, "line_end": 461}]
    assert _drop_option_line_blocks(raw, [(461, 461)], None, "u16/S1/stem") == []


def test_unrelated_text_inside_option_span_is_kept():
    from strict_adapter.mapper import _drop_option_line_blocks

    raw = [{"kind": "text", "text": "passage sentence", "line_start": 461, "line_end": 461}]
    out = _drop_option_line_blocks(
        raw, [(461, 461)], None, "u/s/stem", option_texts=["ownership"]
    )
    assert out == raw


def test_partial_option_text_is_not_trimmed():
    """Only a block that contains the whole option group is the option row."""
    from strict_adapter.mapper import _drop_option_line_blocks

    raw = [
        {
            "kind": "text",
            "text": "（1）A.ownership only",
            "line_start": 461,
            "line_end": 461,
        }
    ]
    out = _drop_option_line_blocks(
        raw,
        [(461, 461)],
        None,
        "u/s/stem",
        option_texts=["ownership", "membership", "companionship", "leadership"],
    )
    assert out == raw
