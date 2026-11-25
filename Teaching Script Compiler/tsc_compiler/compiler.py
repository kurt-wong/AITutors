"""Deterministic TeachingScript compiler.

The script is *derived* from the official revision payload:

* what to show → source blocks (stem / materials / options / explanation)
* what to say  → the same source text, math rendered readably
* what it means → the official answer, never an LLM guess

A deterministic compiler is a deliberate pilot choice: every fact in the script
can be traced to a source ref, and re-compiling the same revision yields the
same steps. The LLM is confined to the retrieval layer (matching a photo to a
candidate), where a mistake cannot become a question fact.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from .models import (
    DEFAULT_LANGUAGE,
    MODEL_ID,
    PROMPT_VERSION,
    RENDERER_VERSION,
    SCRIPT_SCHEMA_VERSION,
    cache_key,
)
from .normalize import (
    estimate_duration_ms,
    math_to_speech,
    speechify,
    split_math_spans,
)

ANALYSIS_MARKERS = ("【分析】", "【思路】", "分析：", "思路：")
DETAIL_MARKERS = ("【详解】", "【解答】", "【解析】", "详解：", "解答：", "解：")
CONCLUSION_MARKERS = ("【点睛】", "【答案】", "【结论】", "答案：", "结论：")
MAX_STEPS = 8


class CompileError(RuntimeError):
    """A revision cannot be turned into an honest teaching script."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_marker(text: str, markers: tuple[str, ...]) -> tuple[str, str | None]:
    stripped = text.lstrip()
    for marker in markers:
        if stripped.startswith(marker):
            return stripped[len(marker) :].strip(), marker
        idx = stripped.find(marker)
        if 0 < idx <= 4:
            return (stripped[:idx] + stripped[idx + len(marker) :]).strip(), marker
    return text, None


