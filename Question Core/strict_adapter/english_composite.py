"""英语 Composite 确定性结构展开 + 答案解码 + 逐子归一（QCORE-DELIVERY-01-C-R3）。

当前项目原生纯函数实现。规则来源（只提炼规则，不搬运代码）：
* B_HISTORY/ENGLISH-HISTORICAL-STRUCTURE-RECOVERY.md §3（五类结构规则）
* 同报告 §4（答案解码边界）与 §9（逐 Unit 方案）
* Owner R3 裁决（Gate 解耦、逐子 N.answer 归一、fail-closed、stem 边界）

职责分离（R3 §3.1，不复制历史 Gate）：
  1. 结构展开   —— expand_*：只看 Manifest 行区 + 源 MD 行，产出子题结构
  2. 答案解码   —— decode_*：按证据形态确定性解码，产出 label→value
  3. 归一/映射  —— build_composite_answers：逐子 TypedAnswer + N.answer declared_value
  4. 契约验证   —— 由 PreprocessingCandidate / candidate_adapter 执行（不在此绕过）

fail-closed：任一步无法唯一确定即返回 None/失败原因；不猜、不补齐、不提升
transport completeness（P-2）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from question_core.contracts.v1 import (
    AnswerCompleteness,
    AnswerEvidenceKind,
    AnswerStatement,
    Completeness,
    CompositeAnswer,
    CompositeSubAnswer,
    FillBlankAnswer,
    Material,
    MaterialRef,
    OptionItem,
    QuestionBody,
    QuestionContent,
    QuestionType,
    SingleChoiceAnswer,
    SlotBinding,
    StrictAnswerDeclaration,
    UnitType,
)

from .extract import extract_range
from .mapper import (
    MappingContext,
    UnitMapping,
    _annotate_conflicts,
    _answer_region_images,
    _blocks_from_raw,
    _build_evidence,
    _explanation_blocks,
    _item_locators,
    _item_statement,
    _rebuild,
    _register_asset,
)
from .rules import answer_completeness, question_type, resolve_attribution

#: 英语 composite 的 original_question_type。
#: 注意：语文卷同样声明 reading/composite_question（Q5/Q6/Q8/Q9/Q10）——
#: 仅凭题型不足以判定分支，必须叠加 rules.ENGLISH_COMPOSITE_SCOPE_PAPERS
#: 的试卷上下文（DSH R3 复核阻断项一）。
ENGLISH_COMPOSITE_TYPES = frozenset(
    {"grammar_fill", "cloze", "reading", "seven_to_five"}
)


def is_english_composite(unit: dict, ctx: MappingContext) -> bool:
    """英语 composite 判定 = 题型集合 **且** 试卷在显式适用范围内。

    范围外（含语文同名 reading composite）恒 False → 走既有（n）切分路径。
    """
    if unit.get("unit_type") != "composite_question":
        return False
    if (unit.get("original_question_type") or "") not in ENGLISH_COMPOSITE_TYPES:
        return False
    from .rules import ENGLISH_COMPOSITE_SCOPE_PAPERS

    return ctx.paper_id in ENGLISH_COMPOSITE_SCOPE_PAPERS


# ---------------------------------------------------------------------------
# 1. 答案解码（纯函数；每种格式正向/反向/fail-closed 测试见 test_english_composite）
# ---------------------------------------------------------------------------

_RANGE_SEG_RE = re.compile(
    r"(\d+)\s*[-—–]\s*(\d+)\s*[:：]?\s*([A-Za-z]+)"
)
_TOKEN_PAIR_RE = re.compile(
    r"[(（]?\s*(\d+)\s*[)）]?\s*[.．、:：]\s*([A-Za-z]+|[^()\（\）\s][^()\（\）]*?)"
    r"(?=\s+[(（]?\s*\d+\s*[)）]?\s*[.．、:：]|$)"
)
_COMPACT_RE = re.compile(r"^[A-Ha-h]+$")
_LETTER_SET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def decode_range_answer_key(raw: str) -> dict[int, str] | None:
    """区间答案键 `19-23 DABCA` / `21-23DBC` / `56—59:CBBA` / `36—40：ABCBA`。

    整串解码：所有区间长度==字母数、区间不重叠、题号不重复、字母∈A-H；
    任一违反 → None（fail-closed）。紧凑键（`FGDAE`）不是区间键 → None。
    """
    text = " ".join((raw or "").split())
    if not text or _COMPACT_RE.match(text):
        return None
    out: dict[int, str] = {}
    pos = 0
    consumed = 0
    first = True
    for m in _RANGE_SEG_RE.finditer(text):
        gap = text[pos : m.start()]
        if gap.strip():
            # 历史语料允许无数字前缀（如 `阅读：21-23DBC`）；含数字残段一律拒绝
            if not (first and not re.search(r"\d", gap)):
                return None
        first = False
        a, b, letters = int(m.group(1)), int(m.group(2)), m.group(3)
        if b < a or b - a + 1 != len(letters):
            return None
        if any(c.upper() not in _LETTER_SET for c in letters):
            return None
        for qn, ch in zip(range(a, b + 1), letters.upper()):
            if qn in out:
                return None  # 重叠/重复题号
            out[qn] = ch
        pos = m.end()
        consumed += 1
    if consumed == 0 or text[pos:].strip():
        return None
    return out


def decode_compact_answer_key(raw: str, start: int) -> dict[int, str] | None:
    """紧凑答案键 `FGDAE`：自 start 起逐字母一一对应；字母∈A-H，长度>0。"""
    text = (raw or "").strip().upper()
    if not text or not _COMPACT_RE.match(text) or start < 1:
        return None
    return {start + i: ch for i, ch in enumerate(text)}


def decode_per_question_tokens(raw: str) -> dict[int, str] | None:
    """逐题答案 `31. C 32. D` / `46. B 47. E` / `11.C 12.D`。

    题号必须唯一、值必须是单个 A-H 字母（该形态只用于选择题键）。
    """
    text = " ".join((raw or "").split())
    if not text:
        return None
    out: dict[int, str] = {}
    pos = 0
    for m in _TOKEN_PAIR_RE.finditer(text):
        if text[pos : m.start()].strip():
            return None
        qn = int(m.group(1))
        val = m.group(2).strip().upper()
        if len(val) != 1 or val not in _LETTER_SET:
            return None
        if qn in out:
            return None
        out[qn] = val
        pos = m.end()
    if not out or text[pos:].strip():
        return None
    return out


def decode_semicolon_fill(raw: str, expected: int) -> list[str] | None:
    """语法填空分号式答案 `voiced; facing; myself`（半角 ; 或全角 ；）。

    拆分数必须与 expected 完全一致；段内斜杠/空格属于答案本体（如
    `suggests/suggested/has suggested`），不得再拆。无法唯一拆分 → None。
    """
    text = (raw or "").strip()
    if not text or expected < 1:
        return None
    parts = [p.strip() for p in re.split(r"[;；]", text) if p.strip() != ""]
    if len(parts) != expected:
        return None
    return parts


def normalize_declared_value(pairs: list[tuple[str, str]]) -> str:
    """逐子归一为 F2 条件 5 可识别的 `N.answer` 形态（值逐字保留）。"""
    return " ".join(f"{label}.{value}" for label, value in pairs)


# ---------------------------------------------------------------------------
# 2. 空格定位（结构展开用；只认源文渲染形态，不猜结构）
# ---------------------------------------------------------------------------


@dataclass
class BlankMarker:
    label: str
    line_start: int
    line_end: int
    col: int
    raw: str
    #: 空位渲染的结束位置（跨行合并时指向最后一段渲染的末尾，句片段锚点用）
    end_line: int = 0
    end_col: int = 0
    merged_from: list = field(default_factory=list)


_UnderlineBlank = re.compile(r"\$ \s*\\underline\{(\d+)\}\s* \$(_*)")
_UnderscoreNumbered = re.compile(r"_{2,}(\d+)_{2,}")
_BareUnderscore = re.compile(r"_{3,}")


def find_blank_markers(
    lines: list[str], start: int, end: int, expected_labels: list[str]
) -> tuple[list[BlankMarker], list[str]] | None:
    """在行区 [start,end] 内定位空格，与 expected_labels 对账。

    渲染形态（2019 北京卷实测）：
      * `$ \\underline{N} $(hint)` —— LaTeX 编号空格（可带提示词）
      * `\\underline{N} $____`   —— 编号空格 + 紧随的 OCR 多余下划线（并入该空格）
      * `___N___`                —— 下划线编号空格（可跨行：行尾裸 ___ + 下行 `___N___`）
      * `___` / `____`           —— 裸空格（按出现顺序填补缺失编号）

    返回 (markers, errors)；errors 非空表示对账失败（调用方 fail-closed）。
    """
    expected = [str(x) for x in expected_labels]
    numbered: list[BlankMarker] = []
    bare: list[tuple[int, int, str]] = []  # (line_no, col, raw)

    def _mk(label, ln, col, raw, end_line=None, end_col=None):
        return BlankMarker(
            label=str(label),
            line_start=ln,
            line_end=ln,
            col=col,
            raw=raw,
            end_line=end_line if end_line is not None else ln,
            end_col=end_col if end_col is not None else col + len(raw),
        )

    for ln in range(start, end + 1):
        if ln - 1 >= len(lines):
            return None
        text = lines[ln - 1]
        consumed = [False] * (len(text) + 1)

        for m in _UnderlineBlank.finditer(text):
            numbered.append(_mk(int(m.group(1)), ln, m.start(), m.group(0)))
            for i in range(m.start(), m.end()):
                consumed[i] = True

        for m in _UnderscoreNumbered.finditer(text):
            if any(consumed[i] for i in range(m.start(), m.end())):
                continue
            numbered.append(_mk(int(m.group(1)), ln, m.start(), m.group(0)))
            for i in range(m.start(), m.end()):
                consumed[i] = True

        for m in _BareUnderscore.finditer(text):
            if any(consumed[i] for i in range(m.start(), m.end())):
                continue
            bare.append((ln, m.start(), m.group(0)))
            for i in range(m.start(), m.end()):
                consumed[i] = True

    errors: list[str] = []
    # 跨行合并：行尾裸空格 + 下一非空行行首 `___N___` → 同一空格 N。
    # 锚点取**第一段渲染**（行尾裸 ___）的起点，span 终点取最后一段渲染末尾
    # （DSH R3 复核阻断项二：不得只改 line_start 而让锚点落在错误的行首）。
    merged_bare: list[tuple[int, int, str]] = []
    skip_bare = set()
    numbered_at = {(m.line_start, m.col): m for m in numbered}
    for i, (ln, col, raw) in enumerate(bare):
        text_len = len(lines[ln - 1])
        at_line_end = col + len(raw) >= text_len
        nxt = None
        for cand in range(ln + 1, end + 1):
            if lines[cand - 1].strip():
                nxt = cand
                break
        if at_line_end and nxt is not None:
            tail_raw_line = lines[nxt - 1]
            tail = tail_raw_line.lstrip()
            lead_ws = len(tail_raw_line) - len(tail)
            m2 = _UnderscoreNumbered.match(tail)
            target = numbered_at.get((nxt, lead_ws + m2.start())) if m2 else None
            if m2 and target is not None:
                # 空位起点 = 行尾裸 ___（第一段），终点 = 下行编号渲染末尾
                target.line_start = ln
                target.col = col
                target.end_line = nxt
                target.end_col = lead_ws + m2.end()
                target.merged_from.append({"line": ln, "col": col, "raw": raw})
                skip_bare.add(i)
    for i, b in enumerate(bare):
        if i not in skip_bare:
            merged_bare.append(b)

    # 裸空格按序填补缺失编号
    have = {m.label for m in numbered}
    missing = [lb for lb in expected if lb not in have]
    if len(missing) != len(merged_bare):
        errors.append(
            f"bare blank count {len(merged_bare)} != missing labels {missing}"
        )
    else:
        for (ln, col, raw), label in zip(merged_bare, missing):
            numbered.append(_mk(label, ln, col, raw))

    numbered.sort(key=lambda m: expected.index(m.label) if m.label in expected else 999)
    got = [m.label for m in numbered]
    if got != expected:
        errors.append(f"blank labels {got} != expected {expected}")
    for m in numbered:
        if m.label not in expected:
            errors.append(f"unexpected blank label {m.label!r}")
    dup = {x for x in got if got.count(x) > 1}
    if dup:
        errors.append(f"duplicate blank labels {sorted(dup)}")
    return numbered, errors


_SENT_END_RE = re.compile(r'[.!?]["\')\]]?')


def sentence_fragment(
    lines: list[str], marker: BlankMarker
) -> tuple[str, int, int]:
    """空格句片段（确定性双模式，DSH R3 复核 §3 口径）：

    * **句中空位**（空位前有本句正文）：片段 = 含空位的整句
      （上一句终止符末尾 → 下一句终止符末尾）。
    * **句末/接缝空位**（空位紧跟句界、中间无正文）：片段 = **前一句 + 空位渲染**
      （空位即该句收尾/延伸；不取后句，避免把次句误作题干——U9 Q49 口径）。

    多空同句时各空得到相同片段（一致不矛盾）；跨行句自然跨行。
    """
    offsets: list[int] = []
    total = 0
    for ln in lines:
        offsets.append(total)
        total += len(ln) + 1  # "\n" join
    joined = "\n".join(lines)

    anchor_start = offsets[marker.line_start - 1] + marker.col
    end_line = marker.end_line or marker.line_start
    end_col = marker.end_col or (marker.col + len(marker.raw))
    anchor_end = offsets[end_line - 1] + end_col

    prev = 0
    prev_prev = 0
    for m in _SENT_END_RE.finditer(joined):
        if m.end() <= anchor_start:
            prev_prev = prev
            prev = m.end()
        else:
            break
    nxt = len(joined)
    for m in _SENT_END_RE.finditer(joined):
        if m.start() >= anchor_end:
            nxt = m.end()
            break

    if joined[prev:anchor_start].strip():
        # 模式 1：句中空位 → 含空位句
        abs_start, abs_end = prev, nxt
    else:
        # 模式 2：句末/接缝空位 → 前一句 + 空位渲染
        abs_start, abs_end = prev_prev, anchor_end

    frag = joined[abs_start:abs_end].strip("\n")
    # 回映射行区间：片段首尾字符所在行（按已知绝对偏移，不用 index 猜）
    while abs_start < abs_end and joined[abs_start] == "\n":
        abs_start += 1
    while abs_end > abs_start and joined[abs_end - 1] == "\n":
        abs_end -= 1
    line_start = 1
    line_end = 1
    for i, off in enumerate(offsets):
        if off <= abs_start:
            line_start = i + 1
        if off < abs_end:
            line_end = i + 1
    fl = frag.split("\n")
    while fl and not fl[0].strip():
        fl.pop(0)
        line_start += 1
    while fl and not fl[-1].strip():
        fl.pop()
        line_end -= 1
    return "\n".join(fl), line_start, line_end


# ---------------------------------------------------------------------------
# 3. 选项解析（只认行内印刷标签，不猜、不补）
# ---------------------------------------------------------------------------

_CLOZE_ROW_RE = re.compile(r"^\s*(\d+)\.\s+(.*)$")
_OPT_MARKER_RE = re.compile(r"(?:^|\s)([A-D])\.\s+")
_AG_LINE_RE = re.compile(r"^\s*([A-G])\.\s+(.*?)\s*$")


def _split_option_markers(inner: str) -> list[tuple[str, str]] | None:
    """按 `A.`/`B.`… 印刷标记切选项；标签必须恰好 A-D 各一次。"""
    marks = [(m.start(), m.end(), m.group(1)) for m in _OPT_MARKER_RE.finditer(inner)]
    if [lb for _, _, lb in marks] != ["A", "B", "C", "D"]:
        return None
    out = []
    for i, (s, e, lb) in enumerate(marks):
        nxt = marks[i + 1][0] if i + 1 < len(marks) else len(inner)
        text = inner[e:nxt].strip()
        if not text:
            return None
        out.append((lb, text))
    return out


def _split_option_markers_located(
    parts: list[tuple[str, int]],
) -> list[tuple[str, str, int, int]] | None:
    """按印刷标记切选项并保留真实行定位（R1 B3）。

    parts = [(line_text, line_no), …]，行号允许不连续。每选项返回
    (label, text, line_start, line_end)：同行多选项共享同一行号；
    跨行选项给真实起止行。标签必须恰好 A-D 各一次，否则 None（fail-closed）。
    不推算行号、不使用 Unit 级行区代替块级定位。
    """
    if not parts:
        return None
    joined_parts: list[str] = []
    spans: list[tuple[int, int, int]] = []  # (start, end_exclusive, line_no)
    offset = 0
    for text, ln in parts:
        if joined_parts:
            joined_parts.append("\n")
            offset += 1
        start = offset
        joined_parts.append(text)
        offset += len(text)
        spans.append((start, offset, ln))
    joined = "".join(joined_parts)

    def line_at(pos: int) -> int:
        for s, e, ln in spans:
            if s <= pos < e:
                return ln
        for s, e, ln in reversed(spans):
            if e <= pos:
                return ln
        return spans[0][2]

    marks = [(m.start(), m.end(), m.group(1)) for m in _OPT_MARKER_RE.finditer(joined)]
    if [lb for _, _, lb in marks] != ["A", "B", "C", "D"]:
        return None
    out = []
    for i, (_s, e, lb) in enumerate(marks):
        nxt = marks[i + 1][0] if i + 1 < len(marks) else len(joined)
        raw = joined[e:nxt]
        text = raw.strip()
        if not text:
            return None
        first = e + (len(raw) - len(raw.lstrip()))
        last = first + len(text) - 1
        out.append((lb, text, line_at(first), line_at(last)))
    return out


def parse_cloze_option_rows(
    lines: list[str], start: int, end: int, expected_labels: list[str]
) -> tuple[dict[str, list[tuple[str, str, int, int]]], list[str]]:
    """完形选项行 `11. A. … B. … C. … D. …`：行号=空格号，每空 A-D 各一。

    返回 rows[label] = [(opt_label, text, line_start, line_end), …]（R1 B3）。
    """
    errors: list[str] = []
    rows: dict[str, list[tuple[str, str, int, int]]] = {}
    for ln in range(start, end + 1):
        text = lines[ln - 1]
        if not text.strip() or text.strip() == "---":
            continue
        m = _CLOZE_ROW_RE.match(text)
        if not m:
            errors.append(f"L{ln}: unmatched option row: {text[:60]!r}")
            continue
        label = str(int(m.group(1)))
        opts = _split_option_markers_located([(m.group(2), ln)])
        if opts is None:
            errors.append(f"L{ln}: option labels not exactly A-D once each")
            continue
        if label in rows:
            errors.append(f"duplicate option row for blank {label}")
            continue
        rows[label] = opts
    if sorted(rows, key=int) != sorted(expected_labels, key=int):
        errors.append(
            f"option rows {sorted(rows, key=int)} != expected {sorted(expected_labels, key=int)}"
        )
    return rows, errors


def parse_ag_pool(
    lines: list[str], start: int, end: int
) -> tuple[list[tuple[str, str, int, int]], list[str]]:
    """七选五共享选项池 A-G（父级挂载；不得复制成每子 A-D）。

    返回 (label, text, line_start, line_end)（R1 B3：逐选项块级定位）。
    """
    errors: list[str] = []
    pool: list[tuple[str, str, int, int]] = []
    for ln in range(start, end + 1):
        text = lines[ln - 1]
        if not text.strip() or text.strip() == "---":
            continue
        m = _AG_LINE_RE.match(text)
        if not m:
            errors.append(f"L{ln}: unmatched A-G option line: {text[:60]!r}")
            continue
        pool.append((m.group(1), m.group(2), ln, ln))
    labels = [lb for lb, *_ in pool]
    if labels != sorted(labels) or len(set(labels)) != len(labels) or not labels:
        errors.append(f"A-G pool labels not unique ascending: {labels}")
    return pool, errors


def parse_reading_stems(
    lines: list[str], start: int, end: int, expected_labels: list[str]
) -> tuple[list[dict], list[str]]:
    """阅读子题：`N. 题干` 行 + 其后 A-D 选项行，直到下一题干。"""
    errors: list[str] = []
    stems: list[dict] = []
    stem_lines: list[tuple[int, str, str]] = []
    for ln in range(start, end + 1):
        text = lines[ln - 1]
        m = re.match(r"^\s*(\d+)\.\s+(\S.*)$", text)
        if m and str(int(m.group(1))) in expected_labels:
            stem_lines.append((ln, str(int(m.group(1))), text.strip()))
    got = [lb for _, lb, _ in stem_lines]
    if got != expected_labels:
        errors.append(f"reading stems {got} != expected {expected_labels}")
        return stems, errors
    for i, (ln, label, first) in enumerate(stem_lines):
        nxt_ln = stem_lines[i + 1][0] if i + 1 < len(stem_lines) else end + 1
        stem_parts = [first]
        opt_parts: list[tuple[str, int]] = []
        in_opts = False
        for cand in range(ln + 1, nxt_ln):
            t = lines[cand - 1]
            if not t.strip() or t.strip() == "---":
                continue
            if _OPT_MARKER_RE.search(t):
                in_opts = True
            if in_opts:
                opt_parts.append((t, cand))
            else:
                stem_parts.append(t.strip())
        stem_text = " ".join(stem_parts).strip()
        opts = _split_option_markers_located(opt_parts) if opt_parts else None
        if opts is None:
            errors.append(f"reading Q{label}: options not exactly A-D once each")
            continue
        stems.append(
            SubSpec(
                label=label,
                stem_text=stem_text,
                stem_line_start=ln,
                stem_line_end=ln,
                options=list(opts),
                blank_raw=None,
            )
        )
    return stems, errors


# ---------------------------------------------------------------------------
# 4. 空格型展开（语法填空 / 完形 / 七选五）
# ---------------------------------------------------------------------------


@dataclass
class SubSpec:
    label: str
    stem_text: str
    stem_line_start: int
    stem_line_end: int
    options: list[tuple[str, str, int, int]]  # (label, text, line_start, line_end)
    blank_raw: str | None


def expand_blank_subs(
    lines: list[str],
    material_range: tuple[int, int],
    expected_labels: list[str],
    option_rows: dict[str, list[tuple[str, str, int, int]]] | None,
) -> tuple[list[SubSpec], list[str]]:
    """空格型子题：空格定位 + 句片段题干 +（可选）逐空选项。"""
    found = find_blank_markers(
        lines, material_range[0], material_range[1], expected_labels
    )
    if found is None:
        return [], ["blank marker scan failed"]
    markers, errors = found
    if errors:
        return [], errors
    subs: list[SubSpec] = []
    for m in markers:
        frag, ls, le = sentence_fragment(lines, m)
        opts = (option_rows or {}).get(m.label, [])
        if option_rows is not None and not opts:
            return [], [f"blank {m.label}: no option row"]
        subs.append(
            SubSpec(
                label=m.label,
                stem_text=frag,
                stem_line_start=ls,
                stem_line_end=le,
                options=list(opts),
                blank_raw=m.raw,
            )
        )
    return subs, []


# ---------------------------------------------------------------------------
# 5. 答案解码（独立于结构；失败不影响已展开结构）
# ---------------------------------------------------------------------------


@dataclass
class DecodeResult:
    ok: bool
    mode: str
    pairs: list[tuple[str, str]]
    declared_value: str
    errors: list[str]


def decode_unit_answers(unit: dict, labels: list[str]) -> DecodeResult:
    """按证据形态确定性解码 → 逐子 (label, value)。

    覆盖格式（R3 §5.1）：`N.answer` 逐题、`N-M ABCDE` 区间、紧凑键、
    分号式语法填空。任一不确定 → ok=False，保留结构、答案 fail-closed。
    """
    ev = unit.get("answer_evidence") or {}
    kind = ev.get("type") or "absent"
    raw = (ev.get("value") or "").strip()
    qtype = unit.get("original_question_type") or ""
    errors: list[str] = []

    # Phase 3（G-04）：Manifest answers[] 逐条为权威取值（sub_label ↔ value_text），
    # 覆盖全部 question_numbers 时确定性成立；answers[] 存在但不完整/异常时
    # fail-closed（不与旧字符串解码混源）；无 answers[] 时回退既有解码路径。
    items = unit.get("answers") or []
    if items:
        by_label: dict[str, str] = {}
        for it in items:
            lb = str(it.get("sub_label") or "")
            vt = it.get("value_text")
            if vt is None:
                errors.append(
                    f"label {lb}: null value_text in answers[] "
                    "(disputed/image slots are not handled by the english "
                    "composite decode path)"
                )
                continue
            if lb in by_label:
                errors.append(f"label {lb}: duplicated in answers[]")
                continue
            by_label[lb] = vt
        if errors:
            return DecodeResult(
                False, "manifest_answers_items", [], "", errors
            )
        if sorted(by_label, key=int) != sorted(labels, key=int):
            return DecodeResult(
                False,
                "manifest_answers_items",
                [],
                "",
                [
                    f"answers[] labels {sorted(by_label, key=int)} != "
                    f"question_numbers {sorted(labels, key=int)}"
                ],
            )
        pairs = [(lb, by_label[lb]) for lb in labels]
        return DecodeResult(
            True,
            "manifest_answers_items",
            pairs,
            normalize_declared_value(pairs),
            [],
        )

    if not raw:
        return DecodeResult(False, "absent", [], "", ["no declared answer value"])

    decoded: dict[str, str] = {}
    mode = ""

    if kind == "range_string" or re.search(r"\d+\s*[-—–]\s*\d+", raw):
        rng = decode_range_answer_key(raw)
        if rng is None:
            return DecodeResult(
                False, "range_key", [], "", ["range key decode failed (fail-closed)"]
            )
        decoded = {str(k): v for k, v in rng.items()}
        mode = "range_key"
    elif qtype == "grammar_fill":
        items = decode_semicolon_fill(raw, len(labels))
        if items is None:
            return DecodeResult(
                False, "semicolon_fill", [], "",
                [f"semicolon split count != {len(labels)} (fail-closed)"],
            )
        decoded = {lb: v for lb, v in zip(labels, items)}
        mode = "semicolon_fill"
    else:
        toks = decode_per_question_tokens(raw)
        if toks is not None:
            decoded = {str(k): v for k, v in toks.items()}
            mode = "per_question_tokens"
        else:
            compact = decode_compact_answer_key(raw, start=int(labels[0]))
            if compact is not None:
                decoded = {str(k): v for k, v in compact.items()}
                mode = "compact_key"
            else:
                return DecodeResult(
                    False, "unknown", [], "",
                    ["no deterministic answer format matched (fail-closed)"],
                )

    if sorted(decoded, key=int) != sorted(labels, key=int):
        errors.append(
            f"decoded labels {sorted(decoded, key=int)} != expected {sorted(labels, key=int)}"
        )
    for lb, v in decoded.items():
        if not v:
            errors.append(f"label {lb}: empty answer value")
    if errors:
        return DecodeResult(False, mode, [], "", errors)

    pairs = [(lb, decoded[lb]) for lb in labels]
    return DecodeResult(True, mode, pairs, normalize_declared_value(pairs), [])


def build_composite_answer(
    unit: dict, decode: DecodeResult, transport: str
) -> CompositeAnswer | None:
    """逐子 CompositeSubAnswer（值逐字保留）→ CompositeAnswer。

    Phase 3 增量（G-04/G-01）：answers[] 条目来源的 statements（source_region/
    evidence_lines）与 slot_bindings（slot_id/sub_label）随答案落位；
    attribution 由条目状态派生（resolved→attributed，disputed→disputed）。
    """
    if not decode.ok:
        return None
    comp = AnswerCompleteness(transport)
    kind = (unit.get("answer_evidence") or {}).get("type") or "absent"
    # DSH B2：逐答案 provenance 与 Manifest answer_evidence.type 一致
    # （顶层/子问/inner 三层同源，不再硬编码 answer_lines）。
    evidence_kind = (
        AnswerEvidenceKind(kind) if kind != "absent" else AnswerEvidenceKind.ANSWER_LINES
    )
    qtype = unit.get("original_question_type") or ""
    unit_id = unit.get("unit_id") or "u"
    items_by_label: dict[str, dict] = {}
    for it in unit.get("answers") or []:
        items_by_label[str(it.get("sub_label") or "")] = it
    subs = []
    for pos, (label, value) in enumerate(decode.pairs):
        item = items_by_label.get(str(label), {})
        item_statements = []
        if item:
            stmt_value = item.get("value_text")
            if stmt_value is not None:
                item_statements.append(
                    _item_statement(
                        item,
                        statement_id=f"{unit_id.lower()}-st{pos + 1}",
                        sub_label=str(label),
                        slot_index=0 if qtype == "grammar_fill" else None,
                        value_text=stmt_value,
                        locators=_item_locators(item),
                    )
                )
        sub_attr = (
            "disputed"
            if (item.get("status") == "disputed")
            else "attributed"
        )
        if qtype == "grammar_fill":
            inner = FillBlankAnswer(
                answer_value=(value,),
                answer_display=value,
                evidence_kind=evidence_kind,
                completeness=comp,
                grading_rule="manual",
                attribution=sub_attr,
                statements=tuple(item_statements),
                slot_bindings=(
                    (
                        SlotBinding(
                            slot_index=0,
                            slot_id=(item.get("slot_id") or f"{label}#1"),
                            sub_label=str(label),
                        ),
                    )
                    if item
                    else ()
                ),
                note="verbatim manifest answer segment (multi-word values kept intact)",
            )
        else:
            inner = SingleChoiceAnswer(
                answer_value=value,
                answer_display=value,
                evidence_kind=evidence_kind,
                completeness=comp,
                grading_rule="exact",
                attribution=sub_attr,
                statements=tuple(item_statements),
                note=f"decoded via {decode.mode}; letter bound to printed label",
            )
        subs.append(
            CompositeSubAnswer(
                sub_label=str(label),
                answer_value=inner,
                completeness=comp,
                evidence_kind=evidence_kind,
                attribution=sub_attr,
                note=f"per-sub attribution established by {decode.mode} (R3 §5.1)",
            )
        )
    return CompositeAnswer(
        answer_value=tuple(subs),
        answer_display=decode.declared_value,
        evidence_kind=evidence_kind,
        completeness=comp,
        grading_rule="manual",
        note=(
            "CompositeAnswer: one sub-answer per printed label; declared_value "
            "normalised to N.answer form (R3 §5.2); transport completeness is "
            "the only completeness authority (P-2)"
        ),
    )


def f2_condition5_probe(pairs: list[tuple[str, str]]) -> dict:
    """诊断（证据用）：当前契约 F2-5 composite 匹配器能否识别该 N.answer 形态。

    使用契约自带匹配实现（contracts.v1.candidate），不改契约。
    """
    from question_core.contracts.v1.candidate import (
        _answer_matches_declared,
        _parse_composite_pairs,
        _norm,
    )

    declared = normalize_declared_value(pairs)
    parsed = _parse_composite_pairs(_norm(declared))
    expect_keys = {lb for lb, _ in pairs}
    got_keys = set(parsed) if parsed else set()

    def _k(x: str):
        return (0, int(x)) if x.isdigit() else (1, x)

    inner = []
    for lb, val in pairs:
        item = FillBlankAnswer(answer_value=(val,), completeness="unknown")
        sub = CompositeSubAnswer(sub_label=lb, answer_value=item)
        inner.append((lb, _answer_matches_declared(sub, _norm(val))))
    return {
        "declared_value": declared,
        "parsed_pairs": parsed,
        "expected_keys": sorted(expect_keys, key=_k),
        "parsed_keys": sorted(got_keys, key=_k),
        "keys_match": got_keys == expect_keys,
        "per_sub_value_match": dict(inner),
        "f2_condition5_recognizable": got_keys == expect_keys
        and all(ok for _, ok in inner),
    }


# ---------------------------------------------------------------------------
# 6. 映射编排（英语 composite 专用；化学/语文路径在 mapper.map_unit 不变）
# ---------------------------------------------------------------------------


def map_unit(unit: dict, ctx: MappingContext) -> UnitMapping:
    """英语 composite Unit → UnitMapping（结构/解码/归一分离，fail-closed）。"""
    import hashlib

    from question_core.contracts.v1 import (
        Asset,
        CandidateCore,
        Completeness as _C,
        IngestionIdentity,
        InputHashes,
        PreprocessingCandidate,
        PreprocessingSource,
        PreprocessingUnitRef,
        SourceDocumentRef,
        TextBlock,
        Visibility,
        canonical_content_hash,
        derive_idempotency_key,
    )

    from . import ADAPTER_VERSION

    # R1 B2：学科由导入上下文显式提供（不猜测、不默认）
    if not (ctx.subject or "").strip():
        raise ValueError(
            f"{unit.get('unit_id')}: MappingContext.subject missing "
            "(fail-closed; english_composite requires explicit paper-level "
            "subject from the import context)"
        )

    unit_id = unit["unit_id"]
    log: dict = {"unit_id": unit_id, "path": "english_composite"}
    source_document_id = f"{ctx.paper_id}/{unit_id}"
    attribution, reason = resolve_attribution(unit, source_document_id)
    log["attribution"] = attribution
    log["attribution_reason"] = reason
    transport = answer_completeness(unit)
    log["answer_completeness_transport"] = transport

    labels = [str(n) for n in (unit.get("question_numbers") or [])]
    if not labels:
        raise ValueError(f"{unit_id}: composite unit without question_numbers")
    qtype = unit.get("original_question_type") or ""
    mrange = unit.get("material_lines")
    orange = unit.get("options_lines")
    if not mrange:
        raise ValueError(f"{unit_id}: english composite without material_lines")

    asset_sink: list = []
    errors: list[str] = []

    # ---- 1. 结构展开（答案不可用也不影响）----
    option_rows = None
    ag_pool: list[tuple[str, str]] = []
    if qtype == "cloze":
        if not orange:
            raise ValueError(f"{unit_id}: cloze without options_lines")
        option_rows, err = parse_cloze_option_rows(ctx.lines, orange[0], orange[1], labels)
        errors.extend(err)
    if qtype == "seven_to_five":
        if not orange:
            raise ValueError(f"{unit_id}: seven_to_five without options_lines")
        ag_pool, err = parse_ag_pool(ctx.lines, orange[0], orange[1])
        errors.extend(err)

    if qtype == "reading":
        qrange = unit.get("questions_lines") or []
        if not qrange:
            raise ValueError(f"{unit_id}: reading without questions_lines")
        subs, err = parse_reading_stems(ctx.lines, qrange[0], qrange[1], labels)
        errors.extend(err)
    else:
        subs, err = expand_blank_subs(
            ctx.lines, (mrange[0], mrange[1]), labels, option_rows
        )
        errors.extend(err)
    if errors:
        raise ValueError(f"{unit_id}: english expansion fail-closed: {errors}")
    log["sub_specs"] = [
        {
            "label": s.label,
            "stem_line_start": s.stem_line_start,
            "stem_line_end": s.stem_line_end,
            "stem_text_len": len(s.stem_text),
            "blank_raw": s.blank_raw,
            "option_labels": [lb for lb, *_ in s.options],
        }
        for s in subs
    ]

    # ---- 2. 内容：父 Material + 父 body + 子 body ----
    base = unit_id.lower()
    mres = extract_range(ctx.lines, mrange[0], mrange[1])
    mblocks = _blocks_from_raw(mres.blocks, asset_sink, ctx, f"{base}-material")
    material = Material(
        material_id=f"{base}-material",
        title=None,
        blocks=tuple(mblocks),
        line_start=mrange[0],
        line_end=mrange[1],
        note="shared material extracted from manifest.material_lines (verbatim)",
    )

    parent_options = tuple(
        OptionItem(
            label=lb,
            blocks=(TextBlock(text=txt, line_start=ls, line_end=le),),
            line_start=ls,
            line_end=le,
        )
        for lb, txt, ls, le in ag_pool
    )
    parent = QuestionBody(
        local_id=base,
        question_type=QuestionType(question_type(unit)),
        printed_number=unit.get("printed_number"),
        stem_blocks=(TextBlock(text="", line_start=mrange[0], line_end=mrange[0]),),
        options=parent_options,
        material_ids=(material.material_id,),
        parent_question_ref=None,
        sub_question_ids=tuple(f"{base}-s{i+1}" for i in range(len(subs))),
        unit_type=UnitType(unit.get("unit_type") or "composite_question"),
        note=(
            "english composite parent; sub-questions expanded deterministically "
            "(blank markers / printed question lines); shared material kept on "
            "parent only; A-G option pool on parent for seven_to_five"
        ),
    )
    bodies = [parent]
    sub_type = (
        "fill_blank" if qtype == "grammar_fill" else "single_choice"
    )
    for i, s in enumerate(subs):
        opts = tuple(
            OptionItem(
                label=lb,
                blocks=(TextBlock(text=txt, line_start=ls, line_end=le),),
                line_start=ls,
                line_end=le,
            )
            for lb, txt, ls, le in s.options
        )
        bodies.append(
            QuestionBody(
                local_id=f"{base}-s{i+1}",
                question_type=QuestionType(sub_type),
                printed_number=s.label,
                stem_blocks=(
                    TextBlock(
                        text=s.stem_text,
                        line_start=s.stem_line_start,
                        line_end=s.stem_line_end,
                    ),
                ),
                options=opts,
                material_ids=(material.material_id,),
                parent_question_ref=base,
                sub_question_ids=(),
                unit_type=UnitType(unit.get("unit_type") or "composite_question"),
                note=(
                    f"sub-question {s.label}: stem = sentence fragment clamped to "
                    f"L{s.stem_line_start}-L{s.stem_line_end}; blank rendering "
                    f"{s.blank_raw!r} kept as locator evidence (R3 §4.5)"
                ),
            )
        )

    explanation_blocks = _explanation_blocks(unit, ctx, asset_sink, log)
    ans_img_records = tuple(_answer_region_images(unit, ctx, asset_sink, log))
    assets = tuple(
        Asset(
            asset_id=a["asset_id"],
            asset_role=a["asset_role"],
            target_path=a.get("target_path"),
            source_id=a["source_id"],
            page=a["page"],
            bbox=a["bbox"],
            storage_path=a["storage_path"],
            content_hash=a["content_hash"],
            mime_type=a["mime_type"],
            width=a["width"],
            height=a["height"],
            note=a["note"],
        )
        for a in asset_sink
    )
    content = QuestionContent(
        bodies=tuple(bodies), materials=(material,), assets=assets
    )

    # ---- 3. 答案解码 + 逐子归一（失败不影响上面的结构）----
    decode = decode_unit_answers(unit, labels)
    log["answer_decode"] = {
        "ok": decode.ok,
        "mode": decode.mode,
        "declared_value": decode.declared_value,
        "errors": decode.errors,
        "pairs": [{"label": lb, "value": v} for lb, v in decode.pairs],
    }
    if decode.ok:
        composite = build_composite_answer(unit, decode, transport)
        answers = (composite,) if composite else ()
    else:
        answers = ()
    answers, conflict_specs = _annotate_conflicts(answers, unit, unit_id, log)

    # 逐条答案追踪（Phase 3 保真矩阵输入）：answers[] 条目 → 解码对/子答案位。
    label_pos = {str(lb): i for i, (lb, _) in enumerate(decode.pairs)}
    for idx, it in enumerate(unit.get("answers") or []):
        lb = str(it.get("sub_label") or "")
        if decode.ok and lb in label_pos:
            disposition = "composite_sub_slot"
            target = f"/answers/0/answer_value/{label_pos[lb]}"
        else:
            disposition = "unmapped"
            target = None
        log.setdefault("answers_trace", []).append(
            {
                "item_index": idx,
                "sub_label": it.get("sub_label"),
                "slot_id": it.get("slot_id"),
                "value_text": it.get("value_text"),
                "asset_ref": it.get("asset_ref"),
                "form": it.get("form"),
                "source_region": it.get("source_region"),
                "evidence_lines": it.get("evidence_lines"),
                "status": it.get("status"),
                "disposition": disposition,
                "target": target,
                "unmapped_reason": (
                    None if disposition != "unmapped" else
                    "; ".join(decode.errors) or "decode failed"
                ),
            }
        )

    # 归属细化（R3 §5.1/§5.2 + Phase 3 answers[] 来源）：确定性逐题解码且
    # 题号全覆盖时获得逐题归属（默认 kind_to_attribution 保持不变，本分支限定使用）。
    if (
        decode.ok
        and attribution == "not_attributable"
        and decode.mode in ("range_key", "manifest_answers_items")
    ):
        attribution = "declared"
        reason = (
            f"R3 §5.1/§5.2: answer evidence deterministically decoded "
            f"(mode={decode.mode}) with exact question-number coverage -> "
            "per-question attribution established"
        )
        log["attribution"] = attribution
        log["attribution_reason"] = reason
    elif not decode.ok and attribution == "declared":
        attribution = "not_attributable"
        reason = (
            "declared value cannot be reliably normalised to per-sub N.answer "
            "(fail-closed): " + "; ".join(decode.errors)
        )
        log["attribution"] = attribution
        log["attribution_reason"] = reason

    evidence = _build_evidence(
        unit,
        answers,
        ctx,
        attribution,
        log,
        extra_records=ans_img_records,
        conflict_specs=conflict_specs,
    )
    declaration = StrictAnswerDeclaration(
        attribution=attribution,
        evidence_kind=(unit.get("answer_evidence") or {}).get("type") or "absent",
        declared_value=decode.declared_value if (decode.ok and attribution == "declared") else None,
        table_row_locator=(unit.get("answer_evidence") or {}).get("table_row_locator"),
        completeness=(
            _C.INCOMPLETE if attribution == "not_attributable" else _C.COMPLETE
        ),
    )
    log["declaration"] = declaration.model_dump(mode="json")

    all_full = bool(answers) and all(
        a.completeness == AnswerCompleteness.FULL for a in answers
    )
    core_completeness = (
        _C.COMPLETE if all_full else _C.INCOMPLETE
    )
    declaration = _rebuild(declaration, completeness=core_completeness)
    log["declaration"] = declaration.model_dump(mode="json")
    log["core_completeness_before_f2"] = core_completeness.value

    # ---- 4. 身份 / 证据链（与 mapper 相同口径）----
    input_hashes = InputHashes(
        manifest_hash=ctx.manifest_sha,
        source_md_hash=ctx.source_md_sha,
        source_pdf_hash=ctx.source_pdf_sha,
    )
    idem_key = derive_idempotency_key(
        source_type="preprocessing",
        source_document_id=source_document_id,
        input_hashes=input_hashes,
    )
    stem_texts = "\n".join(
        getattr(b, "text", "")
        for body in bodies
        for b in body.stem_blocks
        if getattr(b, "kind", "") == "text"
    )
    fingerprint = "fp-e2e01-" + hashlib.sha256(
        f"{source_document_id}\n{stem_texts}".encode("utf-8")
    ).hexdigest()[:16]
    ingestion = IngestionIdentity(
        candidate_idempotency_key=idem_key,
        ingestion_run_id=ctx.ingestion_run_id,
        adapter_version=ADAPTER_VERSION,
        input_hashes=input_hashes,
        ingested_by="qcore-e2e-01-phase-c",
        note="sealed Phase-B artifacts only; no re-OCR/re-reslice/re-guess",
    )
    source = PreprocessingSource(
        source_document_id=source_document_id,
        manifest_ref=SourceDocumentRef(
            doc_role="manifest",
            content_hash=ctx.manifest_sha,
            locator_uri=ctx.manifest_path,
            byte_size=ctx.manifest_bytes,
        ),
        source_md_ref=SourceDocumentRef(
            doc_role="source_markdown",
            content_hash=ctx.source_md_sha,
            locator_uri=ctx.source_md_path,
            byte_size=ctx.source_md_bytes,
        ),
        source_pdf_ref=SourceDocumentRef(
            doc_role="source_pdf",
            content_hash=ctx.source_pdf_sha,
            locator_uri=ctx.source_pdf_name,
            byte_size=ctx.source_pdf_bytes,
        ),
        annotated_md_ref=SourceDocumentRef(
            doc_role="annotated_markdown",
            content_hash=ctx.annotated_md_sha,
            locator_uri=ctx.annotated_md_name,
            byte_size=ctx.annotated_md_bytes,
        ),
        unit=PreprocessingUnitRef(
            unit_id=unit["unit_id"],
            unit_type=UnitType(unit["unit_type"]),
            question_numbers=tuple(unit.get("question_numbers") or ()),
            original_question_type=unit.get("original_question_type"),
            section=unit.get("section"),
            printed_number=unit.get("printed_number"),
            stem_lines=tuple(unit["stem_lines"]) if unit.get("stem_lines") else None,
            options_lines=tuple(unit["options_lines"])
            if unit.get("options_lines")
            else None,
            answer_lines=tuple(unit["answer_lines"])
            if unit.get("answer_lines")
            else None,
            explanation_lines=tuple(unit["explanation_lines"])
            if unit.get("explanation_lines")
            else None,
            extra_lines=tuple(unit["extra_lines"]) if unit.get("extra_lines") else None,
            material_lines=tuple(unit["material_lines"])
            if unit.get("material_lines")
            else None,
            questions_lines=tuple(unit["questions_lines"])
            if unit.get("questions_lines")
            else None,
        ),
        grade=ctx.manifest.get("grade"),
        subject=ctx.subject,
        answer_declaration=declaration,
    )

    def _build(core_comp: _C):
        core = CandidateCore(
            question_type=QuestionType(question_type(unit)),
            content=content,
            answers=tuple(answers),
            evidence=evidence,
            completeness=core_comp,
            identity_fingerprint=fingerprint,
            ingestion=ingestion,
            content_visibility=Visibility.REVIEW_ONLY,
            answer_visibility=Visibility.REVIEW_ONLY,
            explanation_visibility=Visibility.REVIEW_ONLY,
            evidence_visibility=Visibility.REVIEW_ONLY,
            created_by="qcore-e2e-01-phase-c",
            note=(
                "english composite mapped by strict_adapter.english_composite "
                f"(deterministic expansion + answer decode); decode_mode={decode.mode}; "
                f"answer ruling: {reason}"
            ),
        )
        return PreprocessingCandidate(core=core, source=source)

    try:
        candidate = _build(core_completeness)
    except ValueError as exc:
        if core_completeness != _C.COMPLETE:
            raise
        # F2 条件 5 等校验拒绝 complete：fail-closed 降 incomplete 并留证
        core_completeness = _C.INCOMPLETE
        log["f2_complete_rejected"] = str(exc)
        candidate = _build(core_completeness)
    log["core_completeness"] = core_completeness.value

    all_ranges = [
        r for r in (mrange, unit.get("questions_lines"), unit.get("options_lines"),
                    unit.get("answer_lines"), unit.get("explanation_lines"),
                    unit.get("extra_lines")) if r
    ]
    instance_fields = {
        "printed_number": unit.get("printed_number"),
        "question_numbers": tuple(unit.get("question_numbers") or ()),
        "section": unit.get("section"),
        "line_start": min(r[0] for r in all_ranges) if all_ranges else None,
        "line_end": max(r[1] for r in all_ranges) if all_ranges else None,
    }
    content_hash = canonical_content_hash(
        content, *answers, *explanation_blocks
    )
    log["content_hash"] = content_hash
    state_plan = (
        "approve_publish" if core_completeness == _C.COMPLETE else "hold_not_ready"
    )
    log["state_plan"] = state_plan
    log["state_plan_not_executed"] = state_plan

    return UnitMapping(
        unit_id=unit_id,
        candidate=candidate,
        explanation_blocks=explanation_blocks,
        content_hash=content_hash,
        completeness=core_completeness.value,
        instance_fields=instance_fields,
        state_plan=state_plan,
        log=log,
    )
