"""extract 层测试：HTML 表格解析、子问印刷标签分段、行区提取。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strict_adapter.extract import (  # noqa: E402
    OptionSpec,
    extract_options,
    extract_range,
    parse_html_table,
    split_sub_segments,
)


class TestParseHtmlTable:
    def test_simple_grid(self):
        html = (
            "<table border=1><tr><td>a</td><td>b</td></tr>"
            "<tr><td>1</td><td>2</td></tr></table>"
        )
        rt = parse_html_table(html)
        assert rt.n_rows == 2
        assert rt.n_cols == 2
        assert {(c["row_index"], c["col_index"], c["content"]) for c in rt.cells} == {
            (0, 0, "a"),
            (0, 1, "b"),
            (1, 0, "1"),
            (1, 1, "2"),
        }

    def test_rowspan_colspan(self):
        html = (
            "<table><tr><td rowspan='2'>x</td><td>y</td></tr>"
            "<tr><td>z</td></tr></table>"
        )
        rt = parse_html_table(html)
        assert rt.n_rows == 2
        assert rt.n_cols == 2
        contents = {(c["row_index"], c["col_index"]): c["content"] for c in rt.cells}
        assert contents[(0, 0)] == "x"
        assert contents[(1, 1)] == "z"
        assert (1, 0) not in contents  # covered by rowspan anchor

    def test_inner_tags_stripped(self):
        html = "<table><tr><td><b>bold</b> tail</td></tr></table>"
        rt = parse_html_table(html)
        assert rt.cells[0]["content"] == "bold tail"


class TestExtractRange:
    def test_text_image_table_mix(self):
        lines = [
            "line one",
            "line two",
            "",
            '<div style="text-align: center;"><img src="imgs/a_b_c.jpg" alt="Image" width="10%" /></div>',
            "",
            "<table><tr><td>t1</td></tr></table>",
            "tail text",
        ]
        res = extract_range(lines, 1, 7)
        kinds = [b["kind"] for b in res.blocks]
        assert kinds == ["text", "image", "table", "text"]
        assert res.blocks[0]["text"] == "line one\nline two"
        assert res.blocks[0]["line_start"] == 1
        assert res.blocks[0]["line_end"] == 2
        assert res.blocks[1]["asset_id"] == "a_b_c"
        assert res.images[0].line_no == 4

    def test_empty_range(self):
        res = extract_range(["a"], 1, 1)
        assert res.blocks and res.blocks[0]["kind"] == "text"


class TestSubSegments:
    def test_label_split(self):
        lines = [
            "8. (14分)",
            "",
            "（1）第一问",
            "",
            "（2）第二问",
            "(3) 第三问",
        ]
        segs, lead = split_sub_segments(lines, 1, 6)
        assert [s[0] for s in segs] == ["（1）", "（2）", "(3)"]
        assert segs[0][1] == 3 and segs[0][2] == 4
        assert lead == [(1, 2)]

    def test_skip_ranges(self):
        lines = ["8.", "", "MATERIAL", "", "（1）q1", "（2）q2"]
        segs, lead = split_sub_segments(lines, 1, 6, skip=[(3, 3)])
        assert [s[0] for s in segs] == ["（1）", "（2）"]
        assert (3, 3) not in [(a, b) for a, b in lead]

    def test_no_labels_returns_lead_only(self):
        segs, lead = split_sub_segments(["intro", ""], 1, 2)
        assert segs == []
        assert lead == [(1, 2)]


class TestExtractOptions:
    def test_shared_table_options(self):
        lines = [
            "<table><tr><td></td><td>col</td></tr>"
            "<tr><td>A</td><td>内容A</td></tr>"
            "<tr><td>B</td><td>内容B</td></tr>"
            "<tr><td>C</td><td>内容C</td></tr>"
            "<tr><td>D</td><td>内容D</td></tr></table>",
        ]
        opts = [
            OptionSpec(label=l, start=1, end=1) for l in ("A", "B", "C", "D")
        ]
        out, table = extract_options(lines, opts)
        assert table is not None
        assert [o["label"] for o in out] == ["A", "B", "C", "D"]
        texts = ["".join(b["text"] for b in o["blocks"]) for o in out]
        assert texts[0] == "A内容A"
        assert texts[3] == "D内容D"

    def test_independent_ranges(self):
        lines = ["A. 甲", "", "B. 乙"]
        opts = [OptionSpec(label="A", start=1, end=1), OptionSpec(label="B", start=3, end=3)]
        out, table = extract_options(lines, opts)
        assert table is None
        assert out[0]["blocks"][0]["text"] == "A. 甲"
        assert out[1]["blocks"][0]["text"] == "B. 乙"
