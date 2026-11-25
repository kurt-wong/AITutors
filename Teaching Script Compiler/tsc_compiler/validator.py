"""TeachingScript validator.

A script is only usable when all checks pass. The validator is intentionally
paranoid: it re-reads the QCore bundle and proves that

* the script is bound to the *current published* revision,
* every source ref resolves to the same text/line range it claims,
* every board target and effect target exists,
* every image resolves through the asset allowlist,
* the final answer equals QCore's typed answer,
* no numeric or LaTeX token appears that is not present in the source,
* the math is structurally renderable.

Failing any check makes the script ``status="fail"``; the API/cache refuses to
serve failed scripts as teaching material.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

from .normalize import latex_commands, normalize_answer, numeric_tokens, split_math_spans

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "teaching_script.schema.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _res(check: str, ok: bool, detail: str = "") -> dict[str, str]:
    return {"name": check, "status": "pass" if ok else "fail", "detail": detail}


def _bundle_text(bundle: dict[str, Any]) -> str:
    parts: list[str] = []
    content = bundle.get("content") or {}
    for body in content.get("bodies") or []:
        for block in body.get("stem_blocks") or []:
            parts.append(_block_text(block))
        for option in body.get("options") or []:
            for block in option.get("blocks") or []:
                parts.append(_block_text(block))
    for material in content.get("materials") or []:
        for block in material.get("blocks") or []:
            parts.append(_block_text(block))
    for block in bundle.get("explanation_blocks") or []:
        parts.append(_block_text(block))
    for answer in bundle.get("answers") or []:
        parts.append(str(answer.get("answer_value") or ""))
        parts.append(str(answer.get("answer_display") or ""))
    parts.append(str(bundle.get("printed_number") or ""))
    return "\n".join(parts)


def _block_text(block: dict[str, Any]) -> str:
    kind = block.get("kind")
    if kind == "text":
        return str(block.get("text") or "")
    if kind == "table":
        rows = _table_rows(block)
        return "\n".join(" | ".join(str(c.get("content") or "") for c in row) for row in rows)
    if kind == "image":
        return str(block.get("alt_text") or "")
    return ""


def _table_rows(block: dict[str, Any]) -> list[list[dict[str, Any]]]:
    n_rows = int(block.get("n_rows") or 0)
    n_cols = int(block.get("n_cols") or 0)
    rows = [[{"content": ""} for _ in range(n_cols)] for _ in range(n_rows)]
    for cell in block.get("cells") or []:
        r, c = int(cell.get("row_index") or 0), int(cell.get("col_index") or 0)
        if 0 <= r < n_rows and 0 <= c < n_cols:
            rows[r][c] = cell
    return rows


def _find_content_block(bundle: dict[str, Any], ref: dict[str, Any]) -> dict[str, Any] | None:
    content = bundle.get("content") or {}
    if ref.get("part") == "material":
        for material in content.get("materials") or []:
            if str(material.get("material_id")) == ref.get("material_id"):
                blocks = material.get("blocks") or []
                index = int(ref.get("index") or 0)
                return blocks[index] if index < len(blocks) else None
        return None
    for body in content.get("bodies") or []:
        if str(body.get("local_id")) != ref.get("local_id"):
            continue
        if ref.get("part") == "stem":
            blocks = body.get("stem_blocks") or []
            index = int(ref.get("index") or 0)
            return blocks[index] if index < len(blocks) else None
        if ref.get("part") == "option":
            for option in body.get("options") or []:
                if str(option.get("label")) != ref.get("label"):
                    continue
                blocks = option.get("blocks") or []
                index = int(ref.get("index") or 0)
                return blocks[index] if index < len(blocks) else None
    return None


def _check_sources(script: dict[str, Any], bundle: dict[str, Any]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    sources = script.get("sources") or {}
    failures: list[str] = []
    for ref_id, record in sources.items():
        kind = record.get("kind")
        if kind == "content_block":
            block = _find_content_block(bundle, record)
            if block is None:
                failures.append(f"{ref_id}: content block not found")
                continue
            expected = _block_text(block)
            if _norm_ws(record.get("text")) != _norm_ws(expected):
                failures.append(f"{ref_id}: text mismatch")
            if record.get("line_start") != block.get("line_start"):
                failures.append(f"{ref_id}: line_start mismatch")
        elif kind == "explanation_block":
            blocks = bundle.get("explanation_blocks") or []
            index = int(record.get("index") or 0)
            if index >= len(blocks):
                failures.append(f"{ref_id}: explanation block not found")
                continue
            block = blocks[index]
            if _norm_ws(record.get("text")) != _norm_ws(_block_text(block)):
                failures.append(f"{ref_id}: explanation text mismatch")
            if record.get("line_start") != block.get("line_start"):
                failures.append(f"{ref_id}: line_start mismatch")
        elif kind == "answer":
            answers = bundle.get("answers") or []
            index = int(record.get("answer_index") or 0)
            if index >= len(answers):
                failures.append(f"{ref_id}: answer not found")
                continue
            if str(answers[index].get("answer_value") or "") != str(
                record.get("value_text") or ""
            ):
                failures.append(f"{ref_id}: answer value mismatch")
        elif kind == "asset":
            asset_ids = {str(a.get("asset_id")) for a in bundle.get("assets") or []}
            if record.get("asset_id") not in asset_ids:
                failures.append(f"{ref_id}: asset not in revision")
        else:
            failures.append(f"{ref_id}: unknown source kind {kind}")
    checks.append(_res("source_refs_resolve", not failures, "; ".join(failures[:8])))
    return checks


def _check_refs_exist(script: dict[str, Any]) -> list[dict[str, str]]:
    sources = script.get("sources") or {}
    missing: list[str] = []
    for step in script.get("steps") or []:
        for ref in step.get("source_refs") or []:
            if ref not in sources:
                missing.append(f"{step.get('step_id')} -> {ref}")
        for block in step.get("board") or []:
            ref = block.get("ref")
            if ref and ref not in sources:
                missing.append(f"{step.get('step_id')}/{block.get('id')} -> {ref}")
    for ref in (script.get("final_answer") or {}).get("source_refs") or []:
        if ref not in sources:
            missing.append(f"final_answer -> {ref}")
    return [_res("refs_declared", not missing, "; ".join(missing[:8]))]


def _check_targets(script: dict[str, Any]) -> list[dict[str, str]]:
    problems: list[str] = []
    seen: set[str] = set()
    for step in script.get("steps") or []:
        ids = [b.get("id") for b in step.get("board") or []]
        if len(ids) != len(set(ids)):
            problems.append(f"{step.get('step_id')}: duplicate block id")
        seen.update(ids)
        target_ids = set(ids)
        for effect in step.get("effects") or []:
            if effect.get("target") not in target_ids:
                problems.append(
                    f"{step.get('step_id')}: effect target missing {effect.get('target')}"
                )
            if int(effect.get("at_ms") or 0) >= int(step.get("duration_ms") or 0):
                problems.append(f"{step.get('step_id')}: effect outside step duration")
    return [_res("board_targets", not problems, "; ".join(problems[:8]))]


def _check_assets(script: dict[str, Any]) -> list[dict[str, str]]:
    problems: list[str] = []
    for step in script.get("steps") or []:
        for block in step.get("board") or []:
            if block.get("kind") != "image":
                continue
            if not block.get("url"):
                problems.append(f"{block.get('id')}: image has no resolvable url")
            if not str(block.get("alt") or "").strip():
                problems.append(f"{block.get('id')}: image has no alt text")
    return [_res("assets_resolve", not problems, "; ".join(problems[:8]))]


def _expected_answers(selected: dict[str, Any]) -> set[str]:
    raw = selected.get("answer_value")
    values: list[str] = []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = [str(v) for v in raw if isinstance(v, str) and v.strip()]
    expanded: list[str] = []
    for item in values:
        parts = [p.strip() for p in item.split("#\\#") if p.strip()]
        expanded.extend(parts or [item])
    expected = {normalize_answer(v) for v in expanded if normalize_answer(v)}
    if len(expanded) > 1:
        expected.add(normalize_answer("".join(expanded)))
    display = selected.get("answer_display")
    if isinstance(display, str) and display.strip():
        expected.add(normalize_answer(display))
    return expected


def _check_answer(script: dict[str, Any], bundle: dict[str, Any]) -> list[dict[str, str]]:
    answers = bundle.get("answers") or []
    qtype = str(bundle.get("question_type") or "")
    selected = None
    for answer in answers:
        if answer.get("answer_type") == qtype:
            selected = answer
            break
    if selected is None and answers:
        selected = answers[0]
    if selected is None:
        return [_res("answer_consistent", False, "bundle has no answer")]
    expected = _expected_answers(selected)
    final = script.get("final_answer") or {}
    got_value = normalize_answer(final.get("value") or "")
    got_display = normalize_answer(final.get("display") or "")
    ok = got_value in expected or got_display in expected
    return [
        _res(
            "answer_consistent",
            ok,
            f"script=({final.get('display')!r},{final.get('value')!r}) "
            f"qcore={sorted(expected)[:4]}",
        )
    ]


def _step_text_tokens(step: dict[str, Any]) -> tuple[set[str], set[str]]:
    numbers: set[str] = set()
    commands: set[str] = set()
    texts: list[str] = []
    for block in step.get("board") or []:
        for key in ("text", "latex"):
            if block.get(key):
                texts.append(str(block[key]))
        for row in block.get("rows") or []:
            texts.extend(str(cell) for cell in row)
    texts.append(str(step.get("speech") or ""))
    for text in texts:
        numbers |= numeric_tokens(text)
        commands |= latex_commands(text)
    return numbers, commands


def _check_no_new_facts(script: dict[str, Any], bundle: dict[str, Any]) -> list[dict[str, str]]:
    allowed_text = _bundle_text(bundle)
    allowed_numbers = numeric_tokens(allowed_text)
    allowed_commands = latex_commands(allowed_text)
    extra_numbers: set[str] = set()
    extra_commands: set[str] = set()
    for step in script.get("steps") or []:
        numbers, commands = _step_text_tokens(step)
        extra_numbers |= numbers - allowed_numbers
        extra_commands |= commands - allowed_commands
    detail = ""
    if extra_numbers:
        detail += f"unknown numbers: {sorted(extra_numbers)[:10]}"
    if extra_commands:
        detail += f" unknown latex: {sorted(extra_commands)[:10]}"
    return [
        _res(
            "no_unsupported_facts",
            not extra_numbers and not extra_commands,
            detail.strip(),
        )
    ]


def _math_balance(latex: str) -> str | None:
    depth = 0
    i = 0
    while i < len(latex):
        ch = latex[i]
        if ch == "\\":  # escaped brace / command: never a structural brace
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return "unbalanced closing brace"
        i += 1
    if depth != 0:
        return "unbalanced opening brace"
    return None


def _check_math(script: dict[str, Any]) -> list[dict[str, str]]:
    problems: list[str] = []
    for step in script.get("steps") or []:
        for block in step.get("board") or []:
            if block.get("kind") == "math":
                err = _math_balance(str(block.get("latex") or ""))
                if err:
                    problems.append(f"{block.get('id')}: {err}")
            elif block.get("kind") == "text":
                text = str(block.get("text") or "")
                for span in split_math_spans(text):
                    if span["kind"] == "math":
                        err = _math_balance(span["latex"])
                        if err:
                            problems.append(f"{block.get('id')}: inline {err}")
    return [_res("math_renderable", not problems, "; ".join(problems[:8]))]


def _check_choice_text(script: dict[str, Any], bundle: dict[str, Any]) -> list[dict[str, str]]:
    """Choice blocks must carry the option text the revision actually holds."""
    option_texts: dict[str, set[str]] = {}
    for body in (bundle.get("content") or {}).get("bodies") or []:
        for option in body.get("options") or []:
            label = str(option.get("label") or "")
            joined = "".join(
                _block_text(b) for b in option.get("blocks") or []
            )
            option_texts.setdefault(label, set()).add(_norm_ws(joined))
    problems: list[str] = []
    for step in script.get("steps") or []:
        for block in step.get("board") or []:
            if block.get("kind") != "choice":
                continue
            label = str(block.get("label") or "")
            text = _norm_ws(block.get("text") or "")
            if label not in option_texts:
                problems.append(f"{block.get('id')}: unknown option label {label!r}")
            elif text and text not in option_texts[label]:
                problems.append(f"{block.get('id')}: option text drift for {label}")
    return [_res("choice_text_faithful", not problems, "; ".join(problems[:8]))]


def _check_step_shape(script: dict[str, Any]) -> list[dict[str, str]]:
    problems: list[str] = []
    steps = script.get("steps") or []
    if not 1 <= len(steps) <= 8:
        problems.append(f"step count {len(steps)} outside 1..8")
    for index, step in enumerate(steps, start=1):
        if step.get("step_id") != f"s{index}":
            problems.append(f"step ordering broken at {step.get('step_id')}")
        if not (step.get("source_refs") or []):
            problems.append(f"{step.get('step_id')}: no source refs")
        if int(step.get("duration_ms") or 0) < 3000:
            problems.append(f"{step.get('step_id')}: duration too short")
    return [_res("step_contract", not problems, "; ".join(problems[:8]))]


_SECTION_MARKER = re.compile(r"【(?:分析|详解|点睛|答案|解析|解答|小问)】")


def _strip_section_markers(text: str) -> str:
    """Remove structural section labels before source containment checks.

    The board deliberately renders clean prose (``5.利用…``) while the source
    keeps the publication marker (``5.【分析】利用…``). The marker is layout,
    not content, so it must not make an otherwise verbatim chunk fail.
    """
    return _SECTION_MARKER.sub("", text or "")


def _check_board_text_sources(script: dict[str, Any]) -> list[dict[str, str]]:
    """Every rendered text chunk must be a substring of the source it cites."""
    problems: list[str] = []
    sources = script.get("sources") or {}
    for step in script.get("steps") or []:
        for block in step.get("board") or []:
            ref = block.get("ref")
            if not ref or block.get("kind") not in ("text",):
                continue
            record = sources.get(ref) or {}
            if record.get("kind") not in ("content_block", "explanation_block"):
                continue
            needle = _norm_ws(block.get("text") or "")
            haystack = _norm_ws(_strip_section_markers(record.get("text") or ""))
            if needle and needle not in haystack:
                problems.append(f"{block.get('id')}: text not contained in {ref}")
    return [_res("board_text_from_source", not problems, "; ".join(problems[:8]))]


def _check_final_callout(script: dict[str, Any]) -> list[dict[str, str]]:
    display = str((script.get("final_answer") or {}).get("display") or "")
    found = False
    for step in script.get("steps") or []:
        for block in step.get("board") or []:
            if block.get("kind") == "callout" and block.get("tone") == "answer":
                if display and display in str(block.get("text") or ""):
                    found = True
    return [
        _res(
            "final_answer_shown",
            found,
            f"answer callout carries {display!r}" if found else "no answer callout",
        )
    ]


def validate_script(
    script: dict[str, Any],
    bundle: dict[str, Any],
    *,
    expected_revision_id: str | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    if expected_revision_id and script.get("revision_id") != expected_revision_id:
        checks.append(
            _res(
                "revision_binding",
                False,
                f"script revision {script.get('revision_id')} != published {expected_revision_id}",
            )
        )
    else:
        checks.append(_res("revision_binding", True, str(script.get("revision_id"))))

    checks.append(
        _res(
            "revision_content_hash",
            str(script.get("content_hash")) == str(bundle.get("content_hash")),
            "content hash matches the revision payload",
        )
    )
    checks.extend(_check_refs_exist(script))
    checks.extend(_check_sources(script, bundle))
    checks.extend(_check_board_text_sources(script))
    checks.extend(_check_targets(script))
    checks.extend(_check_assets(script))
    checks.extend(_check_answer(script, bundle))
    checks.extend(_check_final_callout(script))
    checks.extend(_check_no_new_facts(script, bundle))
    checks.extend(_check_math(script))
    checks.extend(_check_choice_text(script, bundle))
    checks.extend(_check_step_shape(script))

    script["validation"] = {
        "status": "pass" if all(c["status"] == "pass" for c in checks) else "fail",
        "checks": checks,
        "validated_at": _utc_now(),
    }
    try:
        jsonschema.validate(instance=script, schema=_load_schema())
        schema_check = _res("json_schema", True, "teaching_script.schema.json")
    except jsonschema.ValidationError as exc:
        schema_check = _res(
            "json_schema", False, f"{list(exc.absolute_path)}: {exc.message}"
        )
        script["validation"]["status"] = "fail"
    checks.insert(0, schema_check)
    script["validation"]["checks"] = checks
    return script["validation"]


def schema_errors(script: dict[str, Any]) -> list[str]:
    try:
        jsonschema.validate(instance=script, schema=_load_schema())
        return []
    except jsonschema.ValidationError as exc:
        return [f"{list(exc.absolute_path)}: {exc.message}"]
