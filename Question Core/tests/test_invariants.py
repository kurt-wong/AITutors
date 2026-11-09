"""Counterexample tests: the four blocking invariants (F1–F4) and the five
non-blocking contract fixes (N1/N5/N7/N8/N9).

Each test constructs the *illegal* shape DSH found and asserts the contract
now rejects it. If any of these pass, the corresponding blocker has
regressed.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError


_HASH_A = "a" * 64
_HASH_B = "b" * 64


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(text="题干", local_id="q"):
    from question_core.contracts.v1 import QuestionBody, QuestionType, TextBlock

    return QuestionBody(
        local_id=local_id,
        question_type=QuestionType.SHORT_ANSWER,
        stem_blocks=[TextBlock(text=text)],
    )


def _content(*bodies):
    from question_core.contracts.v1 import QuestionContent

    return QuestionContent(bodies=list(bodies) or [_body()])


def _evidence(target="/answers/0", value="A", source="s1", role="answer"):
    from question_core.contracts.v1 import (
        EvidenceRecord,
        SourceKind,
        SourceLocator,
        SourceRef,
    )

    return EvidenceRecord(
        target_path=target,
        evidence_role=role,
        source=SourceRef(
            source_id=source,
            source_kind=SourceKind.SOURCE_MARKDOWN,
            content_hash=_HASH_A,
        ),
        locators=[SourceLocator(kind="line_range", line_start=1, line_end=1)],
        raw_value=value,
    )


# ---------------------------------------------------------------------------
# F1 — unresolved critical evidence conflict blocks approval / publication
# ---------------------------------------------------------------------------


class TestF1EvidenceConflictBlocksApproval:
    def test_revision_with_unresolved_critical_conflict_cannot_be_approved(self):
        """DSH counterexample: two contradicting evidence records, conflict
        unresolved and critical, yet the revision could reach ``approved``."""
        from question_core.contracts.v1 import (
            ApprovalRecord,
            Completeness,
            EvidenceBundle,
            EvidenceConflict,
            ReviewState,
            Revision,
            StateSnapshot,
            canonical_content_hash,
        )

        e1 = _evidence(value="B", source="manifest")
        e2 = _evidence(value="C", source="answer_table")
        conflict = EvidenceConflict(
            target_path="/answers/0",
            evidence_ids=[e1.evidence_id, e2.evidence_id],
            is_critical=True,
        )
        bundle = EvidenceBundle(records=[e1, e2], conflicts=[conflict])
        content = _content()
        ch = canonical_content_hash(content)
        rid = uuid.uuid4()
        approval = ApprovalRecord(
            revision_id=rid, content_hash=ch, approved_by="r"
        )
        state = StateSnapshot(
            revision_id=rid,
            content_hash=ch,
            completeness=Completeness.COMPLETE,
            review=ReviewState.APPROVED,
            approval=approval,
        )
        with pytest.raises(ValidationError, match="unresolved critical"):
            Revision(
                revision_id=rid,
                question_id=uuid.uuid4(),
                revision_number=1,
                content_hash=ch,
                question_type="short_answer",
                content=content,
                evidence=bundle,
                state=state,
            )

    def test_revision_with_unresolved_critical_conflict_cannot_be_published(self):
        from question_core.contracts.v1 import (
            Completeness,
            EvidenceBundle,
            EvidenceConflict,
            PublicationRecord,
            PublicationState,
            ReviewState,
            Revision,
            StateSnapshot,
        )

        e1 = _evidence(value="B", source="manifest")
        e2 = _evidence(value="C", source="answer_table")
        conflict = EvidenceConflict(
            target_path="/answers/0",
            evidence_ids=[e1.evidence_id, e2.evidence_id],
            is_critical=True,
        )
        bundle = EvidenceBundle(records=[e1, e2], conflicts=[conflict])
        content = _content()
        ch = __import__(
            "question_core.contracts.v1", fromlist=["x"]
        ).canonical_content_hash(content)
        rid = uuid.uuid4()
        pub_record = PublicationRecord(
            revision_id=rid,
            content_hash=ch,
            state=PublicationState.PUBLISHED,
            acted_by="p",
        )
        state = StateSnapshot(
            revision_id=rid,
            content_hash=ch,
            completeness=Completeness.COMPLETE,
            review=ReviewState.APPROVED,
            publication=PublicationState.PUBLISHED,
            publication_record=pub_record,
            approval=__import__(
                "question_core.contracts.v1", fromlist=["x"]
            ).ApprovalRecord(revision_id=rid, content_hash=ch, approved_by="r"),
        )
        with pytest.raises(ValidationError, match="unresolved critical"):
            Revision(
                revision_id=rid,
                question_id=uuid.uuid4(),
                revision_number=1,
                content_hash=ch,
                question_type="short_answer",
                content=content,
                evidence=bundle,
                state=state,
            )

    def test_resolved_conflict_allows_approval(self):
        """The fix must not over-block: a properly resolved conflict is fine."""
        from question_core.contracts.v1 import (
            ApprovalRecord,
            Completeness,
            ConflictResolution,
            EvidenceBundle,
            EvidenceConflict,
            ReviewState,
            Revision,
            StateSnapshot,
            canonical_content_hash,
        )

        e1 = _evidence(value="B", source="manifest")
        e2 = _evidence(value="C", source="answer_table")
        conflict = EvidenceConflict(
            target_path="/answers/0",
            evidence_ids=[e1.evidence_id, e2.evidence_id],
            is_critical=True,
            resolution=ConflictResolution.HUMAN_ADJUDICATED,
            resolved_by="reviewer:Kurtw",
            winning_evidence_id=e1.evidence_id,
        )
        bundle = EvidenceBundle(records=[e1, e2], conflicts=[conflict])
        content = _content()
        ch = canonical_content_hash(content)
        rid = uuid.uuid4()
        approval = ApprovalRecord(
            revision_id=rid, content_hash=ch, approved_by="r"
        )
        state = StateSnapshot(
            revision_id=rid,
            content_hash=ch,
            completeness=Completeness.COMPLETE,
            review=ReviewState.APPROVED,
            approval=approval,
        )
        rev = Revision(
            revision_id=rid,
            question_id=uuid.uuid4(),
            revision_number=1,
            content_hash=ch,
            question_type="short_answer",
            content=content,
            evidence=bundle,
            state=state,
        )
        assert rev.state.review == ReviewState.APPROVED

    def test_non_critical_conflict_does_not_block(self):
        from question_core.contracts.v1 import (
            ApprovalRecord,
            Completeness,
            EvidenceBundle,
            EvidenceConflict,
            ReviewState,
            Revision,
            StateSnapshot,
            canonical_content_hash,
        )

        e1 = _evidence(value="x", target="/stem")
        e2 = _evidence(value="y", target="/stem", source="s2")
        conflict = EvidenceConflict(
            target_path="/stem",
            evidence_ids=[e1.evidence_id, e2.evidence_id],
            is_critical=False,
        )
        bundle = EvidenceBundle(records=[e1, e2], conflicts=[conflict])
        content = _content()
        ch = canonical_content_hash(content)
        rid = uuid.uuid4()
        approval = ApprovalRecord(
            revision_id=rid, content_hash=ch, approved_by="r"
        )
        state = StateSnapshot(
            revision_id=rid,
            content_hash=ch,
            completeness=Completeness.COMPLETE,
            review=ReviewState.APPROVED,
            approval=approval,
        )
        rev = Revision(
            revision_id=rid,
            question_id=uuid.uuid4(),
            revision_number=1,
            content_hash=ch,
            question_type="short_answer",
            content=content,
            evidence=bundle,
            state=state,
        )
        assert rev.state.review == ReviewState.APPROVED


# ---------------------------------------------------------------------------
# F2 — Strict attribution ↔ Candidate completeness linkage
# ---------------------------------------------------------------------------


class TestF2StrictCompletenessLink:
    def test_not_attributable_with_complete_candidate_rejected(self):
        """DSH counterexample: not_attributable answer but candidate claims
        completeness=complete."""
        from question_core.contracts.v1 import (
            Completeness,
            PreprocessingCandidate,
            PreprocessingSource,
            PreprocessingUnitRef,
            SourceDocumentRef,
            StrictAnswerDeclaration,
        )

        with pytest.raises(ValidationError, match="not_attributable"):
            PreprocessingCandidate(
                core=__import__(
                    "question_core.contracts.v1", fromlist=["x"]
                ).CandidateCore(
                    question_type="short_answer",
                    content=_content(),
                    completeness=Completeness.COMPLETE,
                    ingestion=__import__(
                        "question_core.contracts.v1", fromlist=["x"]
                    ).IngestionIdentity(
                        candidate_idempotency_key="k" * 20,
                        adapter_version="a/1",
                        input_hashes=__import__(
                            "question_core.contracts.v1", fromlist=["x"]
                        ).InputHashes(manifest_hash=_HASH_A),
                    ),
                ),
                source=PreprocessingSource(
                    source_document_id="doc/1",
                    manifest_ref=SourceDocumentRef(
                        doc_role="manifest", content_hash=_HASH_A
                    ),
                    unit=PreprocessingUnitRef(
                        unit_id="Q1", unit_type="standalone_question"
                    ),
                    answer_declaration=StrictAnswerDeclaration(
                        attribution="not_attributable",
                        evidence_kind="explanation_prose",
                        completeness="incomplete",
                    ),
                ),
            )

    def test_table_row_without_locator_rejected(self):
        """DSH counterexample: table_row attribution with no row locator."""
        from question_core.contracts.v1 import StrictAnswerDeclaration

        with pytest.raises(ValidationError, match="table_row_locator"):
            StrictAnswerDeclaration(
                attribution="table_row",
                evidence_kind="answer_table",
                completeness="complete",
            )

    def test_table_row_without_value_rejected(self):
        from question_core.contracts.v1 import StrictAnswerDeclaration

        with pytest.raises(ValidationError, match="declared_value"):
            StrictAnswerDeclaration(
                attribution="table_row",
                evidence_kind="answer_table",
                table_row_locator="table:row=1,col=1",
                completeness="complete",
            )

    def test_absent_answer_forces_incomplete_candidate(self):
        from question_core.contracts.v1 import (
            AnswerCompleteness,
            Completeness,
            FillBlankAnswer,
            PreprocessingCandidate,
            PreprocessingSource,
            PreprocessingUnitRef,
            SourceDocumentRef,
            StrictAnswerDeclaration,
            CandidateCore,
            IngestionIdentity,
            InputHashes,
        )

        with pytest.raises(ValidationError, match="completeness to be 'full'"):
            PreprocessingCandidate(
                core=CandidateCore(
                    question_type="fill_blank",
                    content=_content(),
                    answers=(
                        FillBlankAnswer(
                            answer_value=["?"],
                            evidence_kind="absent",
                            completeness=AnswerCompleteness.ABSENT,
                        ),
                    ),
                    completeness=Completeness.COMPLETE,
                    ingestion=IngestionIdentity(
                        candidate_idempotency_key="k" * 20,
                        adapter_version="a/1",
                        input_hashes=InputHashes(manifest_hash=_HASH_A),
                    ),
                ),
                source=PreprocessingSource(
                    source_document_id="doc/1",
                    manifest_ref=SourceDocumentRef(
                        doc_role="manifest", content_hash=_HASH_A
                    ),
                    unit=PreprocessingUnitRef(
                        unit_id="Q1", unit_type="standalone_question"
                    ),
                    answer_declaration=StrictAnswerDeclaration(
                        attribution="declared",
                        evidence_kind="answer_lines",
                        declared_value="?",
                        completeness="complete",
                    ),
                ),
            )


# ---------------------------------------------------------------------------
# F3 — Student Upload permission fields must not contradict
# ---------------------------------------------------------------------------


class TestF3StudentUploadPermissions:
    def test_student_upload_cannot_claim_public_bank(self):
        """DSH counterexample: core.owner_scope=public_bank while
        source.owner_scope=student."""
        from question_core.contracts.v1 import (
            OwnerScope,
            StudentUploadSource,
        )

        with pytest.raises(ValidationError, match="public_bank"):
            StudentUploadSource(
                source_document_id="doc/1",
                uploaded_by="student:X",
                upload_blob_hash=_HASH_A,
                owner_scope=OwnerScope.PUBLIC_BANK,
            )

    def test_core_no_longer_carries_permission_fields(self):
        """F3 fix: the contradiction class is structurally impossible —
        CandidateCore simply has no owner_scope/pii_status/distribution_policy
        to contradict the source's."""
        from question_core.contracts.v1 import CandidateCore, IngestionIdentity, InputHashes

        core = CandidateCore(
            question_type="short_answer",
            content=_content(),
            ingestion=IngestionIdentity(
                candidate_idempotency_key="k" * 20,
                adapter_version="a/1",
                input_hashes=InputHashes(manifest_hash=_HASH_A),
            ),
        )
        assert not hasattr(core, "owner_scope")
        assert not hasattr(core, "pii_status")
        assert not hasattr(core, "distribution_policy")

    def test_student_upload_defaults_are_conservative(self):
        from question_core.contracts.v1 import (
            DistributionPolicy,
            OwnerScope,
            PiiStatus,
            StudentUploadSource,
        )

        src = StudentUploadSource(
            source_document_id="doc/1",
            uploaded_by="student:X",
            upload_blob_hash=_HASH_A,
        )
        assert src.owner_scope == OwnerScope.STUDENT
        assert src.pii_status == PiiStatus.SUSPECTED
        assert src.distribution_policy == DistributionPolicy.NO_REDISTRIBUTION

    def test_golden_student_upload_has_no_contradiction(self):
        import json
        from pathlib import Path

        golden = (
            Path(__file__).resolve().parents[1]
            / "question_core"
            / "golden"
            / "v1"
            / "student_upload_candidate.json"
        )
        doc = json.loads(golden.read_text(encoding="utf-8"))
        # The old contradiction (core=public_bank vs source=student) must not
        # exist in the golden snapshot.
        assert "owner_scope" not in doc.get("core", {}), (
            "CandidateCore must not carry owner_scope (F3)"
        )
        assert doc["source"]["owner_scope"] == "student"
        assert doc["source"]["pii_status"] == "suspected"
        assert doc["source"]["distribution_policy"] == "no_redistribution"


