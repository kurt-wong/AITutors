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
# AF2-A：可见文本恢复只剥已知版式标签（div/span/br 等）——数学不等式里的裸
# `<`（如 $K_{sp}(A)<K_{sp}(B)$）绝不能按标签吞掉；实体（&gt; 等）保持原样。
_VISIBLE_TAG_RE = re.compile(
    r"<\s*/?\s*(?:div|span|br|p|center|b|i|em|strong|font|hr|sup|sub|u|s)\b[^>]*>",
    re.I,
)
_IMG_RE = re.compile(r"<img\b[^>]*?src\s*=\s*[\"']([^\"']+)[\"'][^>]*?>", re.I)
_IMG_ALT_RE = re.compile(r"alt\s*=\s*[\"']([^\"']*)[\"']", re.I)
_IMG_DIV_RE = re.compile(r"^\s*<div[^>]*>\s*<img\b", re.I)


def visible_text(raw: str) -> str:
    """剥版式标签留可见文本（AF2-A）；`<br>` 转行；其余标签直接去除。

    Owner 2026-11-22（4.2）：`<sub>/<sup>` 承载语义（下标/上标），不能当版式
    标签直接剥掉——先转成 `_x` / `^x` 再清理其余标签，避免 `Π₃⁴ → Π34`。
    """
    s = re.sub(r"<\s*br\s*/?\s*>", "\n", raw, flags=re.I)
    s = re.sub(
        r"<\s*sub\b[^>]*>(.*?)<\s*/\s*sub\s*>",
        lambda m: "_" + (m.group(1) or ""),
        s,
        flags=re.I | re.S,
    )
    s = re.sub(
        r"<\s*sup\b[^>]*>(.*?)<\s*/\s*sup\s*>",
        lambda m: "^" + (m.group(1) or ""),
        s,
        flags=re.I | re.S,
    )
    return _VISIBLE_TAG_RE.sub("", s)


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
                    "image_srcs": _IMG_RE.findall(inner),
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
        vis = visible_text(raw)
        if vis.strip():
            buf.append(vis)
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


def _split_inline_shared_options(
    lines: list[str], s: int, e: int, options: list[OptionSpec]
) -> dict[str, dict] | None:
    """同文本区域多选项（非 HTML 表格）按印刷标记切分（R1 B1）。

    返回 label -> {"text", "line_start", "line_end"}；标记序列与
    options 标签顺序不一致或任一标记缺失时返回 None（fail-closed，
    不产出空选项、不合并选项内容）。
    """
    joined = "\n".join(lines[s - 1:e])
    marks: list[tuple[str, int, int]] = []
    pos = 0
    for opt in options:
        pat = re.compile(r"(?:^|\s)(" + re.escape(opt.label) + r")[.．、]\s*")
        m = pat.search(joined, pos)
        if m is None:
            return None
        marks.append((opt.label, m.start(1), m.end()))
        pos = m.end()
    out: dict[str, dict] = {}
    for i, (label, _ls_off, start_off) in enumerate(marks):
        end_off = marks[i + 1][1] if i + 1 < len(marks) else len(joined)
        raw = joined[start_off:end_off]
        text = raw.strip()
        if not text:
            return None
        first = start_off + (len(raw) - len(raw.lstrip()))
        last = first + len(text) - 1
        line_start = s + joined[:first].count("\n")
        line_end = s + joined[:last].count("\n")
        out[label] = {"text": text, "line_start": line_start, "line_end": line_end}
    return out


_FOOTER_RE = re.compile(
    r"^\s*(?:第\s*\d+\s*页\s*[/_／]\s*共\s*\d+\s*页|←\s*更多资料|更多资料|"
    r"交互课程径课堂\s*[：:]?)\s*$"
)


def _drop_footer_lines(text: str) -> str:
    """剔除版面页脚行（第N页/共M页）——页脚不得成为选项正文（G4-R1 R1-05）。"""
    kept = [ln for ln in text.split("\n") if not _FOOTER_RE.match(ln)]
    return "\n".join(kept).strip()


def _norm_cell_label(text: str) -> str:
    return (text or "").strip().upper().rstrip("．.、")


def _table_rows(rt: RawTable) -> list[list[dict]]:
    rows: dict[int, list[dict]] = {}
    for c in rt.cells:
        rows.setdefault(c["row_index"], []).append(c)
    return [rows[k] for k in sorted(rows)]


