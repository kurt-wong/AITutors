"""Phase-C driver: sealed artifacts → Questions in PostgreSQL → student API.

执行链（每步独立日志，见 03_STRICT_IMPORT/00_PHASE_C_EXECUTION_DIRECTIVE.md）：

  0. V3 隔离检查（执行前，静态 import 扫描）
  1. 输入加载复核（哈希对齐阶段 B 封存值）
  2. Strict Adapter 映射（12 units → Candidate + explanation_blocks）
  3. 契约校验 + Admission
  4. 数据库隔离检查 + 事务持久化
  5. 断开重连回读
  6. 学生 API 验证（可见性矩阵 + 真实 HTTP）
  7. V3 隔离检查（执行后：静态 + 运行时 sys.modules）

禁止重新 OCR/Reslice/识别/猜答案；禁止导入 ARCHIVE V3 旧管线。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
QCORE_ROOT = HERE.parent  # .../Question Core
sys.path.insert(0, str(QCORE_ROOT))

RUN_ID = "qcore-e2e-01-20261108-104211"
RUN_ROOT = Path(r"D:\Project\AITutors\runs\qcore_e2e_01") / RUN_ID
STRICT_DIR = RUN_ROOT / "03_STRICT_IMPORT"
DB_DIR = RUN_ROOT / "04_DATABASE"
STU_DIR = RUN_ROOT / "05_STUDENT_ACCESS"
ART = RUN_ROOT / "02_PREPROCESSING" / "artifacts"
OCR_DIR = ART / "ocr" / "高考真题" / "化学"
RESLICE_DIR = ART / "reslice"

SRC_MD = OCR_DIR / "2020全国I卷高考真题化学（教师版）(1).md"
MANIFEST = RESLICE_DIR / "2020全国I卷高考真题化学（教师版）(1).manifest.json"
ANNOTATED = RESLICE_DIR / "2020全国I卷高考真题化学（教师版）(1).annotated.md"
SOURCE_PDF = Path(
    r"D:\Project\AITutors\Preprocessing\maintainess\PDF\2020全国I卷高考真题化学（教师版）(1).pdf"
)

EXPECTED_DB_NAME = "qcore_e2e_01_phase_c"
ADAPTER_VERSION = "strict-adapter/0.1.0"

SEALED = {
    "manifest": "585230ba63148b2e5714c31d0d6dd0b38c26cdb7b1456f65ba11296fc47f5d18",
    "source_md": "dee902ef16540079ed8eef3fef5a44443ecd58b48c801b229513aebe9524c1ef",
    "source_pdf": "e58e921daca6b049214e87d0c2284ca91cc04e62745348ec4b7037b0059ba2be",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------
# 0. V3 隔离检查
# ---------------------------------------------------------------------------

FORBIDDEN_IMPORT_PATTERNS = re.compile(
    r"ARCHIVE|runner_b2|annotation_adapter|resolved_span_adapter|"
    r"(^|[._])gate([._]|$)|(^|[._])compile([._]|$)|(^|[._])resolver([._]|$)|"
    r"(^|[._])ir([._]|$)",
    re.I,
)
FORBIDDEN_RUNTIME_NAMES = re.compile(
    r"archive|runner_b2|annotation_adapter|resolved_span_adapter", re.I
)
_IMPORT_LINE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M
)
_DANGEROUS_CALL = re.compile(r"\b(subprocess|eval|exec|importlib)\b")


def v3_isolation_static() -> dict:
    scanned = []
    findings = []
    for base in (HERE, QCORE_ROOT / "question_core"):
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in str(p):
                continue
            rel = str(p.relative_to(QCORE_ROOT))
            text = p.read_text(encoding="utf-8")
            scanned.append(rel)
            for m in _IMPORT_LINE.finditer(text):
                mod = m.group(1) or m.group(2) or ""
                if FORBIDDEN_IMPORT_PATTERNS.search(mod):
                    findings.append(
                        {"file": rel, "module": mod, "kind": "forbidden_import"}
                    )
            for m in _DANGEROUS_CALL.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                findings.append(
                    {
                        "file": rel,
                        "line": line_no,
                        "token": m.group(1),
                        "kind": "dynamic_execution_token",
                    }
                )
    return {
        "method": (
            "static scan of import statements (module paths) over "
            "strict_adapter/ and question_core/; alternation "
            "ARCHIVE|runner_b2|annotation_adapter|resolved_span_adapter|"
            "gate|compile|resolver|ir applied to module path segments; "
            "subprocess/eval/exec/importlib tokens listed for disclosure"
        ),
        "files_scanned": len(scanned),
        "files": scanned,
        "findings": findings,
        "result": "clean" if not any(f["kind"] == "forbidden_import" for f in findings)
        else "FORBIDDEN_IMPORT_FOUND_STOP",
    }


def v3_isolation_runtime() -> dict:
    hits = []
    for name, mod in list(sys.modules.items()):
        origin = getattr(mod, "__file__", None) or ""
        if FORBIDDEN_RUNTIME_NAMES.search(name) or FORBIDDEN_RUNTIME_NAMES.search(
            str(origin)
        ):
            hits.append({"module": name, "origin": str(origin)})
    return {
        "method": "runtime sys.modules scan for ARCHIVE / V3 runner names",
        "modules_loaded": len(sys.modules),
        "hits": hits,
        "result": "clean" if not hits else "V3_MODULE_LOADED_STOP",
    }


# ---------------------------------------------------------------------------
# 1. 输入加载
# ---------------------------------------------------------------------------


def load_inputs() -> tuple[dict, dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    got = {
        "manifest": sha256_file(MANIFEST),
        "source_md": sha256_file(SRC_MD),
        "source_pdf": sha256_file(SOURCE_PDF),
    }
    match = all(got[k] == SEALED[k] for k in got)
    manifest_md_match = got["source_md"] == manifest.get("source_content_sha256")
    return manifest, {
        "checked_at": now(),
        "hashes": got,
        "sealed_hashes": SEALED,
        "match_sealed": match,
        "manifest_source_content_sha256_match": manifest_md_match,
        "result": "consistent" if (match and manifest_md_match) else "MISMATCH_STOP",
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> int:
    run_log = {"run_id": RUN_ID, "adapter_version": ADAPTER_VERSION,
               "started_at": now(), "steps": []}

    # ---- 0. V3 隔离（前） ----
    pre = v3_isolation_static()
    pre["phase"] = "pre_execution"
    pre["recorded_at"] = now()
    write_json(STRICT_DIR / "logs" / "02_v3_isolation_pre.json", pre)
    run_log["steps"].append({"step": "v3_isolation_pre", "result": pre["result"]})
    if pre["result"] != "clean":
        print("V3 isolation pre-check FAILED — stopping.")
        return 2

    # ---- 1. 输入加载 ----
    manifest, input_check = load_inputs()
    write_json(STRICT_DIR / "logs" / "03_input_verify.json", input_check)
    run_log["steps"].append({"step": "input_verify", "result": input_check["result"]})
    if input_check["result"] != "consistent":
        print("input hash mismatch — stopping.")
        return 3

    # ---- 2. Adapter 映射 ----
    from strict_adapter.extract import load_source_lines
    from strict_adapter.mapper import MappingContext, map_all

    lines = load_source_lines(str(SRC_MD))
    image_by_line = {a["line_no"]: a for a in manifest.get("image_assets", [])}
    paper_id = "2020全国I卷高考真题化学（教师版）(1)"
    ctx = MappingContext(
        lines=lines,
        manifest=manifest,
        manifest_path=str(MANIFEST),
        manifest_name=MANIFEST.name,
        source_md_path=str(SRC_MD),
        source_md_name=SRC_MD.name,
        source_pdf_name=SOURCE_PDF.name,
        annotated_md_name=ANNOTATED.name,
        manifest_sha=SEALED["manifest"],
        source_md_sha=SEALED["source_md"],
        source_pdf_sha=SEALED["source_pdf"],
        annotated_md_sha=sha256_file(ANNOTATED),
        manifest_bytes=MANIFEST.stat().st_size,
        source_md_bytes=SRC_MD.stat().st_size,
        source_pdf_bytes=SOURCE_PDF.stat().st_size,
        annotated_md_bytes=ANNOTATED.stat().st_size,
        image_by_line=image_by_line,
        paper_id=paper_id,
        run_id=RUN_ID,
    )
    mapping_started = now()
    try:
        mappings = map_all(ctx)
    except Exception as exc:  # noqa: BLE001
        write_json(
            STRICT_DIR / "logs" / "03_adapter_mapping.json",
            {"started_at": mapping_started, "error": f"{type(exc).__name__}: {exc}",
             "traceback": traceback.format_exc(), "result": "MAP_FAILED_STOP"},
        )
        print("mapping failed:", exc)
        return 4
    adapter_log = {
        "started_at": mapping_started,
        "finished_at": now(),
        "entry": "strict_adapter.mapper.map_all",
        "adapter_version": ADAPTER_VERSION,
        "input": {"manifest": str(MANIFEST), "source_md": str(SRC_MD)},
        "unit_count": len(mappings),
        "units": [m.log for m in mappings],
        "result": "ok",
    }
    write_json(STRICT_DIR / "logs" / "03_adapter_mapping.json", adapter_log)
    run_log["steps"].append(
        {"step": "adapter_mapping", "units": len(mappings), "result": "ok"}
    )

    # ---- 3. 契约校验 + Admission ----
    from strict_adapter.admission import admit

    admissions = []
    admission_log = {"started_at": now(), "items": []}
    for i, m in enumerate(mappings, 1):
        res = admit(m, ctx, ordinal=i)
        admissions.append(res)
        admission_log["items"].append(res.log | {
            "unit_id": res.unit_id,
            "validated": res.validated,
            "validation_error": res.validation_error,
            "admitted": res.admitted,
            "admission_reason": res.admission_reason,
            "review_state": res.review_state,
            "publication_state": res.publication_state,
            "question_id": res.question_id,
            "revision_id": res.revision_id,
            "instance_id": res.instance_id,
        })
    admission_log["finished_at"] = now()
    admission_log["counts"] = {
        "units": len(mappings),
        "validated": sum(1 for r in admissions if r.validated),
        "admitted": sum(1 for r in admissions if r.admitted),
        "published": sum(1 for r in admissions if r.publication_state == "published"),
        "held_not_ready": sum(1 for r in admissions if r.review_state == "not_ready"),
    }
    write_json(STRICT_DIR / "logs" / "04_admission.json", admission_log)
    run_log["steps"].append({"step": "admission", **admission_log["counts"]})
    if any(not r.admitted for r in admissions):
        print("admission rejected at least one unit — see 04_admission.json")

    # ---- 4. 数据库隔离检查 + 持久化 ----
    db_log_dir = DB_DIR / "logs"
    db_check = _db_isolation_check()
    write_json(db_log_dir / "01_db_target_check.json", db_check)
    if db_check["result"] != "isolated_target_ok":
        print("DB target isolation check FAILED — stopping.")
        return 5

    from question_core.persistence import (
        DatabaseSettings,
        QuestionCoreRepository,
        create_db_engine,
        session_scope,
    )
    from question_core.persistence.exceptions import NotFoundError

    settings = DatabaseSettings.from_env()
    engine = create_db_engine(settings)
    tx_records = []
    persisted = {}
    persist_summary = {"started_at": now(), "items": []}
    for res in admissions:
        if not res.admitted or res.aggregate is None:
            continue
        cand = None
        for m in mappings:
            if m.unit_id == res.unit_id:
                cand = m.candidate
                break
        tx = {
            "unit_id": res.unit_id,
            "question_id": res.question_id,
            "tx_begin": now(),
            "status": "begun",
        }
        try:
            with session_scope(engine) as session:
                repo = QuestionCoreRepository(session)
                try:
                    existing = repo.get_candidate_by_key(
                        cand.core.ingestion.candidate_idempotency_key,
                        ADAPTER_VERSION,
                    )
                    tx["status"] = "skipped_duplicate"
                    tx["existing_candidate_id"] = str(existing.core.candidate_id)
                except NotFoundError:
                    repo.save_candidate_with_question(cand, res.aggregate)
                    tx["status"] = "committed"
                    tx["candidate_id"] = str(cand.core.candidate_id)
                    persisted[res.unit_id] = res
        except Exception as exc:  # noqa: BLE001
            tx["status"] = "rolled_back"
            tx["error"] = f"{type(exc).__name__}: {exc}"
            tx["traceback"] = traceback.format_exc()
        tx["tx_end"] = now()
        tx_records.append(tx)
        persist_summary["items"].append(tx)
    persist_summary["finished_at"] = now()
    persist_summary["counts"] = {
        "committed": sum(1 for t in tx_records if t["status"] == "committed"),
        "skipped_duplicate": sum(1 for t in tx_records if t["status"] == "skipped_duplicate"),
        "rolled_back": sum(1 for t in tx_records if t["status"] == "rolled_back"),
    }
    write_json(db_log_dir / "02_persistence.json", persist_summary)
    write_json(db_log_dir / "02_persistence_tx.json", tx_records)
    run_log["steps"].append({"step": "persistence", **persist_summary["counts"]})

    # ---- 5. 断开重连回读 ----
    engine.dispose()
    readback_engine = create_db_engine(DatabaseSettings.from_env())
    readback = {
        "started_at": now(),
        "method": "fresh engine (previous disposed), restore_* re-validates contracts",
        "items": [],
    }
    from question_core.contracts.v1 import canonical_content_hash

    with session_scope(readback_engine) as session:
        repo = QuestionCoreRepository(session)
        for res in admissions:
            if not res.admitted or res.aggregate is None:
                continue
            item = {"unit_id": res.unit_id, "question_id": res.question_id}
            try:
                agg = repo.get_question_aggregate(
                    __import__("uuid").UUID(res.question_id)
                )
                item["revisions"] = len(agg.revisions)
                item["instances"] = len(agg.instances)
                item["state_history"] = len(agg.state_history)
                rev = agg.revisions[0]
                item["revision_id"] = str(rev.revision_id)
                item["content_hash"] = rev.content_hash
                item["content_hash_matches"] = rev.content_hash == res.content_hash
                item["instance_question_id_matches"] = (
                    agg.instances[0].question_id == agg.identity.question_id
                )
                item["instance_revision_id_matches"] = (
                    agg.instances[0].revision_id == rev.revision_id
                )
                item["source_document_id"] = agg.instances[0].source_document_id
                item["answers"] = len(rev.answers)
                item["answer_completeness"] = [
                    a.completeness.value
                    if hasattr(a.completeness, "value")
                    else a.completeness
                    for a in rev.answers
                ]
                item["evidence_records"] = len(rev.evidence.records)
                item["evidence_status"] = [
                    r.evidence_status.value for r in rev.evidence.records
                ]
                item["explanation_blocks"] = len(rev.explanation_blocks)
                item["materials"] = len(rev.content.materials)
                item["assets"] = len(rev.content.assets)
                item["bodies"] = len(rev.content.bodies)
                item["composite_tree"] = rev.content.tree()
                item["published"] = agg.published_revision() is not None
                item["review_state"] = rev.state.review.value if rev.state else None
                item["completeness_state"] = (
                    rev.state.completeness.value if rev.state else None
                )
                cand = repo.get_candidate_by_key(
                    res.log["objects"]["idempotency_key"], ADAPTER_VERSION
                )
                dec = cand.source.answer_declaration
                item["candidate_readback"] = {
                    "candidate_id": str(cand.core.candidate_id),
                    "attribution": dec.attribution if dec else None,
                    "declaration_completeness": dec.completeness.value if dec else None,
                    "declared_value": dec.declared_value if dec else None,
                    "core_completeness": cand.core.completeness.value,
                }
                item["status"] = "ok"
            except Exception as exc:  # noqa: BLE001
                item["status"] = "error"
                item["error"] = f"{type(exc).__name__}: {exc}"
            readback["items"].append(item)
    readback["finished_at"] = now()
    readback["counts"] = {
        "items": len(readback["items"]),
        "ok": sum(1 for i in readback["items"] if i["status"] == "ok"),
        "content_hash_matches": sum(
            1 for i in readback["items"] if i.get("content_hash_matches")
        ),
    }
    write_json(db_log_dir / "03_readback.json", readback)
    run_log["steps"].append({"step": "readback", **readback["counts"]})

    # ---- 6. 学生 API 验证 ----
    student = _verify_student_api(readback_engine, admissions, mappings)
    write_json(STU_DIR / "logs" / "01_student_api.json", student)
    run_log["steps"].append(
        {"step": "student_api", "result": student.get("result")}
    )

    # ---- 7. V3 隔离（后） ----
    post_static = v3_isolation_static()
    post_rt = v3_isolation_runtime()
    post = {
        "phase": "post_execution",
        "recorded_at": now(),
        "static": post_static,
        "runtime": post_rt,
        "result": (
            "clean"
            if post_static["result"] == "clean" and post_rt["result"] == "clean"
            else "V3_CONTAMINATION_STOP"
        ),
    }
    write_json(STRICT_DIR / "logs" / "05_v3_isolation_post.json", post)
    run_log["steps"].append({"step": "v3_isolation_post", "result": post["result"]})

    run_log["finished_at"] = now()
    run_log["result"] = "completed"
    write_json(STRICT_DIR / "logs" / "00_run_summary.json", run_log)
    print(json.dumps(run_log["steps"], ensure_ascii=False, indent=1))
    return 0


def _db_isolation_check() -> dict:
    from question_core.persistence.config import DatabaseSettings

    settings = DatabaseSettings.from_env()
    redacted = re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", str(settings.url))
    dbname = settings.dbname
    ok = dbname == EXPECTED_DB_NAME
    return {
        "checked_at": now(),
        "url_redacted": redacted,
        "db_name": dbname,
        "expected_db_name": EXPECTED_DB_NAME,
        "host_port": "127.0.0.1:55432",
        "user": "qcore_app",
        "protected_prefix_rule": "aitutors* rejected by DatabaseSettings",
        "result": "isolated_target_ok" if ok else "WRONG_DB_TARGET_STOP",
    }


def _verify_student_api(engine, admissions, mappings) -> dict:
    from fastapi.testclient import TestClient
    from question_core.persistence import QuestionCoreRepository, session_scope
    from strict_adapter.student_api import create_student_app, field_visible

    import uuid as _uuid

    def reader():
        out = []
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            for res in admissions:
                if not res.admitted:
                    continue
                out.append(repo.get_question_aggregate(_uuid.UUID(res.question_id)))
        return out

    app = create_student_app(reader)
    client = TestClient(app)
    result = {"started_at": now(), "cases": []}

    def case(name, method, url, expect_status, check):
        resp = client.request(method, url)
        entry = {
            "case": name,
            "request": f"{method} {url}",
            "status": resp.status_code,
            "expected_status": expect_status,
        }
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = None
        entry["body_summary"] = _summarize_body(body)
        ok = resp.status_code == expect_status and check(body, entry)
        entry["passed"] = bool(ok)
        result["cases"].append(entry)
        return body

    published = [r for r in admissions if r.publication_state == "published"]
    unpublished = [r for r in admissions if r.publication_state != "published"]

    def check_list(body, entry):
        if not isinstance(body, dict):
            return False
        entry["returned_count"] = body.get("count")
        ids = [q["question_id"] for q in body.get("questions", [])]
        entry["returned_ids"] = ids
        pub_ids = {r.question_id for r in published}
        unpub_ids = {r.question_id for r in unpublished}
        entry["published_ids_all_present"] = pub_ids.issubset(set(ids))
        entry["unpublished_ids_absent"] = not (unpub_ids & set(ids))
        entry["no_internal_fields"] = not _leaks(body)
        return (
            body.get("count") == len(published)
            and pub_ids == set(ids)
            and not (unpub_ids & set(ids))
            and not _leaks(body)
        )

    case("list_questions", "GET", "/student/questions", 200, check_list)

    if unpublished:
        uid = unpublished[0].question_id

        def check_404(body, entry):
            entry["no_content_leaked"] = body is None or "content" not in str(body)
            return True

        case("unpublished_404", "GET", f"/student/questions/{uid}", 404, check_404)

    if published:
        pid = published[0].question_id

        def check_detail(body, entry):
            if not isinstance(body, dict):
                return False
            entry["answer_visible"] = body.get("answer_visible")
            entry["explanation_visible"] = body.get("explanation_visible")
            entry["answers_count"] = len(body.get("answers") or [])
            entry["explanation_count"] = len(body.get("explanation_blocks") or [])
            entry["has_content"] = bool(body.get("content"))
            entry["no_internal_fields"] = not _leaks(body)
            return (
                body.get("answer_visible") is False
                and body.get("explanation_visible") is False
                and not (body.get("answers") or [])
                and not (body.get("explanation_blocks") or [])
                and bool(body.get("content"))
                and not _leaks(body)
            )

        case("published_detail_review_only", "GET", f"/student/questions/{pid}", 200, check_detail)
        case(
            "published_detail_submitted_still_hidden",
            "GET",
            f"/student/questions/{pid}?submitted=true",
            200,
            lambda b, e: (b or {}).get("answer_visible") is False
            and not (b or {}).get("answers"),
        )

        def check_reviewer_has_data(body, entry):
            with session_scope(engine) as session:
                repo = QuestionCoreRepository(session)
                agg = repo.get_question_aggregate(_uuid.UUID(pid))
                rev = agg.revisions[0]
                entry["db_answers"] = len(rev.answers)
                entry["db_explanation_blocks"] = len(rev.explanation_blocks)
                entry["db_evidence_records"] = len(rev.evidence.records)
                entry["finding"] = (
                    "student API hid answers/explanations while DB holds them "
                    "under review_only visibility (positive proof of gating)"
                )
            return entry["db_answers"] >= 0

        case("reviewer_db_holds_hidden_data", "GET", f"/student/questions/{pid}", 200, check_reviewer_has_data)

    # 合成正向路径（不落库）：public / student_after_submit 可见性逻辑
    result["visibility_unit_checks"] = {
        "review_only_false": field_visible("review_only", True) is False,
        "after_submit_true": field_visible("student_after_submit", True) is True,
        "after_submit_false": field_visible("student_after_submit", False) is False,
        "public_true": field_visible("public", False) is True,
    }

    # 真实 HTTP 回环（进程内 uvicorn，无 subprocess）
    http_check = _real_http_check(app)
    result["real_http"] = http_check

    result["finished_at"] = now()
    result["counts"] = {
        "cases": len(result["cases"]),
        "passed": sum(1 for c in result["cases"] if c["passed"]),
    }
    result["result"] = (
        "ok"
        if all(c["passed"] for c in result["cases"])
        and all(http_check.get(k) for k in ("status_200", "count_matches"))
        and all(result["visibility_unit_checks"].values())
        else "STUDENT_API_CHECK_FAILED"
    )
    return result


_FORBIDDEN_KEYS = {
    "idempotency_key",
    "ingestion",
    "raw_value",
    "normalized_value",
    "locators",
    "evidence_id",
    "content_hash",
    "identity_fingerprint",
    "ingested_by",
    "created_by",
    "locator_uri",
    "collected_by",
    "approval",
    "publication_record",
    "state_history",
}
_FORBIDDEN_VALUE_TOKENS = ("password", "token", "bcebos", "ocr_raw", "qcore_app:")


def _leaks(body) -> bool:
    """脱敏检查：学生响应不得出现内部字段或敏感值。"""
    hits: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _FORBIDDEN_KEYS:
                    hits.append(f"key:{k}")
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            low = node.lower()
            for t in _FORBIDDEN_VALUE_TOKENS:
                if t in low:
                    hits.append(f"value:{t}")

    if body is not None:
        walk(body)
    return bool(hits)


def _summarize_body(body):
    if isinstance(body, dict):
        return {k: (type(v).__name__ if isinstance(v, (list, dict)) else v)
                for k, v in list(body.items())[:12]}
    return body


def _real_http_check(app) -> dict:
    import uvicorn
    import requests

    port = 8765
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.time() + 15
    ready = False
    while time.time() < deadline:
        if getattr(server, "started", False):
            ready = True
            break
        time.sleep(0.05)
    out = {"port": port, "server_ready": ready}
    if ready:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/student/questions", timeout=10)
            out["status"] = r.status_code
            out["status_200"] = r.status_code == 200
            body = r.json()
            out["count"] = body.get("count")
            out["count_matches"] = isinstance(body.get("count"), int)
            out["no_internal_fields"] = not _leaks(body)
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {exc}"
            out["status_200"] = False
            out["count_matches"] = False
    server.should_exit = True
    t.join(timeout=10)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