# ---------------------------------------------------------------------------
# F4 — Revision / Identity / records are immutable after construction
# ---------------------------------------------------------------------------


class TestF4Immutability:
    def test_revision_content_cannot_be_modified(self):
        from question_core.contracts.v1 import Revision

        rev = Revision.create(
            revision_id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            revision_number=1,
            question_type="short_answer",
            content=_content(),
        )
        with pytest.raises(Exception):  # ValidationError (frozen)
            rev.content = _content(_body("篡改后的题干"))

    def test_revision_content_hash_cannot_be_modified(self):
        from question_core.contracts.v1 import Revision

        rev = Revision.create(
            revision_id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            revision_number=1,
            question_type="short_answer",
            content=_content(),
        )
        with pytest.raises(Exception):
            rev.content_hash = _HASH_B

    def test_nested_body_cannot_be_modified(self):
        from question_core.contracts.v1 import Revision

        rev = Revision.create(
            revision_id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            revision_number=1,
            question_type="short_answer",
            content=_content(),
        )
        body = rev.content.bodies[0]
        with pytest.raises(Exception):
            body.stem_blocks = ()

    def test_question_identity_cannot_be_modified(self):
        from question_core.contracts.v1 import QuestionIdentity

        ident = QuestionIdentity(identity_fingerprint="fp-immutable")
        with pytest.raises(Exception):
            ident.question_id = uuid.uuid4()

    def test_approval_record_cannot_be_modified(self):
        from question_core.contracts.v1 import ApprovalRecord

        rec = ApprovalRecord(
            revision_id=uuid.uuid4(),
            content_hash=_HASH_A,
            approved_by="r",
        )
        with pytest.raises(Exception):
            rec.approved_by = "attacker"

    def test_publication_record_cannot_be_modified(self):
        from question_core.contracts.v1 import (
            PublicationRecord,
            PublicationState,
        )

        rec = PublicationRecord(
            revision_id=uuid.uuid4(),
            content_hash=_HASH_A,
            state=PublicationState.PUBLISHED,
            acted_by="p",
        )
        with pytest.raises(Exception):
            rec.acted_by = "attacker"

    def test_content_hash_mismatch_rejected(self):
        """A revision whose content_hash does not match its content must not
        exist — this is what makes the approval binding verifiable."""
        from question_core.contracts.v1 import Revision

        with pytest.raises(ValidationError, match="content_hash must equal"):
            Revision(
                revision_id=uuid.uuid4(),
                question_id=uuid.uuid4(),
                revision_number=1,
                content_hash=_HASH_A,  # wrong hash
                question_type="short_answer",
                content=_content(),
            )

    def test_answers_cannot_be_appended(self):
        from question_core.contracts.v1 import Revision

        rev = Revision.create(
            revision_id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            revision_number=1,
            question_type="short_answer",
            content=_content(),
        )
        assert isinstance(rev.answers, tuple)
        with pytest.raises(Exception):
            rev.answers.append  # tuples have no append


