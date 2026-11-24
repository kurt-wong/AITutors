"""Controlled LLM rerank for photo matching.

The model answers exactly one question: *does this OCR text describe that
candidate question?* It returns ids and scores only. Any id not in the input is
dropped, and any free-form text it writes is ignored — the LLM can never add a
question or a fact to the retrieval result.
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from ..config import Settings

SYSTEM_PROMPT = """你是题目匹配判定器。输入是一段由手机拍照 OCR 得到的题目文本，以及若干候选题目
（来自题库 Question Core）。你的唯一任务是判断：OCR 文本描述的是不是同一个题目。

规则：
1. 只能对给定候选逐条打分，不得新增题目，不得补充题干条件、答案或解析。
2. 只看文本与结构是否同一道题：数字、公式、选项、表格、图形描述、语句是否对应。
3. 输出 JSON：{"matches":[{"question_id":"...","match":0.0,"verdict":"match|partial|no"}]}
4. match 取 0~1；只有明显同一道题才可给 match。无法判断时输出 partial 或 no。
5. 不要输出任何解释性文字。"""


def _strip_json(text: str) -> str:
    match = re.search(r"\{.*\}", text or "", re.S)
    return match.group(0) if match else ""


def judge_candidates(
    settings: Settings,
    ocr_text: str,
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Return ({question_id: {match, verdict}}, error). Never raises."""
    if not settings.llm_api_key:
        return {}, "llm key not configured"
    if not candidates:
        return {}, None
    payload_candidates = [
        {
            "question_id": c["question_id"],
            "printed_number": c.get("printed_number"),
            "source": c.get("source_document_id"),
            "stem": (c.get("stem_text") or "")[:700],
            "options": (c.get("options_text") or "")[:700],
        }
        for c in candidates
    ]
    user = json.dumps(
        {"ocr_text": ocr_text[:3500], "candidates": payload_candidates},
        ensure_ascii=False,
    )
    body = {
        "model": settings.llm_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    }
    try:
        response = requests.post(
            f"{settings.llm_base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60,
        )
        if response.status_code != 200:
            return {}, f"llm HTTP {response.status_code}"
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(_strip_json(content))
    except Exception as exc:  # noqa: BLE001 - retrieval degrades, never fabricates
        return {}, f"llm error: {exc}"

    allowed = {c["question_id"] for c in candidates}
    out: dict[str, dict[str, Any]] = {}
    for item in parsed.get("matches") or []:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or "")
        if qid not in allowed:
            continue
        try:
            score = float(item.get("match"))
        except (TypeError, ValueError):
            continue
        score = max(0.0, min(1.0, score))
        verdict = str(item.get("verdict") or "").lower()
        if verdict not in {"match", "partial", "no"}:
            verdict = "match" if score >= 0.75 else ("partial" if score >= 0.4 else "no")
        out[qid] = {"match": round(score, 4), "verdict": verdict}
    return out, None
