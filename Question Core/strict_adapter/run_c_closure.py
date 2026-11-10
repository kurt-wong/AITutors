"""QCORE-E2E-01-C-CLOSURE 驱动：定点修复 Q10/Q12 的 Evidence/Asset 关联。

范围（Owner 指令）：
* C1 — Q12 两张答案图补 Asset（target_path=/answers）+ ASSET 证据（review_only）。
* C2 — Q10/Q12 DISPUTED 证据 locator 改为 Manifest JSON Pointer。
* 仅创建新 Revision（v2），旧 Revision 不可变保留；不改 Candidate/Manifest/源文件。
* 定点回归 + 学生 API 可见性 + V3 隔离复查。

日志：06_C_CLOSURE/logs/（Run ID 可追溯；不记密码/Token/签名 URL）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

HERE = Path(__file__).resolve().parent
QCORE_ROOT = HERE.parent
sys.path.insert(0, str(QCORE_ROOT))

RUN_ID = "qcore-e2e-01-20261108-104211"
RUN_ROOT = Path(r"D:\Project\AITutors\runs\qcore_e2e_01") / RUN_ID
LOG_DIR = RUN_ROOT / "06_C_CLOSURE" / "logs"
SRC_MD = (
    RUN_ROOT
    / "02_PREPROCESSING/artifacts/ocr/高考真题/化学/2020全国I卷高考真题化学（教师版）(1).md"
)
MANIFEST = (
    RUN_ROOT
    / "02_PREPROCESSING/artifacts/reslice/2020全国I卷高考真题化学（教师版）(1).manifest.json"
)

ANSWER_IMAGES = {
    "img_in_image_box_150_396_396_557": {
        "line_no": 741,
        "sha256": "46b9a8063a8c0d9075ce2af7c0dfa94fc4f04c0255522d09804631742fada131",
        "bytes": 8742,
        "src": "imgs/img_in_image_box_150_396_396_557.jpg",
        "artifact_path": "_imgs/img_in_image_box_150_396_396_557.jpg",
    },
    "img_in_image_box_534_397_602_549": {
        "line_no": 749,
        "sha256": "9e1caf829e03c511a072d01bbe32a0d0f9f31d2bf9c2240450149a6ede64137f",
        "bytes": 4598,
        "src": "imgs/img_in_image_box_534_397_602_549.jpg",
        "artifact_path": "_imgs/img_in_image_box_534_397_602_549.jpg",
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def unit_pointer(manifest: dict, unit_id: str) -> str:
    for i, u in enumerate(manifest.get("units", [])):
        if u.get("unit_id") == unit_id:
            return f"/units/{i}/answer_evidence/value"
    raise ValueError(f"{unit_id} not in manifest units")


def build_new_evidence(rev1, unit_id: str, manifest: dict, ctx_md_name: str,
                       ctx_md_sha: str, add_asset_records: bool):
    """以 rev1 的证据为事实源重建 v2 证据束（全部新 evidence_id）。

    * DISPUTED（preprocessing_manifest）记录：locator 改为 Manifest JSON
      Pointer；raw_value 保持 declared_value 原样；note 追加修正记录。
    * 其余记录逐字段照搬（仅换 evidence_id，note 不动）。
    * Q12：追加两张答案图的 ASSET 证据（review_only，/answers，md 行区）。
    """
    from question_core.contracts.v1 import (
        EvidenceBundle,
        EvidenceRecord,
        EvidenceRole,
        EvidenceStatus,
        SourceKind,
        SourceLocator,
        SourceRef,
        Visibility,
        new_id,
    )

    ptr = unit_pointer(manifest, unit_id)
    records = []
    for rec in rev1.evidence.records:
        d = rec.model_dump(mode="json")
        d["evidence_id"] = str(new_id())
        is_manifest = rec.source.source_kind == SourceKind.PREPROCESSING_MANIFEST
        if is_manifest and rec.evidence_status == EvidenceStatus.DISPUTED:
            d["locators"] = [
                {
                    "kind": "json_pointer",
                    "line_start": None,
                    "line_end": None,
                    "page": None,
                    "bbox": None,
                    "pointer": ptr,
                    "note": None,
                }
            ]
            d["note"] = (
                (rec.note or "")
                + " | C-CLOSURE C2: locator corrected from OCR-md line_range to "
                f"manifest JSON Pointer {ptr}; raw_value retained verbatim "
                "(manifest declared_value, not rewritten)"
            )
        records.append(EvidenceRecord.model_validate(d))

    if add_asset_records:
        for asset_id, meta in ANSWER_IMAGES.items():
            raw_line = SRC_MD.read_text(encoding="utf-8").splitlines()[
                meta["line_no"] - 1
            ]
            records.append(
                EvidenceRecord(
                    evidence_id=new_id(),
                    target_path="/answers",
                    evidence_role=EvidenceRole.ASSET,
                    source=SourceRef(
                        source_id=ctx_md_name,
                        source_kind=SourceKind.SOURCE_MARKDOWN,
                        content_hash=ctx_md_sha,
                        locator_uri=str(SRC_MD),
                    ),
                    locators=(
                        SourceLocator(
                            kind="line_range",
                            line_start=meta["line_no"],
                            line_end=meta["line_no"],
                        ),
                    ),
                    raw_value=raw_line,
                    evidence_status=EvidenceStatus.ACTIVE,
                    visibility=Visibility.REVIEW_ONLY,
                    note=(
                        f"answer figure of {unit_id} (answer_lines region "
                        f"L{meta['line_no']}); review-only evidence asset "
                        f"asset_id={asset_id}; associated to /answers "
                        "(C-CLOSURE C1)"
                    ),
                )
            )
    return EvidenceBundle(records=tuple(records))


def build_new_content(rev1):
    """Q12 v2 content = v1 content + 两张答案区 Asset（target_path=/answers）。"""
    from question_core.contracts.v1 import Asset, QuestionContent

    data = rev1.content.model_dump(mode="json")
    existing = {a["asset_id"] for a in data["assets"]}
    for asset_id, meta in ANSWER_IMAGES.items():
        if asset_id in existing:
            continue
        data["assets"].append(
            {
                "asset_id": asset_id,
                "asset_role": "figure",
                "target_path": "/answers",
                "source_id": SRC_MD.name,
                "page": None,
                "bbox": None,
                "storage_path": meta["artifact_path"],
                "content_hash": meta["sha256"],
                "mime_type": "image/jpeg",
                "width": None,
                "height": None,
                "note": (
                    f"src={meta['src']}; line_no={meta['line_no']}; "
                    f"bytes={meta['bytes']}; ANSWER-AREA figure (answer "
                    "evidence, review-only; NOT student-visible content)"
                ),
            }
        )
    return QuestionContent.model_validate(data)


def main() -> int:
    from question_core.contracts.v1 import (
        Completeness,
        Revision,
        StateSnapshot,
        canonical_content_hash,
        new_id,
    )
    from question_core.persistence import (
        DatabaseSettings,
        QuestionCoreRepository,
        create_db_engine,
        session_scope,
    )

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    md_sha = sha256_file(SRC_MD)
    log: dict = {
        "run_id": RUN_ID,
        "task": "QCORE-E2E-01-C-CLOSURE",
        "started_at": now(),
        "steps": [],
    }

    # 读 Phase C 回读日志拿 question_id（不重算）
    phase_c_rb = json.loads(
        (RUN_ROOT / "04_DATABASE/logs/03_readback.json").read_text(encoding="utf-8")
    )
    qid_by_unit = {it["unit_id"]: it["question_id"] for it in phase_c_rb["items"]}

    engine = create_db_engine(DatabaseSettings.from_env())

    # ---- BEFORE 快照 ----
    # BEFORE 快照（Phase 3 F 作用域确认：下列 ("Q10","Q12") 是**本驱动运行自身**
    # phase_c_rb 单卷报告内的目标 unit 清单，不是 OWNER_ATTRIBUTION_OVERRIDES
    # 式跨卷策略判断；qid_by_unit 只含本运行单卷条目，不会命中其他试卷同名题。
    # 跨卷作用域策略判定一律走 rules.owner_override_reason(paper_id/unit_id)。
    before = {"captured_at": now(), "items": {}}
    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        for unit in ("Q10", "Q12"):
            agg = repo.get_question_aggregate(UUID(qid_by_unit[unit]))
            rev1 = agg.revisions[0]
            payload = json.dumps(
                rev1.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
            before["items"][unit] = {
                "question_id": qid_by_unit[unit],
                "revision_id": str(rev1.revision_id),
                "revision_number": rev1.revision_number,
                "content_hash": rev1.content_hash,
                "payload_sha256": sha256_bytes(payload),
                "assets": len(rev1.content.assets),
                "evidence_records": len(rev1.evidence.records),
                "state_history_len": len(agg.state_history),
                "answers": len(rev1.answers),
                "explanation_blocks": len(rev1.explanation_blocks),
            }
        # 其余 10 题内容哈希基线
        for unit, qid in qid_by_unit.items():
            if unit in ("Q10", "Q12"):
                continue
            agg = repo.get_question_aggregate(UUID(qid))
            before["items"][unit] = {
                "content_hash": agg.revisions[0].content_hash,
                "revision_count": len(agg.revisions),
            }
    write_json(LOG_DIR / "01_before_state.json", before)
    log["steps"].append({"step": "before_snapshot", "items": len(before["items"])})

    # ---- 修复：Q10 / Q12 新 Revision v2 ----
    tx_log = []
    for unit, add_assets in (("Q10", False), ("Q12", True)):
        tx = {"unit": unit, "tx_begin": now(), "status": "begun"}
        try:
            with session_scope(engine) as session:
                repo = QuestionCoreRepository(session)
                qid = UUID(qid_by_unit[unit])
                agg = repo.get_question_aggregate(qid)
                rev1 = agg.revisions[0]
                if len(agg.revisions) != 1 or rev1.revision_number != 1:
                    raise RuntimeError(
                        f"{unit}: unexpected revision state "
                        f"{len(agg.revisions)} revs — refusing to continue"
                    )
                new_evidence = build_new_evidence(
                    rev1,
                    unit,
                    manifest,
                    SRC_MD.name,
                    md_sha,
                    add_asset_records=add_assets,
                )
                new_content = build_new_content(rev1) if add_assets else rev1.content
                new_rid = new_id()
                ch = canonical_content_hash(
                    new_content, *rev1.answers, *rev1.explanation_blocks
                )
                snap = StateSnapshot(
                    revision_id=new_rid,
                    content_hash=ch,
                    completeness=Completeness.INCOMPLETE,
                    review="not_ready",
                    publication="unpublished",
                )
                rev2 = Revision.create(
                    question_id=qid,
                    revision_id=new_rid,
                    revision_number=2,
                    question_type=rev1.question_type,
                    content=new_content,
                    answers=rev1.answers,
                    explanation_blocks=rev1.explanation_blocks,
                    evidence=new_evidence,
                    answer_visibility=rev1.answer_visibility,
                    explanation_visibility=rev1.explanation_visibility,
                    created_by="qcore-e2e-01-c-closure",
                    change_note=(
                        "C-CLOSURE fix revision: "
                        + (
                            "C2 evidence locator corrected to manifest JSON Pointer"
                            + (" + C1 answer figures added as review-only assets"
                               if add_assets else "")
                        )
                        + "; revision 1 preserved immutable; no approval/"
                        "publication inherited (not_ready/unpublished)"
                    ),
                    state=snap,
                )
                repo.add_revision(rev2)
                repo.append_state_snapshot(qid, snap)
                tx.update(
                    {
                        "status": "committed",
                        "question_id": qid_by_unit[unit],
                        "old_revision_id": str(rev1.revision_id),
                        "new_revision_id": str(new_rid),
                        "new_content_hash": ch,
                        "old_content_hash": rev1.content_hash,
                        "content_hash_changed": ch != rev1.content_hash,
                        "new_evidence_records": len(new_evidence.records),
                        "new_assets": len(new_content.assets),
                        "state": "not_ready/unpublished/incomplete",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            tx["status"] = "rolled_back"
            tx["error"] = f"{type(exc).__name__}: {exc}"
            tx["traceback"] = traceback.format_exc()
        tx["tx_end"] = now()
        tx_log.append(tx)
    write_json(LOG_DIR / "02_revision_fix_tx.json", tx_log)
    log["steps"].append(
        {
            "step": "revision_fixes",
            "committed": sum(1 for t in tx_log if t["status"] == "committed"),
            "rolled_back": sum(1 for t in tx_log if t["status"] == "rolled_back"),
        }
    )
    if any(t["status"] != "committed" for t in tx_log):
        print("fix transaction failed — stopping:", json.dumps(tx_log, ensure_ascii=False))
        engine.dispose()
        return 2

    # ---- 断开重连 AFTER 验证 ----
    engine.dispose()
    engine2 = create_db_engine(DatabaseSettings.from_env())
    after = {"captured_at": now(), "items": {}}
    with session_scope(engine2) as session:
        repo = QuestionCoreRepository(session)
        for unit in ("Q10", "Q12"):
            qid = UUID(qid_by_unit[unit])
            agg = repo.get_question_aggregate(qid)
            rev1 = agg.revisions[0]
            rev2 = agg.revisions[1]
            payload1 = json.dumps(
                rev1.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
            item = {
                "question_id": qid_by_unit[unit],
                "revision_count": len(agg.revisions),
                "current_revision_number": agg.current_revision().revision_number,
                "rev1": {
                    "revision_id": str(rev1.revision_id),
                    "content_hash": rev1.content_hash,
                    "payload_sha256": sha256_bytes(payload1),
                    "unchanged_vs_before": sha256_bytes(payload1)
                    == before["items"][unit]["payload_sha256"],
                    "state": (
                        f"{rev1.state.review.value}/"
                        f"{rev1.state.publication.value}"
                        if rev1.state
                        else None
                    ),
                },
                "rev2": {
                    "revision_id": str(rev2.revision_id),
                    "revision_number": rev2.revision_number,
                    "content_hash": rev2.content_hash,
                    "answers": len(rev2.answers),
                    "explanation_blocks": len(rev2.explanation_blocks),
                    "assets": len(rev2.content.assets),
                    "evidence_records": len(rev2.evidence.records),
                    "state": (
                        f"{rev2.state.review.value}/"
                        f"{rev2.state.publication.value}/"
                        f"{rev2.state.completeness.value}"
                        if rev2.state
                        else None
                    ),
                },
                "state_history": [
                    {
                        "revision_id": str(s.revision_id),
                        "review": s.review.value,
                        "publication": s.publication.value,
                        "completeness": s.completeness.value,
                    }
                    for s in agg.state_history
                ],
                "instance_revision_id": str(agg.instances[0].revision_id),
            }
            # C2 断言数据
            disputed = [
                r
                for r in rev2.evidence.records
                if r.evidence_status.value == "disputed"
            ]
            item["rev2_disputed"] = [
                {
                    "source_kind": r.source.source_kind.value,
                    "source_id": r.source.source_id,
                    "locators": [x.model_dump(mode="json") for x in r.locators],
                    "raw_value_prefix": (r.raw_value or "")[:60],
                    "note_has_c2": "C-CLOSURE C2" in (r.note or ""),
                }
                for r in disputed
            ]
            # C1 断言数据（Q12）
            if unit == "Q12":
                ans_assets = [
                    a
                    for a in rev2.content.assets
                    if a.asset_id in ANSWER_IMAGES
                ]
                item["rev2_answer_assets"] = [
                    {
                        "asset_id": a.asset_id,
                        "content_hash": a.content_hash,
                        "storage_path": a.storage_path,
                        "target_path": a.target_path,
                    }
                    for a in ans_assets
                ]
                item["rev2_asset_evidence"] = [
                    {
                        "role": r.evidence_role.value,
                        "visibility": r.visibility.value,
                        "target_path": r.target_path,
                        "locator": r.locators[0].model_dump(mode="json")
                        if r.locators
                        else None,
                        "raw_value_has_img": "<img" in (r.raw_value or ""),
                    }
                    for r in rev2.evidence.records
                    if r.evidence_role.value == "asset"
                ]
            after["items"][unit] = item

        # 其余 10 题不受影响
        for unit, qid in qid_by_unit.items():
            if unit in ("Q10", "Q12"):
                continue
            agg = repo.get_question_aggregate(UUID(qid))
            after["items"][unit] = {
                "content_hash": agg.revisions[0].content_hash,
                "revision_count": len(agg.revisions),
                "unchanged": agg.revisions[0].content_hash
                == before["items"][unit]["content_hash"]
                and len(agg.revisions) == before["items"][unit]["revision_count"],
            }

        # Q8 答案 8 项回读
        agg_q8 = repo.get_question_aggregate(UUID(qid_by_unit["Q8"]))
        ans = agg_q8.revisions[0].answers[0]
        after["q8_answer_items"] = len(ans.answer_value)
        after["q8_answer_items_is_8"] = len(ans.answer_value) == 8
    write_json(LOG_DIR / "03_after_state.json", after)
    log["steps"].append(
        {
            "step": "after_verify",
            "rev1_unchanged": all(
                after["items"][u]["rev1"]["unchanged_vs_before"] for u in ("Q10", "Q12")
            ),
            "others_unchanged": all(
                after["items"][u].get("unchanged")
                for u in after["items"]
                if u not in ("Q10", "Q12")
            ),
            "q8_items": after["q8_answer_items"],
        }
    )

    # ---- 学生 API 可见性 ----
    from strict_adapter.student_api import (
        _content_public,
        build_student_detail,
        create_student_app,
    )
    from fastapi.testclient import TestClient

    def reader():
        out = []
        with session_scope(engine2) as session:
            repo = QuestionCoreRepository(session)
            for qid in qid_by_unit.values():
                out.append(repo.get_question_aggregate(UUID(qid)))
        return out

    client = TestClient(create_student_app(reader))
    stu = {"checked_at": now(), "cases": []}

    r12 = client.get(f"/student/questions/{qid_by_unit['Q12']}")
    stu["cases"].append(
        {
            "case": "Q12 unpublished 404",
            "request": f"GET /student/questions/{qid_by_unit['Q12']}",
            "status": r12.status_code,
            "passed": r12.status_code == 404,
            "body_has_answer_image": "img_in_image_box" in r12.text,
        }
    )
    r10 = client.get(f"/student/questions/{qid_by_unit['Q10']}")
    stu["cases"].append(
        {
            "case": "Q10 unpublished 404",
            "request": f"GET /student/questions/{qid_by_unit['Q10']}",
            "status": r10.status_code,
            "passed": r10.status_code == 404,
            "body_has_evidence": "raw_value" in r10.text,
        }
    )
    # 真实 Q12 v2 content 过学生资产过滤器：两张答案图必须消失
    with session_scope(engine2) as session:
        repo = QuestionCoreRepository(session)
        agg12 = repo.get_question_aggregate(UUID(qid_by_unit["Q12"]))
        rev2 = agg12.revisions[1]
        pub = _content_public(rev2.content)
        asset_ids = [a["asset_id"] for a in pub["assets"]]
        stu["content_filter_on_real_q12_v2"] = {
            "assets_exposed": asset_ids,
            "answer_images_hidden": all(
                a not in asset_ids for a in ANSWER_IMAGES
            ),
            "blob_free_of_answer_image_ids": all(
                a not in json.dumps(pub, ensure_ascii=False)
                for a in ANSWER_IMAGES
            ),
            "passed": all(a not in asset_ids for a in ANSWER_IMAGES),
        }
    rlist = client.get("/student/questions")
    body = rlist.json()
    stu["list_check"] = {
        "status": rlist.status_code,
        "count": body.get("count"),
        "q10_q12_absent": all(
            qid_by_unit[u] not in [q["question_id"] for q in body.get("questions", [])]
            for u in ("Q10", "Q12")
        ),
    }
    stu["result"] = (
        "ok"
        if all(c["passed"] for c in stu["cases"])
        and stu["content_filter_on_real_q12_v2"]["passed"]
        and stu["list_check"]["q10_q12_absent"]
        else "FAILED"
    )
    write_json(LOG_DIR / "04_student_api.json", stu)
    log["steps"].append({"step": "student_api", "result": stu["result"]})

    # ---- V3 隔离复查 ----
    from strict_adapter.run_phase_c import v3_isolation_runtime, v3_isolation_static

    static = v3_isolation_static()
    runtime = v3_isolation_runtime()
    v3 = {
        "checked_at": now(),
        "static_result": static["result"],
        "static_findings": static["findings"],
        "runtime_result": runtime["result"],
        "runtime_hits": runtime["hits"],
        "result": (
            "clean"
            if static["result"] == "clean" and runtime["result"] == "clean"
            else "V3_CONTAMINATION_STOP"
        ),
    }
    write_json(LOG_DIR / "05_v3_isolation_recheck.json", v3)
    log["steps"].append({"step": "v3_isolation_recheck", "result": v3["result"]})

    log["finished_at"] = now()
    log["result"] = "completed"
    write_json(LOG_DIR / "00_closure_run_summary.json", log)
    print(json.dumps(log["steps"], ensure_ascii=False, indent=1))
    engine2.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