# ---------------------------------------------------------------------------
# N1 / N5 / N7 / N8 / N9
# ---------------------------------------------------------------------------


class TestN1CandidateIdIsUuid:
    def test_rejects_non_uuid(self):
        from question_core.contracts.v1 import (
            CandidateCore,
            IngestionIdentity,
            InputHashes,
        )

        with pytest.raises(ValidationError):
            CandidateCore.model_validate(
                {
                    "candidate_id": "not-a-uuid",
                    "question_type": "short_answer",
                    "content": _content().model_dump(mode="json"),
                    "ingestion": {
                        "candidate_idempotency_key": "k" * 20,
                        "adapter_version": "a/1",
                        "input_hashes": {"manifest_hash": _HASH_A},
                    },
                }
            )


class TestN5IngestionIdentityRejectsEmptyHashes:
    def test_empty_hashes_rejected(self):
        from question_core.contracts.v1 import (
            IngestionIdentity,
            InputHashes,
        )

        with pytest.raises(ValidationError, match="at least one input hash"):
            IngestionIdentity(
                candidate_idempotency_key="k" * 20,
                adapter_version="a/1",
                input_hashes=InputHashes(),
            )


class TestN7ConflictTargetMustMatch:
    def test_conflict_target_mismatch_rejected(self):
        from question_core.contracts.v1 import (
            EvidenceBundle,
            EvidenceConflict,
        )

        e1 = _evidence(target="/answers/0", value="B")
        e2 = _evidence(target="/stem", value="C", source="s2")
        conflict = EvidenceConflict(
            target_path="/answers/0",  # e2 targets /stem — mismatch
            evidence_ids=[e1.evidence_id, e2.evidence_id],
        )
        with pytest.raises(ValidationError, match="same field"):
            EvidenceBundle(records=[e1, e2], conflicts=[conflict])


