"""Deterministic content extraction from the sealed source OCR markdown.

所有提取只做字面/机械操作：按 Manifest 已声明的行区取文本；`<img>` 行解析为
ImageBlock；`<table>` HTML 确定性解析为 TableBlock；Composite 子问只按题面
印刷标签（行首 （n）/(n)）分段并记录切点。禁止语义判断、禁止补全、禁止改写。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 源文件
# ---------------------------------------------------------------------------


def load_source_lines(md_path: str) -> list[str]:
    with open(md_path, "r", encoding="utf-8") as f:
        return f.read().splitlines()


# ---------------------------------------------------------------------------
# HTML 表格 → TableBlock 参数（确定性解析，无语义判断）
# ---------------------------------------------------------------------------

_TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
_TD_RE = re.compile(r"<(td|th)\b([^>]*)>(.*?)</\1>", re.S | re.I)
_ATTR_RE = re.compile(r"(rowspan|colspan)\s*=\s*[\"']?(\d+)", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_IMG_RE = re.compile(r"<img\b[^>]*?src\s*=\s*[\"']([^\"']+)[\"'][^>]*?>", re.I)
_IMG_ALT_RE = re.compile(r"alt\s*=\s*[\"']([^\"']*)[\"']", re.I)
_IMG_DIV_RE = re.compile(r"^\s*<div[^>]*>\s*<img\b", re.I)


def _strip_tags(html: str) -> str:
    return _TAG_RE.sub("", html).strip()


@dataclass
class RawTable:
    n_rows: int
    n_cols: int
    cells: list[dict]  # {row_index, col_index, content, rowspan, colspan, is_header}


def parse_html_table(html: str) -> RawTable:
    """把 OCR md 中的 HTML 表格解析为网格（含 rowspan/colspan 占位展开校验）。"""
    raw_cells: list[dict] = []
    occupied: set[tuple[int, int]] = set()
    n_rows = 0
    max_col = 0
    for r, tr in enumerate(_TR_RE.findall(html)):
        n_rows += 1
        c = 0
        for tag, attrs, inner in _TD_RE.findall(tr):
            while (r, c) in occupied:
                c += 1
            rowspan, colspan = 1, 1
            for name, val in _ATTR_RE.findall(attrs):
                if name.lower() == "rowspan":
                    rowspan = max(1, int(val))
                else:
                    colspan = max(1, int(val))
            raw_cells.append(
                {
                    "row_index": r,
                    "col_index": c,
                    "content": _strip_tags(inner),
                    "rowspan": rowspan,
                    "colspan": colspan,
                    "is_header": tag.lower() == "th" or r == 0,
                }
            )
            for dr in range(rowspan):
                for dc in range(colspan):
                    occupied.add((r + dr, c + dc))
            c += colspan
        max_col = max(max_col, c)
    if not raw_cells or n_rows == 0:
        raise ValueError("html table produced no cells")
    return RawTable(n_rows=n_rows, n_cols=max_col, cells=raw_cells)


# ---------------------------------------------------------------------------
# 行区 → ContentBlock 序列（字面提取）
# ---------------------------------------------------------------------------


@dataclass
class ExtractedImage:
    line_no: int
    src: str
    alt: str | None
    asset_id: str


@dataclass
class ExtractResult:
    blocks: list = field(default_factory=list)  # list[dict]，kind/text/image/table 原料
    images: list[ExtractedImage] = field(default_factory=list)
    tables: list[RawTable] = field(default_factory=list)
    segments: list[tuple[int, int, str]] = field(default_factory=list)  # (s, e, text)


def _asset_id_from_src(src: str) -> str:
    name = src.rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0]
    return stem


def extract_range(
    lines: list[str], start: int, end: int
) -> ExtractResult:
    """提取 1-based 闭区间 [start, end] 的内容块（字面，无改写）。

    - `<div…><img …>` 行 → image 块
    - `<table…>` 起（至 `</table>`）→ table 块（确定性 HTML 解析）
    - 其余非空行 → 连续段合并为 text 块（保留换行与行号范围）
    """
    res = ExtractResult()
    if start is None or end is None:
        return res
    buf: list[str] = []
    buf_start: int | None = None
    last_line_no = start

    def flush_text() -> None:
        nonlocal buf, buf_start
        if buf and buf_start is not None:
            res.blocks.append(
                {
                    "kind": "text",
                    "text": "\n".join(buf),
                    "line_start": buf_start,
                    "line_end": last_line_no,
                }
            )
            res.segments.append((buf_start, last_line_no, "\n".join(buf)))
        buf = []
        buf_start = None

    i = start
    while i <= end:
        raw = lines[i - 1] if i - 1 < len(lines) else ""
        stripped = raw.strip()
        if _IMG_DIV_RE.match(stripped) or (
            stripped.startswith("<div") and "<img" in stripped
        ):
            flush_text()
            m = _IMG_RE.search(raw)
            if m:
                alt_m = _IMG_ALT_RE.search(raw)
                res.images.append(
                    ExtractedImage(
                        line_no=i,
                        src=m.group(1),
                        alt=alt_m.group(1) if alt_m else None,
                        asset_id=_asset_id_from_src(m.group(1)),
                    )
                )
                res.blocks.append(
                    {"kind": "image", "asset_id": _asset_id_from_src(m.group(1)),
                     "alt_text": alt_m.group(1) if alt_m else None,
                     "line_start": i, "line_end": i}
                )
            i += 1
            continue
        if stripped.lower().startswith("<table"):
            flush_text()
            table_html = raw
            j = i
            while "</table>" not in table_html.lower() and j < end:
                j += 1
                table_html += "\n" + (lines[j - 1] if j - 1 < len(lines) else "")
            rt = parse_html_table(table_html)
            res.tables.append(rt)
            res.blocks.append(
                {
                    "kind": "table",
                    "table": rt,
                    "line_start": i,
                    "line_end": j,
                }
            )
            i = j + 1
            continue
        if stripped == "":
            flush_text()
            i += 1
            continue
        if buf_start is None:
            buf_start = i
        buf.append(raw)
        last_line_no = i
        i += 1
    flush_text()
    return res


# ---------------------------------------------------------------------------
# Composite 子问印刷标签分段
# ---------------------------------------------------------------------------

_SUB_LABEL_RE = re.compile(r"^[（(]\s*(\d+)\s*[）)]")


def split_sub_segments(
    lines: list[str],
    start: int,
    end: int,
    skip: list[tuple[int, int]] | None = None,
) -> tuple[list[tuple[str, int, int]], list[tuple[int, int]]]:
    """按印刷子问标签切分 [start, end]。

    返回 ([(label, seg_start, seg_end), ...], lead_ranges)：
    label 形如 "（1）"（保留源文全角/半角形态）；lead_ranges 是标签段之外
    （含题干引导行、跳过区之外）的行区，属于父体。
    """
    skip = skip or []

    def skipped(ln: int) -> bool:
        return any(a <= ln <= b for a, b in skip)

    segs: list[tuple[str, int, int]] = []
    lead: list[tuple[int, int]] = []
    cur: tuple[str, int, int] | None = None
    open_lead: list[int] = []

    def flush_lead() -> None:
        nonlocal open_lead
        if open_lead:
            lead.append((open_lead[0], open_lead[-1]))
            open_lead = []

    def flush_cur() -> None:
        nonlocal cur
        if cur is not None:
            segs.append(cur)
            cur = None

    for ln in range(start, end + 1):
        if skipped(ln):
            flush_cur()
            flush_lead()
            continue
        raw = lines[ln - 1] if ln - 1 < len(lines) else ""
        m = _SUB_LABEL_RE.match(raw.strip())
        if m:
            flush_lead()
            flush_cur()
            cur = (m.group(0), ln, ln)
        elif cur is not None:
            cur = (cur[0], cur[1], ln)
        else:
            if raw.strip() != "":
                open_lead.append(ln)
            elif open_lead:
                open_lead.append(ln)
    flush_cur()
    flush_lead()
    # 收尾：lead 尾部空行并入前段的处理已在 open_lead 逻辑内（空行保留行号）
    return segs, lead


# ---------------------------------------------------------------------------
# 选项提取（含 Q3 型「多选项共享同一 HTML 表格行区」情形）
# ---------------------------------------------------------------------------


@dataclass
class OptionSpec:
    label: str
    start: int
    end: int


def extract_options(
    lines: list[str], options: list[OptionSpec]
) -> tuple[list[dict], RawTable | None]:
    """按 Manifest 逐选项行区提取。

    - 常规：每选项独立行区 → 逐行字面文本。
    - 共享行区（多个选项同一 [s,e]，且该行区是 HTML 表格）：解析表格，
      以印刷标签匹配表格行；每选项 blocks = 该行各单元格文本；同时返回
      完整 RawTable 供父体 stem_blocks 保留整表网格。
    """
    if not options:
        return [], None
    spans = {(o.start, o.end) for o in options}
    shared = len(spans) == 1 and len(options) > 1
    table: RawTable | None = None
    out: list[dict] = []

    if shared:
        s, e = next(iter(spans))
        res = extract_range(lines, s, e)
        if res.tables:
            table = res.tables[0]
        for opt in options:
            row_cells: list[dict] = []
            if table is not None:
                label_norm = opt.label.strip().upper()
                row_idx = None
                for cell in table.cells:
                    if cell["content"].strip().upper().rstrip("．.、") == label_norm:
                        row_idx = cell["row_index"]
                        break
                if row_idx is not None:
                    row_cells = [
                        c for c in table.cells if c["row_index"] == row_idx
                    ]
            if row_cells:
                blocks = [
                    {
                        "kind": "text",
                        "text": c["content"],
                        "line_start": s,
                        "line_end": e,
                    }
                    for c in row_cells
                ]
                if not blocks:
                    blocks = [
                        {"kind": "text", "text": "", "line_start": s, "line_end": e}
                    ]
            else:
                blocks = [
                    {"kind": "text", "text": "", "line_start": s, "line_end": e}
                ]
            out.append({"label": opt.label, "blocks": blocks, "line_start": s, "line_end": e})
        return out, table

    for opt in options:
        res = extract_range(lines, opt.start, opt.end)
        blocks = res.blocks or [
            {"kind": "text", "text": "", "line_start": opt.start, "line_end": opt.end}
        ]
        out.append(
            {
                "label": opt.label,
                "blocks": blocks,
                "line_start": opt.start,
                "line_end": opt.end,
            }
        )
    return out, table
