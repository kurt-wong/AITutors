"""Admission: contract validation → admission decision → state binding.

准入原则（Owner 裁决）：可确定性映射的 Unit 一律准入为 Question
（不因答案不完整丢题）。Admission 只绑定初始状态，不自动批准、不自动发布
（QCORE-ADMISSION-01）：
  complete   → complete   + pending_review + unpublished（待人审）
  incomplete → incomplete + not_ready     + unpublished（Rule 1 不得 approve）
批准与发布是后续人审动作（state.py transitions），本模块不代行。

不复用 V3 Gate/Admission 实现——本模块是为当前 Strict Adapter 新写的确定性
准入步骤。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from question_core.contracts.v1 import (
    Completeness,
    QuestionAggregate,
    QuestionIdentity,
    QuestionInstance,
    Revision,
    StateSnapshot,
    new_id,
)
from question_core.contracts.v1 import candidate_adapter

from .mapper import MappingContext, UnitMapping


@dataclass
class AdmissionResult:
    unit_id: str
    validated: bool
    validation_error: str | None
    admitted: bool
    admission_reason: str
    review_state: str
    publication_state: str
    question_id: str
    revision_id: str
    instance_id: str
    content_hash: str
    aggregate: object = None
    log: dict = field(default_factory=dict)


def admit(
    mapping: UnitMapping, ctx: MappingContext, ordinal: int = 1
) -> AdmissionResult:
    unit_id = mapping.unit_id
    log: dict = {"unit_id": unit_id}

    # ---- 1. 契约校验（真实 validator，不是模拟）----
    try:
        candidate_adapter.validate_python(
            mapping.candidate.model_dump(mode="json")
        )
        validated, verr = True, None
    except Exception as exc:  # noqa: BLE001 — 记录具体错误
        validated, verr = False, f"{type(exc).__name__}: {exc}"
    log["contract_validation"] = {"passed": validated, "error": verr}
    if not validated:
        return AdmissionResult(
            unit_id=unit_id,
            validated=False,
            validation_error=verr,
            admitted=False,
            admission_reason=f"contract validation failed: {verr}",
            review_state="",
            publication_state="",
            question_id="",
            revision_id="",
            instance_id="",
            content_hash=mapping.content_hash,
            log=log,
        )

    # ---- 2. Admission 决策 ----
    # 全部可确定性映射且通过契约校验的 Unit 准入；不完整答案保留不完整状态。
    admitted = True
    reason = (
        "contract validation passed; mapped deterministically from sealed "
        "manifest; admitted as Question with declared completeness "
        f"{mapping.completeness}"
    )
    log["admission"] = {"admitted": admitted, "reason": reason}

    # ---- 3. 状态绑定（初始态；不自动批准、不自动发布）----
    qid = new_id()
    rid = new_id()
    iid = new_id()
    m = mapping.candidate
    content = m.core.content

    # 按真实 completeness 绑定初始态（QCORE-ADMISSION-01）：
    # complete 也只进 pending_review——批准/发布是人审动作，Admission 不代行；
    # Rule 1: incomplete 不得 approve，保持 not_ready。
    if m.core.completeness == Completeness.COMPLETE:
        snapshot = StateSnapshot(
            revision_id=rid,
            content_hash=mapping.content_hash,
            completeness=Completeness.COMPLETE,
            review="pending_review",
            publication="unpublished",
        )
        review_state, pub_state = "pending_review", "unpublished"
    else:
        snapshot = StateSnapshot(
            revision_id=rid,
            content_hash=mapping.content_hash,
            completeness=Completeness.INCOMPLETE,
            review="not_ready",
            publication="unpublished",
        )
        review_state, pub_state = "not_ready", "unpublished"
    history = (snapshot,)
    log["state"] = {
        "review": review_state,
        "publication": pub_state,
        "completeness": mapping.completeness,
        "history_len": len(history),
        "auto_approve": False,
        "auto_publish": False,
        # 遗留 state_plan 字段不再驱动任何状态动作，仅登记以备审计
        "state_plan_not_executed": mapping.state_plan,
    }

    revision = Revision.create(
        question_id=qid,
        revision_id=rid,
        revision_number=1,
        question_type=m.core.question_type,
        content=content,
        answers=m.core.answers,
        explanation_blocks=mapping.explanation_blocks,
        evidence=m.core.evidence,
        answer_visibility=m.core.answer_visibility,
        explanation_visibility=m.core.explanation_visibility,
        created_by=ctx.run_id or "strict-adapter-admission",
        change_note="initial revision mapped by strict-adapter from sealed manifest",
        state=snapshot,
    )

    instance = QuestionInstance(
        instance_id=iid,
        question_id=qid,
        revision_id=rid,
        source_document_id=ctx.paper_id,
        printed_number=mapping.instance_fields.get("printed_number"),
        question_numbers=mapping.instance_fields.get("question_numbers") or (),
        section=mapping.instance_fields.get("section"),
        line_start=mapping.instance_fields.get("line_start"),
        line_end=mapping.instance_fields.get("line_end"),
        ordinal=ordinal,
        note=f"occurrence in {ctx.source_pdf_name}",
    )

    aggregate = QuestionAggregate(
        identity=QuestionIdentity(
            question_id=qid,
            identity_fingerprint=m.core.identity_fingerprint,
        ),
        revisions=(revision,),
        instances=(instance,),
        state_history=tuple(history),
    )
    log["objects"] = {
        "question_id": str(qid),
        "revision_id": str(rid),
        "instance_id": str(iid),
        "content_hash": revision.content_hash,
        "candidate_id": str(m.core.candidate_id),
        "idempotency_key": m.core.ingestion.candidate_idempotency_key,
    }

    return AdmissionResult(
        unit_id=unit_id,
        validated=True,
        validation_error=None,
        admitted=admitted,
        admission_reason=reason,
        review_state=review_state,
        publication_state=pub_state,
        question_id=str(qid),
        revision_id=str(rid),
        instance_id=str(iid),
        content_hash=revision.content_hash,
        aggregate=aggregate,
        log=log,
    )