class TestN8ModelInventory:
    def test_candidate_core_in_all_models(self):
        from question_core.contracts.v1.manifest import ALL_MODELS

        names = {m.__name__ for m in ALL_MODELS}
        assert "CandidateCore" in names, "N8: CandidateCore missing from ALL_MODELS"


class TestN9GoldenAggregateDigest:
    def test_aggregate_digest_is_stable(self):
        from .golden_samples import (
            GOLDEN_DIR,
            build_question_aggregate,
            canonical_digest,
        )

        recorded = __import__("json").loads(
            (GOLDEN_DIR / "golden_digests.json").read_text(encoding="utf-8")
        )
        digest = canonical_digest(build_question_aggregate().model_dump(mode="json"))
        assert digest == recorded["question_aggregate.json"], (
            "N9: question_aggregate golden digest must be reproducible"
        )


# ===========================================================================
# QCORE-01-R4: F2 complete 五条件反例
# ===========================================================================


class TestF2CompleteConditions:
    """R4: a PreprocessingCandidate claiming ``complete`` must prove its
    answers are present, attributed and complete.  Each test builds the
    illegal shape and asserts rejection."""

    @staticmethod
    def _mk_source(dec=None):
        from question_core.contracts.v1 import (
            PreprocessingSource,
            PreprocessingUnitRef,
            SourceDocumentRef,
        )

        return PreprocessingSource(
            source_document_id="doc/1",
            manifest_ref=SourceDocumentRef(
                doc_role="manifest", content_hash=_HASH_A
            ),
            unit=PreprocessingUnitRef(
                unit_id="Q1", unit_type="standalone_question"
            ),
            answer_declaration=dec,
        )

    @staticmethod
    def _mk_core(answers=(), completeness="complete"):
        from question_core.contracts.v1 import (
            CandidateCore,
            Completeness,
            IngestionIdentity,
            InputHashes,
        )

        return CandidateCore(
            question_type="single_choice",
            content=_content(),
            answers=tuple(answers),
            completeness=completeness,
            ingestion=IngestionIdentity(
                candidate_idempotency_key="k" * 20,
                adapter_version="a/1",
                input_hashes=InputHashes(manifest_hash=_HASH_A),
            ),
        )

    def test_declaration_none_plus_complete_rejected(self):
        """R4-F2-1: answer_declaration=None + complete → reject."""
        from question_core.contracts.v1 import PreprocessingCandidate

        with pytest.raises(ValidationError, match="answer_declaration to be present"):
            PreprocessingCandidate(
                core=self._mk_core(),
                source=self._mk_source(dec=None),
            )

    def test_declared_but_no_typed_answer_rejected(self):
        """R4-F2-2: declaration=declared + complete + 无 TypedAnswer → reject."""
        from question_core.contracts.v1 import (
            PreprocessingCandidate,
            StrictAnswerDeclaration,
        )

        dec = StrictAnswerDeclaration(
            attribution="declared",
            evidence_kind="answer_lines",
            declared_value="B",
            completeness="complete",
        )
        with pytest.raises(ValidationError, match="at least one TypedAnswer"):
            PreprocessingCandidate(
                core=self._mk_core(answers=()),
                source=self._mk_source(dec=dec),
            )

    def test_partial_answer_plus_complete_rejected(self):
        """R4-F2-3: answer completeness=partial + core complete → reject."""
        from question_core.contracts.v1 import (
            FillBlankAnswer,
            PreprocessingCandidate,
            StrictAnswerDeclaration,
        )

        dec = StrictAnswerDeclaration(
            attribution="declared",
            evidence_kind="answer_lines",
            declared_value="x",
            completeness="complete",
        )
        ans = FillBlankAnswer(
            answer_value=["x"],
            evidence_kind="answer_lines",
            completeness="partial",
        )
        with pytest.raises(ValidationError, match="completeness to be 'full'"):
            PreprocessingCandidate(
                core=self._mk_core(answers=(ans,)),
                source=self._mk_source(dec=dec),
            )

    def test_empty_answers_plus_complete_rejected(self):
        """R4-F2-4: answers 为空 + core complete → reject."""
        from question_core.contracts.v1 import (
            PreprocessingCandidate,
            StrictAnswerDeclaration,
        )

        dec = StrictAnswerDeclaration(
            attribution="declared",
            evidence_kind="answer_lines",
            declared_value="B",
            completeness="complete",
        )
        with pytest.raises(ValidationError, match="at least one TypedAnswer"):
            PreprocessingCandidate(
                core=self._mk_core(answers=()),
                source=self._mk_source(dec=dec),
            )

    def test_incomplete_candidate_still_constructible(self):
        """R4-F2-5: incomplete Candidate 仍能正常构造（不受五条件约束）。"""
        from question_core.contracts.v1 import PreprocessingCandidate

        cand = PreprocessingCandidate(
            core=self._mk_core(answers=(), completeness="incomplete"),
            source=self._mk_source(dec=None),
        )
        assert cand.core.completeness.value == "incomplete"

    def test_incomplete_with_declared_answer_still_constructible(self):
        """即使 declaration 存在但答案不全，incomplete 仍可构造。"""
        from question_core.contracts.v1 import (
            FillBlankAnswer,
            PreprocessingCandidate,
            StrictAnswerDeclaration,
        )

        dec = StrictAnswerDeclaration(
            attribution="declared",
            evidence_kind="answer_lines",
            declared_value="x",
            completeness="complete",
        )
        ans = FillBlankAnswer(
            answer_value=["x"],
            evidence_kind="answer_lines",
            completeness="partial",
        )
        cand = PreprocessingCandidate(
            core=self._mk_core(answers=(ans,), completeness="incomplete"),
            source=self._mk_source(dec=dec),
        )
        assert cand.core.completeness.value == "incomplete"