def _label_row_map(tables: list[RawTable], labels: list[str]) -> dict[str, list[dict]] | None:
    """策略 A：某单元格恰为选项标签 → 该行整行为该选项内容（多表扫描）。"""
    want = {lb.strip().upper(): lb for lb in labels}
    found: dict[str, list[dict]] = {}
    for rt in tables:
        for row in _table_rows(rt):
            for c in row:
                key = _norm_cell_label(c["content"])
                if key in want and want[key] not in found:
                    found[want[key]] = row
    if all(lb in found for lb in labels):
        return found
    return None


def _expand_label_rows(
    tables: list[RawTable], found: dict[str, list[dict]]
) -> dict[str, list[dict]] | None:
    """标签列扩展（G4-R1）：表格自带标签列（首格为 A-H 字面标签）且声明标签
    为其子集（S12 U5 只声明 A）→ 按行序收齐连续标签行。仅当合并后标签恰为
    连续 A..X 且无重复才成立（确定性，无猜测）。
    """
    taken = {id(c) for row in found.values() for c in row}
    extras: list[tuple[str, list[dict]]] = []
    for rt in tables:
        for row in _table_rows(rt):
            if any(id(c) in taken for c in row):
                continue
            first = _norm_cell_label(row[0]["content"]) if row else ""
            if re.fullmatch(r"[A-H]", first):
                extras.append((first, row))
    if not extras:
        return None
    merged = list(found.items()) + extras
    order = [lb for lb, _ in merged]
    want = [chr(ord("A") + i) for i in range(len(order))]
    if sorted(order) == want and len(set(order)) == len(order):
        return dict(merged)
    return None


def _table_option_rows(
    tables: list[RawTable], options: list[OptionSpec], s: int, e: int
) -> tuple[list[tuple[str, list[dict]]] | None, int]:
    """共享/区域 HTML 表格的选项切分（确定性，全有或全无）。

    返回 (rows, consumed_cells)；rows=None 表示全部策略未命中。
    策略顺序：
      A：行标签单元格（标签列+内容列版式，多表扫描）+ 标签列扩展；
      B：标签前缀单元格（"A. Cl₂收集…"）+ 同列其他行 <img>；
      C：标签→引用 清单单元格（"A.①B.② C.③D.④"）。
    """
    labels = [o.label for o in options]
    consumed = 0

    # ---- 策略 A：行标签单元格（+标签列扩展） ----
    found = _label_row_map(tables, labels)
    if found is not None:
        expanded = _expand_label_rows(tables, found)
        if expanded is not None:
            found = expanded
        rows = []
        for lb, row in found.items():
            blocks: list[dict] = []
            for c in row:
                consumed += 1
                txt = _drop_footer_lines(c["content"])
                if txt:
                    blocks.append({"kind": "text", "text": txt, "line_start": s, "line_end": e})
                for src in c.get("image_srcs") or []:
                    blocks.append({
                        "kind": "image", "asset_id": _asset_id_from_src(src),
                        "alt_text": None, "line_start": s, "line_end": e,
                    })
            if blocks:
                rows.append((lb, blocks))
        if rows:
            return rows, consumed

    # ---- 策略 B：标签前缀单元格（+同列图片） ----
    rows = []
    used_cells: set = set()
    ok = True
    for opt in options:
        label_raw = opt.label.strip()
        hit = None
        for rt in tables:
            for cell in rt.cells:
                key = (id(rt), cell["row_index"], cell["col_index"])
                if key in used_cells:
                    continue
                m = re.match(
                    r"^\s*" + re.escape(label_raw) + r"\s*[.．、:：]", cell["content"], re.I
                )
                if m:
                    hit = (rt, cell, m)
                    break
            if hit:
                break
        if hit is None:
            ok = False
            break
        rt, cell, m = hit
        used_cells.add((id(rt), cell["row_index"], cell["col_index"]))
        consumed += 1
        text = _drop_footer_lines(cell["content"][m.end():])
        if not text:
            ok = False
            break
        blocks = [{"kind": "text", "text": text, "line_start": s, "line_end": e}]
        for other in rt.cells:
            if other["col_index"] == cell["col_index"] and other["row_index"] != cell["row_index"]:
                for src in other.get("image_srcs") or []:
                    blocks.append({
                        "kind": "image", "asset_id": _asset_id_from_src(src),
                        "alt_text": None, "line_start": s, "line_end": e,
                    })
        rows.append((opt.label, blocks))
    if ok:
        return rows, consumed

    # ---- 策略 C：标签→引用 清单单元格 ----
    for rt in tables:
        for cand in rt.cells:
            content = cand["content"]
            parsed: list[tuple[str, str]] = []
            pos = 0
            ok_c = True
            for i, opt in enumerate(options):
                label_raw = opt.label.strip()
                remain = [re.escape(o.label.strip()) for o in options[i + 1:]]
                lookahead = (
                    r"(?=\s*(?:" + "|".join(remain) + r")[.．、:：]|$)" if remain else r"$"
                )
                m = re.search(
                    re.escape(label_raw) + r"\s*[.．、:：]?\s*(.+?)" + lookahead,
                    content[pos:],
                    re.I,
                )
                if m is None or not m.group(1).strip():
                    ok_c = False
                    break
                parsed.append((opt.label, m.group(1).strip()))
                pos += m.end()
            if ok_c and len(parsed) == len(options):
                consumed += 1
                return [
                    (label, [{"kind": "text", "text": text, "line_start": s, "line_end": e}])
                    for label, text in parsed
                ], consumed

    # ---- 策略 D：整行/整表图片单元格（列序=选项序，AF2-A/Q6）----
    # 版式：共享选项区的表格由 N 个图片单元格组成（无正文单元格），N 个声明
    # 选项按列序左→右一一对应；单元格图片不得丢弃（子 asset 块）。
    for rt in tables:
        cols_img: dict[int, list[str]] = {}
        text_cells = 0
        for c in rt.cells:
            if c.get("image_srcs"):
                cols_img.setdefault(c["col_index"], []).extend(c["image_srcs"])
            if (c.get("content") or "").strip():
                text_cells += 1
        if (
            cols_img
            and text_cells == 0
            and len(cols_img) == len(options)
            and sorted(cols_img) == list(range(len(options)))
        ):
            rows = []
            for i, opt in enumerate(options):
                blocks = [
                    {
                        "kind": "image",
                        "asset_id": _asset_id_from_src(src),
                        "alt_text": None,
                        "line_start": s,
                        "line_end": e,
                    }
                    for src in cols_img[i]
                ]
                rows.append((opt.label, blocks))
            consumed += sum(len(v) for v in cols_img.values())
            return rows, consumed
    return None, consumed