def classify_explanation(
    blocks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split explanation blocks into analysis / detail / conclusion."""
    sections: dict[str, list[dict[str, Any]]] = {
        "analysis": [],
        "detail": [],
        "conclusion": [],
    }
    section = "detail"
    for index, block in enumerate(blocks):
        if block.get("kind") != "text":
            continue
        raw = str(block.get("text") or "").strip()
        if not raw or re.fullmatch(r"[-—–\s]+", raw):
            continue
        body = raw
        hit: str | None = None
        for markers, name in (
            (ANALYSIS_MARKERS, "analysis"),
            (CONCLUSION_MARKERS, "conclusion"),
            (DETAIL_MARKERS, "detail"),
        ):
            stripped, marker = _strip_marker(raw, markers)
            if marker:
                hit = name
                body = stripped
                break
        target = hit or section
        if hit:
            section = hit
        if not body:
            continue
        sections[target].append(
            {**block, "text": body, "index": index, "source_text": raw}
        )
    return sections["analysis"], sections["detail"], sections["conclusion"]


def _block_text(block: dict[str, Any]) -> str:
    kind = block.get("kind")
    if kind == "text":
        return str(block.get("text") or "")
    if kind == "table":
        return "\n".join(
            " | ".join(str(c.get("content") or "") for c in row)
            for row in _table_rows(block)
        )
    if kind == "image":
        return str(block.get("alt_text") or "")
    return ""


def _table_rows(block: dict[str, Any]) -> list[list[dict[str, Any]]]:
    n_rows = int(block.get("n_rows") or 0)
    n_cols = int(block.get("n_cols") or 0)
    rows: list[list[dict[str, Any]]] = [
        [{"content": ""} for _ in range(n_cols)] for _ in range(n_rows)
    ]
    for cell in block.get("cells") or []:
        r = int(cell.get("row_index") or 0)
        c = int(cell.get("col_index") or 0)
        if 0 <= r < n_rows and 0 <= c < n_cols:
            rows[r][c] = cell
    return rows


class _Refs:
    """Builds the ``sources`` map and hands out stable ref ids."""

    def __init__(self, bundle: dict[str, Any]):
        self.bundle = bundle
        self.sources: dict[str, dict[str, Any]] = {}
        self.assets_by_id = {
            str(a.get("asset_id")): a for a in (bundle.get("assets") or [])
        }

    def add(self, ref: str, record: dict[str, Any]) -> str:
        if ref in self.sources and self.sources[ref] != record:
            raise CompileError("REF_CONFLICT", f"source ref reused: {ref}")
        self.sources[ref] = record
        return ref

    def content_block(
        self,
        *,
        local_id: str,
        part: str,
        index: int,
        block: dict[str, Any],
        label: str | None = None,
        material_id: str | None = None,
    ) -> str:
        ref = (
            f"cb:{material_id}:{index}"
            if material_id
            else (
                f"cb:{local_id}:option:{label}:{index}"
                if part == "option"
                else f"cb:{local_id}:{part}:{index}"
            )
        )
        record = {
            "kind": "content_block",
            "question_id": self.bundle["question_id"],
            "revision_id": self.bundle["revision_id"],
            "local_id": local_id,
            "part": part,
            "index": index,
            "block_kind": str(block.get("kind") or ""),
            "line_start": block.get("line_start"),
            "line_end": block.get("line_end"),
            "text": _block_text(block),
        }
        if label is not None:
            record["label"] = label
        if material_id is not None:
            record["material_id"] = material_id
        return self.add(ref, record)

    def explanation(self, index: int, block: dict[str, Any]) -> str:
        ref = f"exp:{index}"
        source_text = block.get("source_text")
        if source_text is None:
            source_text = _block_text(block)
        return self.add(
            ref,
            {
                "kind": "explanation_block",
                "question_id": self.bundle["question_id"],
                "revision_id": self.bundle["revision_id"],
                "index": index,
                "block_kind": str(block.get("kind") or ""),
                "line_start": block.get("line_start"),
                "line_end": block.get("line_end"),
                "text": source_text,
            },
        )

    def answer(self, index: int, answer: dict[str, Any]) -> str:
        ref = f"ans:{index}"
        locator = None
        for statement in answer.get("statements") or []:
            for loc in statement.get("locators") or []:
                if loc.get("line_start") is not None:
                    locator = loc
                    break
            if locator:
                break
        return self.add(
            ref,
            {
                "kind": "answer",
                "question_id": self.bundle["question_id"],
                "revision_id": self.bundle["revision_id"],
                "answer_index": index,
                "line_start": (locator or {}).get("line_start"),
                "line_end": (locator or {}).get("line_end"),
                "value_text": str(answer.get("answer_value") or ""),
            },
        )

    def asset(self, asset_id: str, url: str | None) -> str:
        asset = self.assets_by_id.get(asset_id) or {}
        ref = f"asset:{asset_id}"
        return self.add(
            ref,
            {
                "kind": "asset",
                "question_id": self.bundle["question_id"],
                "revision_id": self.bundle["revision_id"],
                "asset_id": asset_id,
                "storage_path": str(asset.get("storage_path") or ""),
                "url": url,
            },
        )


class _BoardBuilder:
    def __init__(
        self,
        step_no: int,
        refs: _Refs,
        allowlist: dict[str, Any],
        asset_base: str,
    ):
        self.step_no = step_no
        self.refs = refs
        self.allowlist = allowlist
        self.asset_base = asset_base.rstrip("/")
        self.blocks: list[dict[str, Any]] = []
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"b{self.step_no}{self._counter:02d}"

    def heading(self, text: str, ref: str | None = None) -> dict[str, Any]:
        block = {"id": self._next_id(), "kind": "heading", "text": text}
        if ref:
            block["ref"] = ref
        self.blocks.append(block)
        return block

    def text(self, text: str, ref: str | None = None) -> dict[str, Any]:
        block = {"id": self._next_id(), "kind": "text", "text": text}
        if ref:
            block["ref"] = ref
        self.blocks.append(block)
        return block

    def math(self, latex: str, ref: str | None = None) -> dict[str, Any]:
        block = {"id": self._next_id(), "kind": "math", "latex": latex}
        if ref:
            block["ref"] = ref
        self.blocks.append(block)
        return block

    def callout(self, text: str, tone: str = "info", ref: str | None = None) -> dict[str, Any]:
        block = {"id": self._next_id(), "kind": "callout", "tone": tone, "text": text}
        if ref:
            block["ref"] = ref
        self.blocks.append(block)
        return block

    def choice(self, label: str, text: str, ref: str | None = None) -> dict[str, Any]:
        block = {
            "id": self._next_id(),
            "kind": "choice",
            "label": label,
            "text": text,
        }
        if ref:
            block["ref"] = ref
        self.blocks.append(block)
        return block

    def source_block(self, source_block: dict[str, Any], ref: str) -> dict[str, Any] | None:
        kind = source_block.get("kind")
        if kind == "text":
            return self.text(str(source_block.get("text") or ""), ref)
        if kind == "image":
            asset_id = str(source_block.get("asset_id") or "")
            entry = self.allowlist.get(asset_id) or {}
            url_path = entry.get("url_path")
            url = f"{self.asset_base}/{url_path}" if url_path else None
            asset_ref = self.refs.asset(asset_id, url)
            block = {
                "id": self._next_id(),
                "kind": "image",
                "asset_id": asset_id,
                "alt": str(source_block.get("alt_text") or "") or f"题目配图（{asset_id}）",
                "url": url,
                "ref": asset_ref,
            }
            self.blocks.append(block)
            return block
        if kind == "table":
            rows = [
                [str(cell.get("content") or "") for cell in row]
                for row in _table_rows(source_block)
            ]
            block = {"id": self._next_id(), "kind": "table", "rows": rows, "ref": ref}
            self.blocks.append(block)
            return block
        return None


def _effects_for(board: list[dict[str, Any]], duration_ms: int) -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []
    max_show = max(0, duration_ms - 2200)
    for offset, block in enumerate(board[1:], start=1):
        effects.append(
            {
                "at_ms": min(400 * offset, max_show),
                "type": "show",
                "target": block["id"],
            }
        )
    if not board:
        return effects
    first_visible = next(
        (b for b in board if b["kind"] not in ("heading",)), board[0]
    )
    effects.append(
        {
            "at_ms": 200,
            "type": "highlight",
            "target": first_visible["id"],
            "duration_ms": 1800,
        }
    )
    key_block = next(
        (b for b in board if b["kind"] in ("math", "callout", "table", "image")),
        first_visible,
    )
    effects.append(
        {
            "at_ms": int(duration_ms * 0.45),
            "type": "focus",
            "target": key_block["id"],
            "duration_ms": 1600,
        }
    )
    effects.append(
        {
            "at_ms": max(1200, int(duration_ms * 0.82)),
            "type": "pulse",
            "target": board[-1]["id"],
            "duration_ms": 900,
        }
    )
    return effects


def _step(
    step_no: int,
    goal: str,
    refs: list[str],
    board: list[dict[str, Any]],
    speech_source: str,
) -> dict[str, Any]:
    speech = speechify(speech_source)
    if not speech:
        speech = goal
    # The player renders the subtitle with KaTeX when the source still carries
    # its math delimiters; speech stays plain text for the (future) TTS layer.
    subtitle = re.sub(r"\s+", " ", speech_source).strip() or speech
    duration = max(estimate_duration_ms(speech_source), 1600 + 500 * len(board))
    duration = max(3000, min(60000, duration))
    return {
        "step_id": f"s{step_no}",
        "goal": goal,
        "source_refs": _dedupe(refs),
        "board": board,
        "speech": speech,
        "subtitle": subtitle,
        "duration_ms": duration,
        "effects": _effects_for(board, duration),
    }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _first_text(bundle: dict[str, Any]) -> str:
    for body in (bundle.get("content") or {}).get("bodies") or []:
        for block in body.get("stem_blocks") or []:
            if block.get("kind") == "text" and str(block.get("text") or "").strip():
                return str(block["text"])
    return "题目"


def _title_text(stem: str, limit: int = 36) -> str:
    """Human title from the prose part of the stem only.

    Math spans are dropped rather than printed as raw LaTeX (the heading is
    plain text; the board carries the rendered formula).
    """
    parts = [
        span["text"]
        for span in split_math_spans(stem)
        if span["kind"] == "text"
    ]
    text = re.sub(r"\s+", " ", "".join(parts)).strip()
    text = re.sub(r"^\d+[.、．]\s*", "", text)
    # Removing math leaves empty brackets and punctuation seams.
    text = re.sub(r"[（(]\s*[）)]", "", text)
    text = re.sub(r"([，,、；;])\s*(?=[，,、；;])", "", text)
    text = re.sub(r"\s+([，,、；;])", r"\1", text)
    text = re.sub(r"[，,、；;：:\s]+$", "", text)
    text = text.strip(" ，,。;；:：")
    if not text:
        return "题目"
    return text[:limit] + ("…" if len(text) > limit else "")


def _answer_payload(answer: dict[str, Any]) -> dict[str, Any]:
    """Normalize a TypedAnswer into (display, value, accepted alternatives).

    The pilot teaches revisions whose typed answer is a *scalar* fact:
    single-choice letter, multi-choice label set, or a fill-in-the-blank
    value. Composite/subjective answers carry per-sub-question ownership that
    this round deliberately does not teach (spec §7.2 excludes ambiguous
    answer ownership).
    """
    answer_type = str(answer.get("answer_type") or "")
    if answer_type not in {"single_choice", "multi_choice", "fill_blank"}:
        raise CompileError(
            "ANSWER_NOT_SIMPLE",
            f"answer_type={answer_type!r} is not a scalar answer; the pilot "
            "only teaches single_choice / multi_choice / fill_blank revisions",
        )
    raw_value = answer.get("answer_value")
    alternatives: list[str] = []
    if isinstance(raw_value, str):
        alternatives = [raw_value]
    elif isinstance(raw_value, list):
        alternatives = [str(v) for v in raw_value if isinstance(v, str) and v.strip()]
    if not alternatives:
        raise CompileError("EMPTY_ANSWER", "typed answer has no scalar value")

    expanded: list[str] = []
    for item in alternatives:
        parts = [p.strip() for p in item.split("#\\#") if p.strip()]
        expanded.extend(parts or [item])
    display = str(answer.get("answer_display") or "").strip()
    if not display:
        joined = "".join(expanded) if answer_type == "multi_choice" else " 或 ".join(expanded)
        display = joined
    value = str(answer.get("answer_value") or display).strip()
    if answer_type == "multi_choice":
        value = "".join(expanded)
    elif answer_type == "fill_blank":
        value = expanded[0]
    else:
        value = str(raw_value).strip()
    return {
        "answer_type": answer_type,
        "display": display,
        "value": value,
        "accepted_alternatives": expanded,
        "grading_rule": answer.get("grading_rule"),
    }


def _detail_groups(
    chunks: list[tuple[dict[str, Any], str]], target: int
) -> list[list[tuple[dict[str, Any], str]]]:
    if len(chunks) <= target or target <= 0:
        return [[c] for c in chunks]
    per_group = -(-len(chunks) // target)
    groups: list[list[tuple[dict[str, Any], str]]] = []
    for start in range(0, len(chunks), per_group):
        groups.append(chunks[start : start + per_group])
    return groups


def _chunk_with_math(text: str, max_chars: int = 220) -> list[str]:
    """Chunk a paragraph at sentence boundaries; never split a math span.

    A hard split would cut numbers (``2550`` → ``2`` + ``550``) and LaTeX
    commands, which the validator would then flag as new facts. Long single
    sentences therefore stay whole.
    """
    from .normalize import split_sentences

    sentences = split_sentences(text) or [text]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current += sentence
    if current.strip():
        chunks.append(current.strip())
    return chunks


def compile_script(
    bundle: dict[str, Any],
    *,
    allowlist: dict[str, Any],
    asset_base: str,
    language: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    answers = bundle.get("answers") or []
    if not answers:
        raise CompileError("NO_ANSWER", "published revision carries no typed answer")
    question_type = str(bundle.get("question_type") or "")
    answer_index = 0
    for idx, answer in enumerate(answers):
        if answer.get("answer_type") == question_type:
            answer_index = idx
            break
    answer = answers[answer_index]
    payload = _answer_payload(answer)
    display = payload["display"]
    value = payload["value"]
    if not display:
        raise CompileError("EMPTY_ANSWER", "typed answer has no displayable value")

    explanation = bundle.get("explanation_blocks") or []
    if not explanation:
        raise CompileError("NO_EXPLANATION", "revision has no official explanation to teach")
    analysis, detail, conclusion = classify_explanation(explanation)
    if not detail and not analysis:
        raise CompileError("NO_EXPLANATION_BODY", "explanation blocks carry no teachable text")

    refs = _Refs(bundle)
    content = bundle.get("content") or {}
    bodies = content.get("bodies") or []
    materials = content.get("materials") or []

    # ---- step 1: read the question -------------------------------------
    board = _BoardBuilder(1, refs, allowlist, asset_base)
    step_refs: list[str] = []
    read_text_parts: list[str] = []
    for material in materials:
        material_id = str(material.get("material_id") or "")
        for index, block in enumerate(material.get("blocks") or []):
            ref = refs.content_block(
                local_id=material_id,
                part="material",
                index=index,
                block=block,
                material_id=material_id,
            )
            step_refs.append(ref)
            board.source_block(block, ref)
            read_text_parts.append(_block_text(block))
    for body in bodies:
        local_id = str(body.get("local_id") or "u1")
        printed = body.get("printed_number") or bundle.get("printed_number")
        if len(bodies) > 1:
            board.heading(f"题目 {printed}" if printed else "题目")
        for index, block in enumerate(body.get("stem_blocks") or []):
            ref = refs.content_block(
                local_id=local_id, part="stem", index=index, block=block
            )
            step_refs.append(ref)
            board.source_block(block, ref)
            read_text_parts.append(_block_text(block))
        for option in body.get("options") or []:
            label = str(option.get("label") or "")
            texts: list[str] = []
            last_ref: str | None = None
            for index, block in enumerate(option.get("blocks") or []):
                ref = refs.content_block(
                    local_id=local_id,
                    part="option",
                    index=index,
                    block=block,
                    label=label,
                )
                step_refs.append(ref)
                last_ref = ref
                if block.get("kind") == "text":
                    texts.append(str(block.get("text") or ""))
                else:
                    board.source_block(block, ref)
            board.choice(label, " ".join(t for t in texts if t).strip(), last_ref)
            read_text_parts.extend(texts)
    if not board.blocks:
        raise CompileError("EMPTY_CONTENT", "revision has no student-visible content")

    steps: list[dict[str, Any]] = [
        _step(
            1,
            "读题：先读题干，再逐项确认选项或空位",
            step_refs,
            board.blocks,
            "\n".join(p for p in read_text_parts if p),
        )
    ]

    # ---- step 2: analysis ----------------------------------------------
    if analysis:
        board = _BoardBuilder(2, refs, allowlist, asset_base)
        refs_for_step: list[str] = []
        texts: list[str] = []
        board.callout("解题思路", "info")
        for block in analysis:
            ref = refs.explanation(block["index"], block)
            refs_for_step.append(ref)
            board.source_block(block, ref)
            texts.append(str(block.get("text") or ""))
        steps.append(
            _step(
                2,
                "分析：把已知条件转化为可计算的表达式",
                refs_for_step,
                board.blocks,
                "\n".join(texts),
            )
        )

    # ---- detail steps ---------------------------------------------------
    detail_chunks: list[tuple[dict[str, Any], str]] = []
    for block in detail:
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        for chunk in _chunk_with_math(text):
            detail_chunks.append((block, chunk))

    reserved = len(steps) + 1  # conclusion
    available = max(1, MAX_STEPS - reserved)
    groups = _detail_groups(detail_chunks, available)

    step_no = len(steps) + 1
    for group in groups:
        board = _BoardBuilder(step_no, refs, allowlist, asset_base)
        group_refs: list[str] = []
        group_text: list[str] = []
        for block, chunk in group:
            ref = refs.explanation(block["index"], block)
            group_refs.append(ref)
            group_text.append(chunk)
            board.source_block({**block, "text": chunk}, ref)
        steps.append(
            _step(
                step_no,
                "详解：按官方解析推进下一段",
                group_refs,
                board.blocks,
                "\n".join(group_text),
            )
        )
        step_no += 1

    # ---- final step: answer ---------------------------------------------
    board = _BoardBuilder(step_no, refs, allowlist, asset_base)
    ans_ref = refs.answer(answer_index, answer)
    final_refs: list[str] = [ans_ref]
    board.heading("结论")
    for block in conclusion:
        ref = refs.explanation(block["index"], block)
        final_refs.append(ref)
        board.source_block(block, ref)
    board.callout(f"本题答案为：{display}", "answer", ans_ref)
    if re.search(r"[\\^_{}]", display) and len(display) > 1:
        board.math(display.replace("$", ""), ans_ref)
    steps.append(
        _step(
            step_no,
            "结论：确认最终答案，并回看关键条件",
            final_refs,
            board.blocks,
            f"所以本题的答案是 {display}。",
        )
    )

    if len(steps) > MAX_STEPS:
        raise CompileError(
            "TOO_MANY_STEPS", f"{len(steps)} steps exceed the {MAX_STEPS}-step contract"
        )

    key = cache_key(
        question_id=bundle["question_id"],
        revision_id=bundle["revision_id"],
        language=language,
    )
    seed = f"{key}|{bundle.get('content_hash')}"
    script_id = "ts_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    printed = bundle.get("printed_number")
    title = (
        f"{printed}题 · {_title_text(_first_text(bundle))}"
        if printed
        else _title_text(_first_text(bundle))
    )

    return {
        "script_schema_version": SCRIPT_SCHEMA_VERSION,
        "script_id": script_id,
        "cache_key": key,
        "question_id": bundle["question_id"],
        "revision_id": bundle["revision_id"],
        "revision_number": int(bundle.get("revision_number") or 1),
        "language": language,
        "prompt_version": PROMPT_VERSION,
        "model": MODEL_ID,
        "renderer_version": RENDERER_VERSION,
        "subject": bundle.get("subject") or "unknown",
        "source_document_id": bundle.get("source_document_id") or "",
        "printed_number": printed,
        "question_type": question_type,
        "title": title,
        "content_hash": bundle.get("content_hash") or "",
        "final_answer": {
            "display": display,
            "value": value,
            "answer_type": payload["answer_type"],
            "grading_rule": payload["grading_rule"],
            "accepted_alternatives": payload["accepted_alternatives"],
            "source_refs": [ans_ref],
        },
        "steps": steps,
        "sources": refs.sources,
        "created_at": _utc_now(),
        "validation": {"status": "fail", "checks": [], "validated_at": _utc_now()},
    }


def math_speech(latex: str) -> str:
    return math_to_speech(latex)


def split_spans(text: str):
    return split_math_spans(text)