# ===========================================================================
# QCORE-01-R4: F4 model_copy(update=...) 绕过反例
# ===========================================================================


class TestF4ModelCopyBypass:
    """R4: ``model_copy(update=…)`` must not produce unvalidated contract
    objects.  Each test tries the bypass and asserts it is rejected."""

    def test_revision_content_cannot_be_replaced_via_model_copy(self):
        from question_core.contracts.v1 import Revision, UnsafeModelCopyError

        rev = Revision.create(
            revision_id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            revision_number=1,
            question_type="short_answer",
            content=_content(),
        )
        with pytest.raises(UnsafeModelCopyError, match="forbidden"):
            rev.model_copy(update={"content": _content(_body("篡改"))})

    def test_revision_evidence_cannot_be_replaced_via_model_copy(self):
        from question_core.contracts.v1 import (
            EvidenceBundle,
            Revision,
            UnsafeModelCopyError,
        )

        rev = Revision.create(
            revision_id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            revision_number=1,
            question_type="short_answer",
            content=_content(),
        )
        with pytest.raises(UnsafeModelCopyError, match="forbidden"):
            rev.model_copy(update={"evidence": EvidenceBundle()})

    def test_revision_state_cannot_bypass_approval_gate(self):
        """The DSH counterexample: model_copy(update={"state": approved_state})
        on a revision with unresolved critical conflicts would bypass F1."""
        from question_core.contracts.v1 import (
            Completeness,
            EvidenceBundle,
            EvidenceConflict,
            ReviewState,
            Revision,
            StateSnapshot,
            UnsafeModelCopyError,
            canonical_content_hash,
        )

        e1 = _evidence(value="B", source="manifest")
        e2 = _evidence(value="C", source="answer_table")
        conflict = EvidenceConflict(
            target_path="/answers/0",
            evidence_ids=[e1.evidence_id, e2.evidence_id],
            is_critical=True,
        )
        bundle = EvidenceBundle(records=[e1, e2], conflicts=[conflict])
        content = _content()
        ch = canonical_content_hash(content)
        rid = uuid.uuid4()

        rev = Revision.create(
            revision_id=rid,
            question_id=uuid.uuid4(),
            revision_number=1,
            question_type="short_answer",
            content=content,
        )
        # An "approved" state — but attaching it via model_copy would bypass
        # both the F1 conflict check and the state binding check.
        from question_core.contracts.v1 import ApprovalRecord

        approval = ApprovalRecord(revision_id=rid, content_hash=ch, approved_by="r")
        bad_state = StateSnapshot(
            revision_id=rid,
            content_hash=ch,
            completeness=Completeness.COMPLETE,
            review=ReviewState.APPROVED,
            approval=approval,
        )
        with pytest.raises(UnsafeModelCopyError, match="forbidden"):
            rev.model_copy(update={"state": bad_state})

    def test_question_identity_id_cannot_be_rewritten(self):
        from question_core.contracts.v1 import QuestionIdentity, UnsafeModelCopyError

        ident = QuestionIdentity(identity_fingerprint="fp-r4-test")
        with pytest.raises(UnsafeModelCopyError, match="forbidden"):
            ident.model_copy(update={"question_id": uuid.uuid4()})

    def test_plain_model_copy_still_works(self):
        """No-update copy must remain available and faithful."""
        from question_core.contracts.v1 import Revision

        rev = Revision.create(
            revision_id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            revision_number=1,
            question_type="short_answer",
            content=_content(),
        )
        clone = rev.model_copy()
        assert clone.revision_id == rev.revision_id
        assert clone.content_hash == rev.content_hash

    def test_empty_update_dict_also_rejected_or_passes(self):
        """model_copy(update={}) should behave as a plain copy (update is
        falsy).  Non-empty is rejected."""
        from question_core.contracts.v1 import Revision

        rev = Revision.create(
            revision_id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            revision_number=1,
            question_type="short_answer",
            content=_content(),
        )
        clone = rev.model_copy(update={})
        assert clone.revision_id == rev.revision_id


# ===========================================================================
# QCORE-01-R5: 多类型答案声明一致性
# ===========================================================================


