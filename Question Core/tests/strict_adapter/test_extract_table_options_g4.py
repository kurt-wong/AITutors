"""G4-F2 回归：共享 HTML 表格行区的选项切分策略 A/B/C。

背景：G4 dry-run S09 U4 / S11 U12 因表格单元格选项（标签前缀式 / 标签→引用式）
被抽取为空文本块 → ContentAuditError。修复后按确定性策略提取。
"""

from __future__ import annotations

from strict_adapter.extract import OptionSpec, extract_options, parse_html_table  # noqa: E402


def _opts(*labels):
    return [OptionSpec(label=lb, start=1, end=1) for lb in labels]


class TestTableOptionStrategyA:
    def test_row_label_cells_unchanged(self):
        html = (
            "<table><tr><td>A</td><td>选项甲</td></tr>"
            "<tr><td>B</td><td>选项乙</td></tr></table>"
        )
        lines = [html]
        out, tables = extract_options(lines, _opts("A", "B"))
        assert tables
        assert out[0]["label"] == "A"
        assert [b["text"] for b in out[0]["blocks"]] == ["A", "选项甲"]
        assert [b["text"] for b in out[1]["blocks"]] == ["B", "选项乙"]


class TestTableOptionStrategyB:
    def test_label_prefixed_cells_with_same_col_images(self):
        """S09 U4 形态：2×4 表格，行1=选项文本（标签前缀），行2=同列装置图。"""
        imgs = [f"imgs/opt_{i}.jpg" for i in range(4)]
        tds_text = "".join(
            f"<td>{lb}. text{i}</td>" for i, lb in enumerate("ABCD")
        )
        tds_img = "".join(f'<td><img src="{src}"></td>' for src in imgs)
        html = f"<table><tr>{tds_text}</tr><tr>{tds_img}</tr></table>"
        out, tables = extract_options([html], _opts("A", "B", "C", "D"))
        assert tables
        a_blocks = out[0]["blocks"]
        assert a_blocks[0] == {
            "kind": "text",
            "text": "text0",
            "line_start": 1,
            "line_end": 1,
        }
        assert a_blocks[1]["kind"] == "image"
        assert a_blocks[1]["asset_id"] == "opt_0"
        assert out[3]["blocks"][1]["asset_id"] == "opt_3"
        # 表格单元格图片源已被解析
        assert tables[0].cells[4]["image_srcs"] == ["imgs/opt_0.jpg"]

    def test_label_prefix_requires_punct(self):
        html = "<table><tr><td>AB text</td></tr></table>"
        out, _ = extract_options([html], _opts("A", "B"))
        # 策略 B/C 均不命中 → 既有空块行为
        assert out[0]["blocks"] == [{"kind": "text", "text": "", "line_start": 1, "line_end": 1}]


class TestTableOptionStrategyC:
    def test_pair_reference_row(self):
        """S11 U12 形态：数据表 + 末行 'A.①B.② C.③D.④'。"""
        html = (
            "<table>"
            "<tr><td>组别</td><td>实验设计</td></tr>"
            "<tr><td>①</td><td>设计一</td></tr>"
            "<tr><td colspan=\"2\">A.①B.② C.③D.④</td></tr>"
            "</table>"
        )
        out, tables = extract_options([html], _opts("A", "B", "C", "D"))
        assert tables
        texts = [o["blocks"][0]["text"] for o in out]
        assert texts == ["①", "②", "③", "④"]

    def test_pair_reference_missing_label_falls_through(self):
        html = (
            "<table><tr><td colspan=\"2\">A.①B.② C.③</td></tr></table>"
        )
        out, _ = extract_options([html], _opts("A", "B", "C", "D"))
        assert all(
            o["blocks"] == [{"kind": "text", "text": "", "line_start": 1, "line_end": 1}]
            for o in out
        )


class TestTableOptionAssets:
    def test_image_cells_parsed(self):
        html = '<table><tr><td>x<img src="imgs/a_b.jpg"></td></tr></table>'
        rt = parse_html_table(html)
        assert rt.cells[0]["image_srcs"] == ["imgs/a_b.jpg"]
        assert rt.cells[0]["content"] == "x"
