"""HTTP API for photo search, lesson access and teaching bundles (pre-prod).

Security model
--------------
* ``X-TSC-Token`` (service token) is required for every ``/api/*`` call except
  a signed lesson-bundle read. Only DeepTutor's server-side proxy holds it.
* A browser (Interactive Lesson iframe) never sees the service token; it gets a
  short-lived HMAC token scoped to one ``question_id`` + ``revision_id`` from
  ``POST /api/lesson-access`` (itself service-authenticated).
* ``/health`` is public but contains no content.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .auth import constant_time_equal, issue_lesson_token, verify_lesson_token
from .compiler import CompileError
from .config import Settings, ensure_dirs
from .photo.ocr_client import ocr_bytes
from .photo.search import persist_search, search_text
from .qcore_source import load_bundle, load_catalog, load_meta
from .semantic.question_structure import analyze_page
from .service import get_or_compile, teaching_bundle

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


class TextSearchRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    use_llm: bool | None = None


class LessonAccessRequest(BaseModel):
    question_id: str = Field(min_length=8, max_length=64)
    revision_id: str | None = Field(default=None, max_length=64)
    ttl_seconds: int | None = Field(default=None, ge=60, le=3600)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _no_store(response: JSONResponse) -> JSONResponse:
    response.headers["Cache-Control"] = "no-store"
    return response


def _auth_error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"detail": detail},
        headers={"Cache-Control": "no-store"},
    )


def create_app(settings: Settings) -> FastAPI:
    ensure_dirs(settings)
    app = FastAPI(title="teaching-script-compiler", version="1.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    jobs_dir = settings.data_dir / "photo" / "jobs"
    uploads_dir = settings.data_dir / "photo" / "uploads"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tsc-ocr")
    job_lock = threading.Lock()

    def job_path(job_id: str) -> Path:
        return jobs_dir / f"{job_id}.json"

    def read_job(job_id: str) -> dict[str, Any]:
        path = job_path(job_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="job not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def write_job(job: dict[str, Any]) -> None:
        path = job_path(str(job["job_id"]))
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8", newline=""
        )
        tmp.replace(path)

    def run_job(job_id: str, content: bytes, filename: str, use_llm: bool | None) -> None:
        with job_lock:
            job = read_job(job_id)
            job.update({"status": "running", "updated_at": _utc_now()})
            write_job(job)
        started = time.time()
        try:
            ocr = ocr_bytes(
                settings,
                content,
                filename=filename,
                timeout_seconds=settings.ocr_timeout_s,
                max_attempts=settings.ocr_max_attempts,
            )
            if ocr.get("status") != "ok":
                with job_lock:
                    job = read_job(job_id)
                    job.update(
                        {
                            "status": "failed",
                            "stage": "ocr",
                            "error": ocr.get("error") or "OCR failed",
                            "ocr": {k: ocr.get(k) for k in ("engine", "error", "duration_s")},
                            "duration_s": round(time.time() - started, 1),
                            "updated_at": _utc_now(),
                        }
                    )
                    write_job(job)
                return
            result = search_text(settings, ocr["text"], use_llm=use_llm)
            result["structure"] = analyze_page(ocr["text"]).to_dict()
            result["ocr"] = {
                "status": "ok",
                "engine": ocr.get("engine"),
                "pages": ocr.get("pages"),
                "duration_s": ocr.get("duration_s"),
                "job_id": ocr.get("job_id"),
                "text": ocr["text"],
            }
            persist_search(settings, result, ocr_text=ocr["text"])
            with job_lock:
                job = read_job(job_id)
                job.update(
                    {
                        "status": "succeeded",
                        "stage": "done",
                        "search_id": result["search_id"],
                        "result": result,
                        "duration_s": round(time.time() - started, 1),
                        "updated_at": _utc_now(),
                    }
                )
                write_job(job)
        except Exception as exc:  # noqa: BLE001 - job must reach a terminal state
            with job_lock:
                job = read_job(job_id)
                job.update(
                    {
                        "status": "failed",
                        "stage": "search",
                        "error": f"{type(exc).__name__}: {exc}",
                        "duration_s": round(time.time() - started, 1),
                        "updated_at": _utc_now(),
                    }
                )
                write_job(job)

    @app.middleware("http")
    async def auth_guard(request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if request.method == "OPTIONS" or path == "/health" or not path.startswith("/api/"):
            return await call_next(request)
        if not settings.require_auth:
            return await call_next(request)

        # Bundle reads may use a short-lived, question-scoped token instead of
        # the service token (the Interactive Lesson iframe cannot hold secrets).
        if path.startswith("/api/teaching-bundles/"):
            question_id = path.rsplit("/", 1)[-1]
            service_header = request.headers.get("X-TSC-Token", "")
            if settings.service_token and constant_time_equal(service_header, settings.service_token):
                return await call_next(request)
            token = request.query_params.get("access_token", "")
            if token:
                ok, reason = verify_lesson_token(
                    settings.signing_secret,
                    token,
                    question_id,
                    request.query_params.get("revision_id"),
                )
                if ok:
                    return await call_next(request)
                return _auth_error(401, f"invalid lesson token: {reason}")
            return _auth_error(401, "missing service token or access_token")

        if not settings.service_token:
            return _auth_error(503, "service authentication is not configured")
        header = request.headers.get("X-TSC-Token", "")
        if not header or not constant_time_equal(header, settings.service_token):
            return _auth_error(401, "invalid or missing service token")
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, Any]:
        meta = load_meta(settings)
        scripts_index = settings.data_dir / "scripts" / "index.json"
        script_count = 0
        if scripts_index.is_file():
            try:
                script_count = len(json.loads(scripts_index.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                script_count = 0
        return {
            "status": "ok",
            "auth_required": settings.require_auth,
            "service_token_configured": bool(settings.service_token),
            "signing_configured": bool(settings.signing_secret),
            "qcore_snapshot": {
                "built_at": meta.get("built_at"),
                "database": meta.get("database"),
                "read_only_transaction": meta.get("read_only_transaction"),
                "published_bundles": (meta.get("counts") or {}).get("published_bundles"),
            },
            "scripts_cached": script_count,
            "llm_rerank": settings.llm_rerank,
        }

    @app.get("/api/catalog")
    def catalog(subject: str | None = Query(default=None)) -> JSONResponse:
        entries = load_catalog(settings)
        if subject:
            entries = [e for e in entries if e.get("subject") == subject]
        return _no_store(
            JSONResponse(
                {
                    "count": len(entries),
                    "questions": [
                        {
                            "question_id": e["question_id"],
                            "revision_id": e["revision_id"],
                            "source_document_id": e.get("source_document_id"),
                            "printed_number": e.get("printed_number"),
                            "question_type": e.get("question_type"),
                            "subject": e.get("subject"),
                            "has_image": e.get("has_image"),
                            "has_table": e.get("has_table"),
                            "has_math": e.get("has_math"),
                        }
                        for e in entries
                    ],
                }
            )
        )

    def _validate_upload(file: UploadFile, content: bytes) -> str:
        if not content:
            raise HTTPException(status_code=400, detail="empty upload")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="upload too large (12MB)")
        suffix = Path(file.filename or "photo.jpg").suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=415, detail=f"unsupported file type: {suffix}")
        return suffix

    @app.post("/api/search/photo/jobs", status_code=202)
    async def create_search_job(
        file: UploadFile = File(...), use_llm: bool | None = None
    ) -> JSONResponse:
        content = await file.read()
        suffix = _validate_upload(file, content)
        job_id = uuid.uuid4().hex[:20]
        upload_path = uploads_dir / f"job-{job_id}{suffix}"
        upload_path.write_bytes(content)
        job = {
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "file": upload_path.name,
            "ocr_timeout_s": settings.ocr_timeout_s,
        }
        with job_lock:
            write_job(job)
        executor.submit(run_job, job_id, content, upload_path.name, use_llm)
        return _no_store(JSONResponse(job, status_code=202))

    @app.get("/api/search/jobs/{job_id}")
    def get_search_job(job_id: str) -> JSONResponse:
        with job_lock:
            job = read_job(job_id)
        return _no_store(JSONResponse(job))

    @app.post("/api/lesson-access")
    def lesson_access(body: LessonAccessRequest) -> JSONResponse:
        try:
            bundle = load_bundle(settings, body.question_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        revision_id = str(bundle.get("revision_id"))
        if body.revision_id and body.revision_id != revision_id:
            raise HTTPException(
                status_code=409,
                detail="revision_id is not the currently published revision",
            )
        ttl = body.ttl_seconds or settings.lesson_token_ttl_s
        if not settings.signing_secret:
            raise HTTPException(status_code=503, detail="lesson signing is not configured")
        token, expires_at = issue_lesson_token(
            settings.signing_secret, body.question_id, revision_id, ttl
        )
        return _no_store(
            JSONResponse(
                {
                    "question_id": body.question_id,
                    "revision_id": revision_id,
                    "expires_at": expires_at,
                    "ttl_seconds": ttl,
                    "access_token": token,
                }
            )
        )

    @app.post("/api/search/text")
    def search_text_api(body: TextSearchRequest) -> JSONResponse:
        result = search_text(settings, body.text, use_llm=body.use_llm)
        result["structure"] = analyze_page(body.text).to_dict()
        persist_search(settings, result, ocr_text=body.text)
        return _no_store(JSONResponse(result))

    @app.post("/api/search/photo")
    async def search_photo(
        file: UploadFile = File(...), use_llm: bool | None = None
    ) -> JSONResponse:
        """Synchronous compatibility endpoint (small uploads, internal tools)."""
        content = await file.read()
        suffix = _validate_upload(file, content)
        upload_path = uploads_dir / f"{uuid.uuid4().hex}{suffix}"
        upload_path.write_bytes(content)
        ocr = ocr_bytes(
            settings,
            content,
            filename=upload_path.name,
            timeout_seconds=settings.ocr_timeout_s,
            max_attempts=settings.ocr_max_attempts,
        )
        if ocr.get("status") != "ok":
            return _no_store(
                JSONResponse(
                    status_code=503,
                    content={
                        "decision": "ocr_failed",
                        "message": "OCR 服务未能返回可用文本，本轮不进入题目匹配。",
                        "ocr": ocr,
                    },
                )
            )
        result = search_text(settings, ocr["text"], use_llm=use_llm)
        result["structure"] = analyze_page(ocr["text"]).to_dict()
        result["ocr"] = {
            "status": "ok",
            "engine": ocr.get("engine"),
            "pages": ocr.get("pages"),
            "duration_s": ocr.get("duration_s"),
            "job_id": ocr.get("job_id"),
            "text": ocr["text"],
        }
        persist_search(settings, result, ocr_text=ocr["text"], image_path=upload_path)
        return _no_store(JSONResponse(result))

    @app.get("/api/search/{search_id}")
    def get_search(search_id: str) -> JSONResponse:
        path = settings.data_dir / "photo" / search_id / "result.json"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="search not found")
        return _no_store(JSONResponse(json.loads(path.read_text(encoding="utf-8"))))

    @app.get("/api/teaching-bundles/{question_id}")
    def bundle_api(
        question_id: str,
        revision_id: str | None = Query(default=None),
        language: str = Query(default="zh-CN"),
        init_step: str | None = Query(default=None),
    ) -> JSONResponse:
        try:
            if revision_id is not None:
                bundle = load_bundle(settings, question_id)
                if str(bundle.get("revision_id")) != revision_id:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "revision_id is not the currently published revision; "
                            "old revisions keep their own script but are not served "
                            "as the current lesson"
                        ),
                    )
            payload = teaching_bundle(
                settings, question_id, language=language, init_step=init_step
            )
            return _no_store(JSONResponse(payload))
        except CompileError as exc:
            raise HTTPException(
                status_code=422, detail={"code": exc.code, "message": exc.message}
            ) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/teaching-scripts/{question_id}")
    def script_api(
        question_id: str,
        language: str = Query(default="zh-CN"),
        force: bool = Query(default=False),
    ) -> JSONResponse:
        try:
            script, bundle, from_cache = get_or_compile(
                settings, question_id, language=language, force=force
            )
            return _no_store(
                JSONResponse(
                    {
                        "from_cache": from_cache,
                        "content_hash": bundle.get("content_hash"),
                        "script": script,
                    }
                )
            )
        except CompileError as exc:
            raise HTTPException(
                status_code=422, detail={"code": exc.code, "message": exc.message}
            ) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app