def detect_table_labels(tables: list[RawTable]) -> list[str]:
    """从表格标签列识别选项标签（A-H 印刷字面，行序；AF2-A/Q11）。"""
    out: list[str] = []
    seen: set[str] = set()
    for rt in tables:
        for row in _table_rows(rt):
            for c in row:
                key = _norm_cell_label(c["content"])
                if re.fullmatch(r"[A-H]", key) and key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


def extract_options(
    lines: list[str], options: list[OptionSpec], region: tuple[int, int] | None = None
) -> tuple[list[dict], list[RawTable]]:
    """按 Manifest 逐选项行区提取。

    - 常规：每选项独立行区 → 逐行字面文本。
    - 共享行区（多个选项同一 [s,e]）：
      · HTML 表格：解析表格，确定性策略切分选项；同时返回行区内全部
        RawTable 供父体 stem_blocks 保留整表网格。
      · 普通文本（同行/同区多选项）：按印刷标记切分（R1 B1）；切分失败
        fail-closed，不产出空选项。
    - region（单元 options_lines，G4-R1）：当声明的逐选项行区未覆盖表格
      （选项行指向 OCR 回声行/页脚行）而 options_lines 内存在表格时，以
      region 为表格探测范围，按「标签列+内容列」等版式提取。
    选项正文中的版面页脚（第N页/共M页）一律剔除（R1-05）。
    """
    if not options:
        return [], []
    spans = {(o.start, o.end) for o in options}
    shared = len(spans) == 1 and len(options) > 1
    s0, e0 = next(iter(spans))
    out: list[dict] = []

    rs, re_ = region if region else (s0, e0)
    span = (min(s0, rs), max(e0, re_))
    res_span = extract_range(lines, span[0], span[1])
    span_tables = res_span.tables
    res_decl = extract_range(lines, s0, e0)
    decl_tables = res_decl.tables

    def _finalize(blocks: list[dict]) -> list[dict]:
        fin = []
        for b in blocks:
            if b.get("kind") == "text":
                txt = _drop_footer_lines(b.get("text") or "")
                if not txt:
                    continue
                fin.append({**b, "text": txt})
            else:
                fin.append(b)
        return fin

    # ---- 表格驱动（共享行区，或声明行区未覆盖的 options_lines 表格） ----
    table_driven = bool(span_tables) and (shared or not decl_tables)
    if table_driven:
        tables = span_tables
        rows, _consumed = _table_option_rows(tables, options, span[0], span[1])
        if rows is not None:
            by_label = {lb: blocks for lb, blocks in rows}
            known = {o.label for o in options}
            for opt in options:
                blocks = _finalize(by_label.get(opt.label) or [])
                out.append({
                    "label": opt.label, "blocks": blocks,
                    "line_start": span[0], "line_end": span[1],
                })
            for lb, blocks in rows:
                if lb not in known:
                    out.append({
                        "label": lb, "blocks": _finalize(blocks),
                        "line_start": span[0], "line_end": span[1],
                    })
            return out, tables
        # 策略未命中 → 落回既有路径

    # ---- 共享行区非表格：同行多选项文本切分（B1） ----
    if shared:
        s, e = s0, e0
        table = decl_tables[0] if decl_tables else None
        tables = decl_tables
        if table is None:
            split = _split_inline_shared_options(lines, s, e, options)
            if split is None:
                raise ValueError(
                    f"shared option region L{s}-L{e}: inline option markers "
                    f"do not match labels {[o.label for o in options]} "
                    "(fail-closed; refusing empty/merged option blocks)"
                )
            for opt in options:
                info = split[opt.label]
                blocks = _finalize([{
                    "kind": "text", "text": info["text"],
                    "line_start": info["line_start"], "line_end": info["line_end"],
                }])
                if not blocks:
                    raise ValueError(
                        f"shared option region L{s}-L{e}: option {opt.label!r} "
                        "reduced to empty after footer filter (fail-closed)"
                    )
                out.append({
                    "label": opt.label, "blocks": blocks,
                    "line_start": info["line_start"], "line_end": info["line_end"],
                })
            return out, tables
        rows, _consumed = _table_option_rows(tables, options, s, e)
        if rows is not None:
            by_label = {lb: blocks for lb, blocks in rows}
            known = {o.label for o in options}
            for opt in options:
                out.append({
                    "label": opt.label, "blocks": _finalize(by_label.get(opt.label) or []),
                    "line_start": s, "line_end": e,
                })
            for lb, blocks in rows:
                if lb not in known:
                    out.append({
                        "label": lb, "blocks": _finalize(blocks),
                        "line_start": s, "line_end": e,
                    })
            return out, tables
        # 全部确定性策略均未命中：维持既有行为（空文本块），交 content audit 阻断
        for opt in options:
            out.append({
                "label": opt.label,
                "blocks": [{"kind": "text", "text": "", "line_start": s, "line_end": e}],
                "line_start": s, "line_end": e,
            })
        return out, tables

    # ---- 独立行区 ----
    # 同一行区内声明多个选项（如 A/B 在 L21、C/D 在 L23）：此时 spans 集合
    # 不止一个，上面的 `shared` 分支不触发，逐选项提取会把整行文本复制给
    # 每一个选项（Owner duplicate_option 的主因）。先按"行区 → 选项组"
    # 分组，多选项组走同行标记切分；切分失败保持原行为（由 ContentAudit
    # 阻断），绝不猜测内容。
    grouped: dict[tuple[int, int], list[OptionSpec]] = {}
    for opt in options:
        grouped.setdefault((opt.start, opt.end), []).append(opt)
    multi_splits: dict[str, dict] = {}
    for (gs, ge), grp in grouped.items():
        if len(grp) < 2:
            continue
        split = _split_inline_shared_options(lines, gs, ge, grp)
        if split is not None:
            multi_splits.update(split)

    for opt in options:
        if opt.label in multi_splits:
            info = multi_splits[opt.label]
            blocks = _finalize(
                [
                    {
                        "kind": "text",
                        "text": info["text"],
                        "line_start": info["line_start"],
                        "line_end": info["line_end"],
                    }
                ]
            )
            if blocks:
                out.append(
                    {
                        "label": opt.label,
                        "blocks": blocks,
                        "line_start": info["line_start"],
                        "line_end": info["line_end"],
                    }
                )
                continue
        res = extract_range(lines, opt.start, opt.end)
        blocks = _finalize(res.blocks or [])
        if not blocks:
            blocks = [{"kind": "text", "text": "", "line_start": opt.start, "line_end": opt.end}]
        out.append({
            "label": opt.label, "blocks": blocks,
            "line_start": opt.start, "line_end": opt.end,
        })
    return out, []
