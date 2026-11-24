"""HTTP API for the photo search and teaching bundles (pilot deployment)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .compiler import CompileError
from .config import Settings, ensure_dirs
from .qcore_source import load_bundle, load_catalog, load_meta
from .service import get_or_compile, teaching_bundle
from .photo.ocr_client import ocr_bytes
from .photo.search import persist_search, search_text

MAX_UPLOAD_BYTES = 12 * 1024 * 1024


class TextSearchRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    use_llm: bool | None = None


def _no_store(response: JSONResponse) -> JSONResponse:
    response.headers["Cache-Control"] = "no-store"
    return response


def create_app(settings: Settings) -> FastAPI:
    ensure_dirs(settings)
    app = FastAPI(title="teaching-script-compiler", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        meta = load_meta(settings)
        scripts_dir = settings.data_dir / "scripts" / "index.json"
        script_count = 0
        if scripts_dir.is_file():
            try:
                script_count = len(json.loads(scripts_dir.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                script_count = 0
        return {
            "status": "ok",
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
                            "title": (e.get("stem_text") or "")[:60],
                        }
                        for e in entries
                    ],
                }
            )
        )

    @app.post("/api/search/text")
    def search_text_api(body: TextSearchRequest) -> JSONResponse:
        result = search_text(settings, body.text, use_llm=body.use_llm)
        persist_search(settings, result, ocr_text=body.text)
        return _no_store(JSONResponse(result))

    @app.post("/api/search/photo")
    async def search_photo(file: UploadFile = File(...), use_llm: bool | None = None) -> JSONResponse:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="empty upload")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="upload too large (12MB)")
        suffix = Path(file.filename or "photo.jpg").suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".pdf"}:
            raise HTTPException(status_code=415, detail=f"unsupported file type: {suffix}")
        upload_dir = settings.data_dir / "photo" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_path = upload_dir / f"{uuid.uuid4().hex}{suffix}"
        upload_path.write_bytes(content)

        ocr = ocr_bytes(settings, content, filename=upload_path.name)
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
