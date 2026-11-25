"""Photo-side OCR: PaddleOCR-VL job client (isolated from Preprocessing).

This pilot does **not** modify the Preprocessing pipeline. It submits a
single-question image (wrapped into a one-page PDF, the shape the OCR API
documents) and returns the markdown the API produces. That text is *retrieval
evidence*: it can select a question, never rewrite one.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from pathlib import Path
from typing import Any

import fitz
import requests
import urllib3

from ..config import Settings

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class OcrError(RuntimeError):
    pass


def _token(settings: Settings) -> str:
    token = (settings.ocr_token or "").strip()
    if token:
        return token
    env = os.environ.get("OCR_API_TOKEN", "").strip()
    if env:
        return env
    path = Path(os.path.expanduser("~")) / ".aitutors" / "ocr_token"
    if path.is_file():
        value = path.read_text(encoding="utf-8-sig").strip()
        if value:
            return value
    raise OcrError(
        "OCR token missing: put OCR_API_TOKEN in Teaching Script Compiler/.env.local"
    )


def image_to_pdf(image_bytes: bytes) -> bytes:
    """Wrap an image into a one-page PDF at 150 dpi so the OCR API accepts it."""
    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)  # A4 fallback
        pix = fitz.Pixmap(image_bytes)
        width, height = pix.width, pix.height
        # Fit the image inside A4 while preserving aspect ratio.
        scale = min(555 / width, 800 / height)
        rect = fitz.Rect(
            20,
            20,
            20 + width * scale,
            20 + height * scale,
        )
        page.insert_image(rect, stream=image_bytes)
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()


def _session(settings: Settings) -> requests.Session:
    session = requests.Session()
    session.verify = False
    if settings.ocr_proxy:
        session.proxies = {"http": settings.ocr_proxy, "https": settings.ocr_proxy}
    return session


def _parse_markdown(jsonl_text: str) -> tuple[str, int]:
    pages: list[str] = []
    for line in jsonl_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            for result in payload["result"]["layoutParsingResults"]:
                pages.append(result["markdown"]["text"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
    return "\n\n---\n\n".join(pages), len(pages)


def ocr_bytes(
    settings: Settings,
    content: bytes,
    *,
    filename: str = "question.png",
    payload_extra: dict[str, Any] | None = None,
    poll_seconds: float = 2.0,
    timeout_seconds: float = 240.0,
    max_attempts: int = 2,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Submit one image/PDF; return ``{status, text, pages, job_id, duration_s}``."""
    token = _token(settings)
    headers = {"Authorization": f"bearer {token}"}
    pdf_bytes = content if content[:4] == b"%PDF" else image_to_pdf(content)
    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }
    if payload_extra:
        optional_payload.update(payload_extra)
    started = time.time()
    last_error = "unknown"
    session = _session(settings)
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            response = session.post(
                settings.ocr_job_url,
                headers=headers,
                data={
                    "model": settings.ocr_model,
                    "optionalPayload": json.dumps(optional_payload),
                },
                files={"file": (filename if filename.endswith(".pdf") else "question.pdf", pdf_bytes, "application/pdf")},
                timeout=180,
            )
            if response.status_code != 200:
                last_error = f"submit HTTP {response.status_code}: {response.text[:200]}"
                time.sleep(3)
                continue
            job_id = response.json()["data"]["jobId"]
            json_url = ""
            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                poll = session.get(
                    f"{settings.ocr_job_url}/{job_id}", headers=headers, timeout=60
                )
                if poll.status_code != 200:
                    last_error = f"poll HTTP {poll.status_code}"
                    break
                state = poll.json()["data"]["state"]
                if state == "done":
                    json_url = poll.json()["data"]["resultUrl"]["jsonUrl"]
                    break
                if state == "failed":
                    last_error = "job state=failed"
                    break
                time.sleep(poll_seconds)
            if not json_url:
                last_error = last_error if last_error != "unknown" else "no result url"
                time.sleep(3)
                continue
            download = session.get(json_url, timeout=120)
            if download.status_code != 200:
                last_error = f"download HTTP {download.status_code}"
                time.sleep(3)
                continue
            text, pages = _parse_markdown(download.text)
            if not text.strip():
                last_error = "empty OCR markdown"
                time.sleep(3)
                continue
            result = {
                "status": "ok",
                "engine": settings.ocr_model,
                "text": text,
                "pages": pages,
                "job_id": job_id,
                "attempts": attempt,
                "duration_s": round(time.time() - started, 1),
                "optional_payload": optional_payload,
            }
            if include_raw:
                raw = download.text
                result["raw_jsonl"] = raw
                result["raw_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            return result
        except Exception as exc:  # noqa: BLE001 - network/API errors are all retryable here
            last_error = f"exception: {exc}"
            time.sleep(3)
    return {
        "status": "failed",
        "engine": settings.ocr_model,
        "error": last_error,
        "attempts": max(1, max_attempts),
        "duration_s": round(time.time() - started, 1),
    }


def ocr_file(settings: Settings, path: Path, **kwargs) -> dict[str, Any]:
    return ocr_bytes(settings, path.read_bytes(), filename=path.name, **kwargs)
