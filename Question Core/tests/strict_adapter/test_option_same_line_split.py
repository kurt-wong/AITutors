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