class TestF2MultiTypeDeclaredValueMatching:
    """R5: the declared value must **fully** match the TypedAnswer structure
    for every answer type.  Partial matches must be rejected."""

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _mk_candidate(declared_value, answers, answer_type="single_choice"):
        from question_core.contracts.v1 import (
            CandidateCore,
            IngestionIdentity,
            InputHashes,
            PreprocessingCandidate,
            PreprocessingSource,
            PreprocessingUnitRef,
            SourceDocumentRef,
            StrictAnswerDeclaration,
        )

        dec = StrictAnswerDeclaration(
            attribution="declared",
            evidence_kind="answer_lines",
            declared_value=declared_value,
            completeness="complete",
        )
        return PreprocessingCandidate(
            core=CandidateCore(
                question_type=answer_type,
                content=_content(),
                answers=tuple(answers),
                completeness="complete",
                ingestion=IngestionIdentity(
                    candidate_idempotency_key="k" * 20,
                    adapter_version="a/1",
                    input_hashes=InputHashes(manifest_hash=_HASH_A),
                ),
            ),
            source=PreprocessingSource(
                source_document_id="doc/1",
                manifest_ref=SourceDocumentRef(
                    doc_role="manifest", content_hash=_HASH_A
                ),
                unit=PreprocessingUnitRef(
                    unit_id="Q1", unit_type="standalone_question"
                ),
                answer_declaration=dec,
            ),
        )

    # -- 1. 多选完整匹配 ---------------------------------------------------

    def test_multi_choice_full_match(self):
        from question_core.contracts.v1 import MultiChoiceAnswer

        ans = MultiChoiceAnswer(
            answer_value=["B", "C"],
            evidence_kind="answer_lines",
            completeness="full",
        )
        cand = self._mk_candidate("BC", [ans], "multi_choice")
        assert cand.core.completeness.value == "complete"

    def test_multi_choice_full_match_delimited(self):
        from question_core.contracts.v1 import MultiChoiceAnswer

        ans = MultiChoiceAnswer(
            answer_value=["A", "C"],
            evidence_kind="answer_lines",
            completeness="full",
        )
        cand = self._mk_candidate("A、C", [ans], "multi_choice")
        assert cand.core.completeness.value == "complete"

    def test_multi_choice_full_match_three(self):
        from question_core.contracts.v1 import MultiChoiceAnswer

        ans = MultiChoiceAnswer(
            answer_value=["A", "B", "C"],
            evidence_kind="answer_lines",
            completeness="full",
        )
        cand = self._mk_candidate("ABC", [ans], "multi_choice")
        assert cand.core.completeness.value == "complete"

    # -- 2. 多选部分匹配拒绝 -----------------------------------------------

    def test_multi_choice_partial_match_rejected(self):
        from question_core.contracts.v1 import MultiChoiceAnswer

        ans = MultiChoiceAnswer(
            answer_value=["A", "C"],
            evidence_kind="answer_lines",
            completeness="full",
        )
        with pytest.raises(ValidationError, match="fully.*represented"):
            self._mk_candidate("A", [ans], "multi_choice")

    def test_multi_choice_wrong_label_rejected(self):
        from question_core.contracts.v1 import MultiChoiceAnswer

        ans = MultiChoiceAnswer(
            answer_value=["A", "C"],
            evidence_kind="answer_lines",
            completeness="full",
        )
        with pytest.raises(ValidationError, match="fully.*represented"):
            self._mk_candidate("B", [ans], "multi_choice")

    def test_multi_choice_extra_label_rejected(self):
        from question_core.contracts.v1 import MultiChoiceAnswer

        ans = MultiChoiceAnswer(
            answer_value=["A", "C"],
            evidence_kind="answer_lines",
            completeness="full",
        )
        with pytest.raises(ValidationError, match="fully.*represented"):
            self._mk_candidate("ABCD", [ans], "multi_choice")

    # -- 3. 多空完整匹配 ---------------------------------------------------

    def test_fill_blank_full_match(self):
        from question_core.contracts.v1 import FillBlankAnswer

        ans = FillBlankAnswer(
            answer_value=["B", "D", "A", "C"],
            evidence_kind="answer_lines",
            completeness="full",
        )
        cand = self._mk_candidate(
            "(1).B (2).D (3).A (4).C", [ans], "fill_blank"
        )
        assert cand.core.completeness.value == "complete"

    def test_fill_blank_full_match_delimited(self):
        from question_core.contracts.v1 import FillBlankAnswer

        ans = FillBlankAnswer(
            answer_value=["B", "D", "A", "C"],
            evidence_kind="answer_lines",
            completeness="full",
        )
        cand = self._mk_candidate("B,D,A,C", [ans], "fill_blank")
        assert cand.core.completeness.value == "complete"

    # -- 4. 多空缺项拒绝 ---------------------------------------------------

    def test_fill_blank_missing_item_rejected(self):
        from question_core.contracts.v1 import FillBlankAnswer

        ans = FillBlankAnswer(
            answer_value=["B", "D", "A", "C"],
            evidence_kind="answer_lines",
            completeness="full",
        )
        with pytest.raises(ValidationError, match="fully.*represented"):
            self._mk_candidate("(1).B (2).D (3).A", [ans], "fill_blank")

    def test_fill_blank_wrong_order_rejected(self):
        from question_core.contracts.v1 import FillBlankAnswer

        ans = FillBlankAnswer(
            answer_value=["B", "D", "A", "C"],
            evidence_kind="answer_lines",
            completeness="full",
        )
        with pytest.raises(ValidationError, match="fully.*represented"):
            self._mk_candidate("(1).C (2).D (3).A (4).B", [ans], "fill_blank")

    # -- 5. 复合题递归完整匹配 ---------------------------------------------

    def test_composite_full_match(self):
        from question_core.contracts.v1 import (
            CompositeAnswer,
            CompositeSubAnswer,
            SingleChoiceAnswer,
        )

        comp = CompositeAnswer(
            answer_value=[
                CompositeSubAnswer(
                    sub_label="9",
                    answer_value=SingleChoiceAnswer(
                        answer_value="D",
                        evidence_kind="answer_lines",
                        completeness="full",
                    ),
                    completeness="full",
                ),
                CompositeSubAnswer(
                    sub_label="10",
                    answer_value=SingleChoiceAnswer(
                        answer_value="B",
                        evidence_kind="answer_lines",
                        completeness="full",
                    ),
                    completeness="full",
                ),
            ],
            evidence_kind="answer_lines",
            completeness="full",
        )
        cand = self._mk_candidate("9.D 10.B", [comp], "short_answer")
        assert cand.core.completeness.value == "complete"

    def test_composite_full_match_paren_labels(self):
        from question_core.contracts.v1 import (
            CompositeAnswer,
            CompositeSubAnswer,
            SingleChoiceAnswer,
        )

        comp = CompositeAnswer(
            answer_value=[
                CompositeSubAnswer(
                    sub_label="(1)",
                    answer_value=SingleChoiceAnswer(
                        answer_value="A",
                        evidence_kind="answer_lines",
                        completeness="full",
                    ),
                    completeness="full",
                ),
                CompositeSubAnswer(
                    sub_label="(2)",
                    answer_value=SingleChoiceAnswer(
                        answer_value="C",
                        evidence_kind="answer_lines",
                        completeness="full",
                    ),
                    completeness="full",
                ),
            ],
            evidence_kind="answer_lines",
            completeness="full",
        )
        cand = self._mk_candidate("(1).A (2).C", [comp], "short_answer")
        assert cand.core.completeness.value == "complete"

    # -- 6. 复合题缺少子答案拒绝 -------------------------------------------

    def test_composite_missing_sub_answer_rejected(self):
        from question_core.contracts.v1 import (
            CompositeAnswer,
            CompositeSubAnswer,
            SingleChoiceAnswer,
        )

        comp = CompositeAnswer(
            answer_value=[
                CompositeSubAnswer(
                    sub_label="9",
                    answer_value=SingleChoiceAnswer(
                        answer_value="D",
                        evidence_kind="answer_lines",
                        completeness="full",
                    ),
                    completeness="full",
                ),
                CompositeSubAnswer(
                    sub_label="10",
                    answer_value=SingleChoiceAnswer(
                        answer_value="B",
                        evidence_kind="answer_lines",
                        completeness="full",
                    ),
                    completeness="full",
                ),
            ],
            evidence_kind="answer_lines",
            completeness="full",
        )
        with pytest.raises(ValidationError, match="fully.*represented"):
            self._mk_candidate("9.D", [comp], "short_answer")

    # -- 7. 复合题子答案不完整拒绝 -----------------------------------------

    def test_composite_partial_sub_answer_rejected(self):
        from question_core.contracts.v1 import (
            CompositeAnswer,
            CompositeSubAnswer,
            SingleChoiceAnswer,
        )

        comp = CompositeAnswer(
            answer_value=[
                CompositeSubAnswer(
                    sub_label="9",
                    answer_value=SingleChoiceAnswer(
                        answer_value="D",
                        evidence_kind="answer_lines",
                        completeness="full",
                    ),
                    completeness="full",
                ),
                CompositeSubAnswer(
                    sub_label="10",
                    answer_value=SingleChoiceAnswer(
                        answer_value="B",
                        evidence_kind="answer_lines",
                        completeness="partial",
                    ),
                    completeness="partial",
                ),
            ],
            evidence_kind="answer_lines",
            completeness="full",
        )
        with pytest.raises(ValidationError, match="completeness to be 'full'"):
            self._mk_candidate("9.D 10.B", [comp], "short_answer")

    # -- 8. 多步骤完整对应 -------------------------------------------------

    def test_multi_step_full_match(self):
        from question_core.contracts.v1 import MultiStepAnswer

        ans = MultiStepAnswer(
            answer_value=["设物质的量为 n", "n = cV = 0.010 mol"],
            final_result="0.010 mol",
            evidence_kind="answer_lines",
            completeness="full",
        )
        declared = "解：设物质的量为 n，n = cV = 0.010 mol。答：0.010 mol"
        cand = self._mk_candidate(declared, [ans], "multi_step")
        assert cand.core.completeness.value == "complete"

    # -- 9. 多步骤部分对应拒绝 ---------------------------------------------

    def test_multi_step_partial_match_rejected(self):
        from question_core.contracts.v1 import MultiStepAnswer

        ans = MultiStepAnswer(
            answer_value=["设物质的量为 n", "n = cV = 0.010 mol"],
            final_result="0.010 mol",
            evidence_kind="answer_lines",
            completeness="full",
        )
        # Only the first step appears; the second step and final result are
        # missing from the declared value.
        declared = "解：设物质的量为 n"
        with pytest.raises(ValidationError, match="fully.*represented"):
            self._mk_candidate(declared, [ans], "multi_step")

    def test_multi_step_missing_final_result_rejected(self):
        from question_core.contracts.v1 import MultiStepAnswer

        ans = MultiStepAnswer(
            answer_value=["设物质的量为 n", "n = cV"],
            final_result="0.010 mol",
            evidence_kind="answer_lines",
            completeness="full",
        )
        declared = "设物质的量为 n，n = cV"
        with pytest.raises(ValidationError, match="fully.*represented"):
            self._mk_candidate(declared, [ans], "multi_step")

    # -- 10. 原有单选匹配 --------------------------------------------------

    def test_single_choice_correct_match(self):
        from question_core.contracts.v1 import SingleChoiceAnswer

        ans = SingleChoiceAnswer(
            answer_value="B",
            evidence_kind="answer_lines",
            completeness="full",
        )
        cand = self._mk_candidate("B", [ans], "single_choice")
        assert cand.core.completeness.value == "complete"

    def test_single_choice_wrong_match_rejected(self):
        from question_core.contracts.v1 import SingleChoiceAnswer

        ans = SingleChoiceAnswer(
            answer_value="B",
            evidence_kind="answer_lines",
            completeness="full",
        )
        with pytest.raises(ValidationError, match="fully.*represented"):
            self._mk_candidate("C", [ans], "single_choice")

    def test_single_choice_fullwidth_match(self):
        from question_core.contracts.v1 import SingleChoiceAnswer

        ans = SingleChoiceAnswer(
            answer_value="B",
            evidence_kind="answer_lines",
            completeness="full",
        )
        cand = self._mk_candidate("Ｂ", [ans], "single_choice")
        assert cand.core.completeness.value == "complete"

    # -- incomplete 不受影响 -----------------------------------------------

    def test_incomplete_never_blocked_by_declared_value(self):
        from question_core.contracts.v1 import (
            CandidateCore,
            IngestionIdentity,
            InputHashes,
            PreprocessingCandidate,
            PreprocessingSource,
            PreprocessingUnitRef,
            SourceDocumentRef,
            StrictAnswerDeclaration,
        )

        dec = StrictAnswerDeclaration(
            attribution="declared",
            evidence_kind="answer_lines",
            declared_value="ZZZ",  # does not match anything
            completeness="complete",
        )
        cand = PreprocessingCandidate(
            core=CandidateCore(
                question_type="single_choice",
                content=_content(),
                answers=(),
                completeness="incomplete",
                ingestion=IngestionIdentity(
                    candidate_idempotency_key="k" * 20,
                    adapter_version="a/1",
                    input_hashes=InputHashes(manifest_hash=_HASH_A),
                ),
            ),
            source=PreprocessingSource(
                source_document_id="doc/1",
                manifest_ref=SourceDocumentRef(
                    doc_role="manifest", content_hash=_HASH_A
                ),
                unit=PreprocessingUnitRef(
                    unit_id="Q1", unit_type="standalone_question"
                ),
                answer_declaration=dec,
            ),
        )
        assert cand.core.completeness.value == "incomplete"


class TestF2CompositeSubInnerCompleteness:
    """DSH R5 残余阻塞修复验证：wrapper=full + inner=partial 必须拒绝。"""

    @staticmethod
    def _mk_candidate(declared_value, answers):
        from question_core.contracts.v1 import (
            CandidateCore,
            IngestionIdentity,
            InputHashes,
            PreprocessingCandidate,
            PreprocessingSource,
            PreprocessingUnitRef,
            SourceDocumentRef,
            StrictAnswerDeclaration,
        )

        return PreprocessingCandidate(
            core=CandidateCore(
                question_type="short_answer",
                content=_content(),
                answers=tuple(answers),
                completeness="complete",
                ingestion=IngestionIdentity(
                    candidate_idempotency_key="k" * 20,
                    adapter_version="a/1",
                    input_hashes=InputHashes(manifest_hash=_HASH_A),
                ),
            ),
            source=PreprocessingSource(
                source_document_id="doc/1",
                manifest_ref=SourceDocumentRef(
                    doc_role="manifest", content_hash=_HASH_A
                ),
                unit=PreprocessingUnitRef(
                    unit_id="Q1", unit_type="standalone_question"
                ),
                answer_declaration=StrictAnswerDeclaration(
                    attribution="declared",
                    evidence_kind="answer_lines",
                    declared_value=declared_value,
                    completeness="complete",
                ),
            ),
        )

    def test_wrapper_full_inner_partial_rejected(self):
        """DSH 反例：CompositeSubAnswer(wrapper=full) 内层 SingleChoiceAnswer
        (completeness=partial) → 必须拒绝。"""
        from question_core.contracts.v1 import (
            CompositeAnswer,
            CompositeSubAnswer,
            SingleChoiceAnswer,
        )

        comp = CompositeAnswer(
            answer_value=[
                CompositeSubAnswer(
                    sub_label="9",
                    answer_value=SingleChoiceAnswer(
                        answer_value="D",
                        evidence_kind="answer_lines",
                        completeness="partial",
                    ),
                    completeness="full",
                ),
                CompositeSubAnswer(
                    sub_label="10",
                    answer_value=SingleChoiceAnswer(
                        answer_value="B",
                        evidence_kind="answer_lines",
                        completeness="full",
                    ),
                    completeness="full",
                ),
            ],
            evidence_kind="answer_lines",
            completeness="full",
        )
        with pytest.raises(ValidationError, match="completeness to be 'full'"):
            self._mk_candidate("9.D 10.B", [comp])

    def test_grandchild_partial_rejected(self):
        """wrapper=full → inner CompositeAnswer=full → 孙子答案 partial → 拒绝。"""
        from question_core.contracts.v1 import (
            CompositeAnswer,
            CompositeSubAnswer,
            SingleChoiceAnswer,
        )

        grand_inner = CompositeAnswer(
            answer_value=[
                CompositeSubAnswer(
                    sub_label="a",
                    answer_value=SingleChoiceAnswer(
                        answer_value="X",
                        completeness="partial",
                    ),
                    completeness="full",
                ),
            ],
            completeness="full",
        )
        comp = CompositeAnswer(
            answer_value=[
                CompositeSubAnswer(
                    sub_label="9",
                    answer_value=grand_inner,
                    completeness="full",
                ),
                CompositeSubAnswer(
                    sub_label="10",
                    answer_value=SingleChoiceAnswer(
                        answer_value="B", completeness="full"
                    ),
                    completeness="full",
                ),
            ],
            completeness="full",
        )
        with pytest.raises(ValidationError, match="completeness to be 'full'"):
            self._mk_candidate("9.X 10.B", [comp])

    def test_full_chain_accepted(self):
        """全链路 full → 通过。"""
        from question_core.contracts.v1 import (
            CompositeAnswer,
            CompositeSubAnswer,
            SingleChoiceAnswer,
        )

        comp = CompositeAnswer(
            answer_value=[
                CompositeSubAnswer(
                    sub_label="9",
                    answer_value=SingleChoiceAnswer(
                        answer_value="D",
                        evidence_kind="answer_lines",
                        completeness="full",
                    ),
                    completeness="full",
                ),
                CompositeSubAnswer(
                    sub_label="10",
                    answer_value=SingleChoiceAnswer(
                        answer_value="B",
                        evidence_kind="answer_lines",
                        completeness="full",
                    ),
                    completeness="full",
                ),
            ],
            evidence_kind="answer_lines",
            completeness="full",
        )
        cand = self._mk_candidate("9.D 10.B", [comp])
        assert cand.core.completeness.value == "complete"

    def test_incomplete_never_blocked(self):
        """incomplete Candidate 不受递归检查影响。"""
        from question_core.contracts.v1 import (
            CandidateCore,
            CompositeAnswer,
            CompositeSubAnswer,
            IngestionIdentity,
            InputHashes,
            PreprocessingCandidate,
            PreprocessingSource,
            PreprocessingUnitRef,
            SingleChoiceAnswer,
            SourceDocumentRef,
            StrictAnswerDeclaration,
        )

        comp = CompositeAnswer(
            answer_value=[
                CompositeSubAnswer(
                    sub_label="9",
                    answer_value=SingleChoiceAnswer(
                        answer_value="D", completeness="partial"
                    ),
                    completeness="full",
                ),
            ],
            completeness="full",
        )
        cand = PreprocessingCandidate(
            core=CandidateCore(
                question_type="short_answer",
                content=_content(),
                answers=(comp,),
                completeness="incomplete",
                ingestion=IngestionIdentity(
                    candidate_idempotency_key="k" * 20,
                    adapter_version="a/1",
                    input_hashes=InputHashes(manifest_hash=_HASH_A),
                ),
            ),
            source=PreprocessingSource(
                source_document_id="doc/1",
                manifest_ref=SourceDocumentRef(
                    doc_role="manifest", content_hash=_HASH_A
                ),
                unit=PreprocessingUnitRef(
                    unit_id="Q1", unit_type="standalone_question"
                ),
                answer_declaration=StrictAnswerDeclaration(
                    attribution="declared",
                    evidence_kind="answer_lines",
                    declared_value="9.D",
                    completeness="complete",
                ),
            ),
        )
        assert cand.core.completeness.value == "incomplete"
