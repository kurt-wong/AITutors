"""Repository: transactional create/read of Question Core contract objects.

All writes go through the caller's :class:`~sqlalchemy.orm.Session` (see
:func:`question_core.persistence.engine.session_scope` for the commit /
rollback boundary).  One aggregate write is always one transaction: either
the whole Candidate / Question / Revision / Instance graph lands, or the
transaction rolls back and nothing is left behind.

Stored payloads are the authoritative restore source; every read rebuilds
the contract object and re-runs its validators.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..contracts.v1 import (
    Candidate,
    QuestionAggregate,
    QuestionIdentity,
    QuestionInstance,
    Revision,
    StateSnapshot,
)
from .exceptions import (
    ContractViolationError,
    DuplicateCandidateError,
    DuplicateInstanceError,
    DuplicateQuestionError,
    DuplicateRevisionError,
    NotFoundError,
    PersistenceError,
)
from .models import (
    AnswerRow,
    AssetRefRow,
    CandidateRow,
    EvidenceConflictRow,
    EvidenceRecordRow,
    InstanceRow,
    MaterialRefRow,
    QuestionRow,
    RevisionRow,
    StateHistoryRow,
)
from .serialize import (
    dump_contract,
    restore_aggregate,
    restore_candidate,
    restore_identity,
    restore_instance,
    restore_revision,
    restore_state_snapshot,
)


def _val(x: Any) -> Any:
    """Enum → value; everything else unchanged."""
    return x.value if hasattr(x, "value") else x


def _integrity_error(exc: IntegrityError) -> Exception:
    """Translate a SQLAlchemy IntegrityError into a domain error."""
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint = getattr(diag, "constraint_name", "") or ""
    message = str(exc)

    if "qcore_revisions_immutable" in message or "immutable" in message:
        return DuplicateRevisionError(
            f"revision rows are immutable and cannot be overwritten: {message}"
        )
    if "uq_candidate_key_version" in constraint or "idempotency_key" in constraint:
        return DuplicateCandidateError(
            f"candidate conflicts with an existing row for the same "
            f"(idempotency_key, adapter_version) ({constraint or 'unique/pk'}): {message}"
        )
    if "qcore_candidates_pkey" in constraint:
        return DuplicateCandidateError(
            f"candidate_id already exists: {message}"
        )
    if "uq_revision_question_number" in constraint:
        return DuplicateRevisionError(
            f"revision_number already used in this question: {message}"
        )
    if "qcore_revisions_pkey" in constraint:
        return DuplicateRevisionError(
            f"revision_id already exists: {message}"
        )
    if "uq_instance_slot" in constraint:
        return DuplicateInstanceError(
            f"question occurrence slot already taken "
            f"(question_id, source_document_id, ordinal): {message}"
        )
    if "qcore_question_instances_pkey" in constraint:
        return DuplicateInstanceError(
            f"instance_id already exists: {message}"
        )
    if "qcore_questions_pkey" in constraint:
        return DuplicateQuestionError(
            f"question_id already exists: {message}"
        )
    if "fk_instance_revision_pair" in constraint:
        return PersistenceError(
            "instance references a revision that does not belong to its "
            f"question (composite FK fk_instance_revision_pair): {message}"
        )
    if "uq_revision_question_ref" in constraint:
        return DuplicateRevisionError(
            f"revision already registered for this question "
            f"(uq_revision_question_ref): {message}"
        )
    if "fkey" in constraint and "qcore_revisions" in constraint:
        return NotFoundError(
            f"referenced question does not exist: {message}"
        )
    if "_fkey" in constraint:
        return PersistenceError(
            f"referential integrity violation ({constraint}): {message}"
        )
    return exc


class QuestionCoreRepository:
    """CRUD for candidates, questions, revisions and instances."""

    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------
    # internal row builders
    # ------------------------------------------------------------------

    def _insert_answer_rows(
        self,
        *,
        answers: tuple,
        candidate_id: UUID | None = None,
        revision_id: UUID | None = None,
    ) -> None:
        for position, ans in enumerate(answers):
            self.session.add(
                AnswerRow(
                    candidate_id=candidate_id,
                    revision_id=revision_id,
                    position=position,
                    answer_type=_val(ans.answer_type),
                    completeness=_val(getattr(ans, "completeness", None)),
                    payload=dump_contract(ans),
                )
            )

    def _insert_evidence_rows(
        self,
        *,
        evidence,
        candidate_id: UUID | None = None,
        revision_id: UUID | None = None,
    ) -> None:
        for rec in evidence.records:
            self.session.add(
                EvidenceRecordRow(
                    candidate_id=candidate_id,
                    revision_id=revision_id,
                    evidence_id=rec.evidence_id,
                    target_path=rec.target_path,
                    evidence_role=_val(rec.evidence_role),
                    evidence_status=_val(rec.evidence_status),
                    payload=dump_contract(rec),
                )
            )
        for conflict in evidence.conflicts:
            self.session.add(
                EvidenceConflictRow(
                    candidate_id=candidate_id,
                    revision_id=revision_id,
                    conflict_id=conflict.conflict_id,
                    target_path=conflict.target_path,
                    is_critical=conflict.is_critical,
                    resolution=_val(conflict.resolution),
                    payload=dump_contract(conflict),
                )
            )

    def _insert_asset_material_rows(
        self,
        *,
        content,
        candidate_id: UUID | None = None,
        revision_id: UUID | None = None,
    ) -> None:
        for asset in content.assets:
            self.session.add(
                AssetRefRow(
                    candidate_id=candidate_id,
                    revision_id=revision_id,
                    asset_id=asset.asset_id,
                    storage_path=asset.storage_path,
                    content_hash=asset.content_hash,
                    mime_type=asset.mime_type,
                    payload=dump_contract(asset),
                )
            )
        for material in content.materials:
            self.session.add(
                MaterialRefRow(
                    candidate_id=candidate_id,
                    revision_id=revision_id,
                    material_id=material.material_id,
                    payload=dump_contract(material),
                )
            )

    def _insert_candidate(self, candidate: Candidate) -> None:
        core = candidate.core
        self.session.add(
            CandidateRow(
                candidate_id=core.candidate_id,
                source_type=_val(candidate.source_type),
                idempotency_key=core.ingestion.candidate_idempotency_key,
                question_type=_val(core.question_type),
                completeness=_val(core.completeness),
                ingestion_run_id=core.ingestion.ingestion_run_id,
                adapter_version=core.ingestion.adapter_version,
                payload=dump_contract(candidate),
                contract_created_at=core.created_at,
            )
        )
        # Parent row first: without relationship() the ORM does not order
        # INSERTs by FK dependency, and the child rows below carry FKs to
        # this row.  flush() only emits SQL - the transaction is unchanged.
        self.session.flush()
        self._insert_answer_rows(
            answers=core.answers, candidate_id=core.candidate_id
        )
        self._insert_evidence_rows(
            evidence=core.evidence, candidate_id=core.candidate_id
        )
        self._insert_asset_material_rows(
            content=core.content, candidate_id=core.candidate_id
        )

    def _insert_revision(self, revision: Revision) -> None:
        state = revision.state
        self.session.add(
            RevisionRow(
                revision_id=revision.revision_id,
                question_id=revision.question_id,
                revision_number=revision.revision_number,
                content_hash=revision.content_hash,
                question_type=_val(revision.question_type),
                answer_visibility=_val(revision.answer_visibility),
                explanation_visibility=_val(revision.explanation_visibility),
                completeness=_val(state.completeness) if state else "incomplete",
                review_state=_val(state.review) if state else "not_ready",
                publication_state=(
                    _val(state.publication) if state else "unpublished"
                ),
                state=dump_contract(state) if state else None,
                payload=dump_contract(revision),
                contract_created_at=revision.created_at,
                created_by=revision.created_by,
                change_note=revision.change_note,
            )
        )
        self.session.flush()
        self._insert_answer_rows(
            answers=revision.answers, revision_id=revision.revision_id
        )
        self._insert_evidence_rows(
            evidence=revision.evidence, revision_id=revision.revision_id
        )
        self._insert_asset_material_rows(
            content=revision.content, revision_id=revision.revision_id
        )

    def _insert_instance(self, instance: QuestionInstance) -> None:
        self.session.add(
            InstanceRow(
                instance_id=instance.instance_id,
                question_id=instance.question_id,
                revision_id=instance.revision_id,
                source_document_id=instance.source_document_id,
                printed_number=instance.printed_number,
                question_numbers=list(instance.question_numbers),
                section=instance.section,
                line_start=instance.line_start,
                line_end=instance.line_end,
                ordinal=instance.ordinal,
                note=instance.note,
                payload=dump_contract(instance),
                contract_created_at=instance.created_at,
            )
        )

    def _insert_question_identity(self, identity: QuestionIdentity) -> None:
        self.session.add(
            QuestionRow(
                question_id=identity.question_id,
                identity_fingerprint=identity.identity_fingerprint,
                embedding_ref=identity.embedding_ref,
                contract_created_at=identity.created_at,
            )
        )
        # Same rationale as _insert_candidate: rows referencing this
        # question (revisions, instances, state history) must see it.
        self.session.flush()

    def _insert_state_history(
        self, question_id: UUID, history: tuple[StateSnapshot, ...]
    ) -> None:
        for position, snapshot in enumerate(history):
            self.session.add(
                StateHistoryRow(
                    question_id=question_id,
                    position=position,
                    snapshot=dump_contract(snapshot),
                )
            )

    # ------------------------------------------------------------------
    # writes (each ends with flush() so constraints surface at the call)
    # ------------------------------------------------------------------

    def save_candidate(self, candidate: Candidate) -> None:
        """Persist one candidate (with its answers/evidence/assets) atomically."""
        try:
            self._insert_candidate(candidate)
            self.session.flush()
        except IntegrityError as exc:
            raise _integrity_error(exc) from exc

    def create_question(self, identity: QuestionIdentity) -> None:
        try:
            self._insert_question_identity(identity)
            self.session.flush()
        except IntegrityError as exc:
            raise _integrity_error(exc) from exc

    def save_question_aggregate(self, aggregate: QuestionAggregate) -> None:
        """Persist identity + all revisions + instances + state history."""
        try:
            self._insert_question_identity(aggregate.identity)
            for revision in aggregate.revisions:
                self._insert_revision(revision)
            for instance in aggregate.instances:
                self._insert_instance(instance)
            self._insert_state_history(
                aggregate.identity.question_id, aggregate.state_history
            )
            self.session.flush()
        except IntegrityError as exc:
            raise _integrity_error(exc) from exc

    def save_candidate_with_question(
        self, candidate: Candidate, aggregate: QuestionAggregate
    ) -> None:
        """Persist a candidate and its question aggregate in ONE transaction."""
        try:
            self._insert_candidate(candidate)
            self._insert_question_identity(aggregate.identity)
            for revision in aggregate.revisions:
                self._insert_revision(revision)
            for instance in aggregate.instances:
                self._insert_instance(instance)
            self._insert_state_history(
                aggregate.identity.question_id, aggregate.state_history
            )
            self.session.flush()
        except IntegrityError as exc:
            raise _integrity_error(exc) from exc

    def add_revision(self, revision: Revision) -> None:
        """Append one immutable revision to an existing question."""
        try:
            self._insert_revision(revision)
            self.session.flush()
        except IntegrityError as exc:
            raise _integrity_error(exc) from exc

    def add_instance(self, instance: QuestionInstance) -> None:
        try:
            self._insert_instance(instance)
            self.session.flush()
        except IntegrityError as exc:
            raise _integrity_error(exc) from exc

    # ------------------------------------------------------------------
    # reads (payload restore + full contract revalidation)
    # ------------------------------------------------------------------

    def get_candidate(self, candidate_id: UUID) -> Candidate:
        row = self.session.get(CandidateRow, candidate_id)
        if row is None:
            raise NotFoundError(f"candidate {candidate_id} not found")
        return restore_candidate(row.payload)

    def get_candidate_by_key(
        self, idempotency_key: str, adapter_version: str
    ) -> Candidate:
        """Look up a candidate by (idempotency key, adapter version).

        The version parameter is mandatory: results of different adapter
        versions coexist and must be distinguishable.
        """
        row = self.session.execute(
            select(CandidateRow).where(
                CandidateRow.idempotency_key == idempotency_key,
                CandidateRow.adapter_version == adapter_version,
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError(
                f"candidate with idempotency key {idempotency_key!r} and "
                f"adapter_version {adapter_version!r} not found"
            )
        return restore_candidate(row.payload)

    def get_question_identity(self, question_id: UUID) -> QuestionIdentity:
        row = self.session.get(QuestionRow, question_id)
        if row is None:
            raise NotFoundError(f"question {question_id} not found")
        return restore_identity(
            {
                "question_id": row.question_id,
                "identity_fingerprint": row.identity_fingerprint,
                "embedding_ref": row.embedding_ref,
                "created_at": row.contract_created_at,
            }
        )

    def get_revision(self, revision_id: UUID) -> Revision:
        row = self.session.get(RevisionRow, revision_id)
        if row is None:
            raise NotFoundError(f"revision {revision_id} not found")
        return restore_revision(row.payload)

    def list_revisions(self, question_id: UUID) -> tuple[Revision, ...]:
        rows = self.session.execute(
            select(RevisionRow)
            .where(RevisionRow.question_id == question_id)
            .order_by(RevisionRow.revision_number)
        ).scalars()
        return tuple(restore_revision(row.payload) for row in rows)

    def get_instance(self, instance_id: UUID) -> QuestionInstance:
        row = self.session.get(InstanceRow, instance_id)
        if row is None:
            raise NotFoundError(f"instance {instance_id} not found")
        return restore_instance(row.payload)

    def list_instances(self, question_id: UUID) -> tuple[QuestionInstance, ...]:
        rows = self.session.execute(
            select(InstanceRow)
            .where(InstanceRow.question_id == question_id)
            .order_by(InstanceRow.ordinal, InstanceRow.instance_id)
        ).scalars()
        return tuple(restore_instance(row.payload) for row in rows)

    def get_question_aggregate(self, question_id: UUID) -> QuestionAggregate:
        """Rebuild the full aggregate; every part is contract-revalidated."""
        row = self.session.get(QuestionRow, question_id)
        if row is None:
            raise NotFoundError(f"question {question_id} not found")
        identity = self.get_question_identity(question_id)
        revisions = self.list_revisions(question_id)
        if not revisions:
            raise ContractViolationError(
                f"question {question_id} has no revisions; a "
                "QuestionAggregate requires at least one"
            )
        instances = self.list_instances(question_id)
        history_rows = self.session.execute(
            select(StateHistoryRow)
            .where(StateHistoryRow.question_id == question_id)
            .order_by(StateHistoryRow.position)
        ).scalars()
        history = tuple(
            restore_state_snapshot(h.snapshot) for h in history_rows
        )
        return restore_aggregate(
            identity=identity,
            revisions=revisions,
            instances=instances,
            state_history=history,
        )

    # ------------------------------------------------------------------
    # State history: the ONLY authority for current lifecycle state.
    #
    # The review_state / publication_state / completeness columns on
    # qcore_revisions are creation-time snapshots for cheap queries; they
    # are never read back as "the current state".  Everything below goes
    # through the append-only qcore_state_history table.
    # ------------------------------------------------------------------

    def append_state_snapshot(
        self, question_id: UUID, snapshot: StateSnapshot
    ) -> None:
        """Append one StateSnapshot to the question's lifecycle history.

        History is append-only: existing rows are never modified.  The
        snapshot is strictly validated BEFORE it may be written:

        1. the referenced revision must exist (else NotFoundError);
        2. the revision must belong to ``question_id`` (else
           PersistenceError);
        3. ``snapshot.content_hash`` must equal the revision's actual
           content_hash (else PersistenceError).

        A snapshot that cannot prove which exact revision content it
        describes must never enter the history - the history is the only
        authority for current lifecycle state.
        """
        revision_row = self.session.execute(
            select(RevisionRow).where(
                RevisionRow.revision_id == snapshot.revision_id
            )
        ).scalar_one_or_none()
        if revision_row is None:
            raise NotFoundError(
                f"revision {snapshot.revision_id} not found; a state "
                "snapshot may only reference a stored revision"
            )
        if revision_row.question_id != question_id:
            raise PersistenceError(
                f"revision {snapshot.revision_id} does not belong to "
                f"question {question_id}"
            )
        if snapshot.content_hash != revision_row.content_hash:
            raise PersistenceError(
                f"snapshot content_hash {snapshot.content_hash} does not "
                f"match revision {snapshot.revision_id} content_hash "
                f"{revision_row.content_hash}"
            )
        current_max = self.session.execute(
            select(func.max(StateHistoryRow.position)).where(
                StateHistoryRow.question_id == question_id
            )
        ).scalar()
        next_position = 0 if current_max is None else current_max + 1
        self.session.add(
            StateHistoryRow(
                question_id=question_id,
                position=next_position,
                snapshot=dump_contract(snapshot),
            )
        )
        self.session.flush()

    def get_current_state(self, question_id: UUID) -> StateSnapshot | None:
        """Latest StateSnapshot of the question, derived from history only."""
        row = self.session.execute(
            select(StateHistoryRow)
            .where(StateHistoryRow.question_id == question_id)
            .order_by(StateHistoryRow.position.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        return restore_state_snapshot(row.snapshot)

    def get_revision_current_state(
        self, revision_id: UUID
    ) -> StateSnapshot | None:
        """Latest StateSnapshot for one revision, from history only.

        ``qcore_state_history`` is the single authority for current
        lifecycle state.  When history holds no entry for this revision
        the answer is ``None`` ("no state recorded yet") - the creation
        -time snapshot carried in the immutable revision payload is NOT
        consulted, so there is no second state source.
        """
        row = self.session.get(RevisionRow, revision_id)
        if row is None:
            raise NotFoundError(f"revision {revision_id} not found")
        history_rows = self.session.execute(
            select(StateHistoryRow)
            .where(StateHistoryRow.question_id == row.question_id)
            .order_by(StateHistoryRow.position.desc())
        ).scalars()
        for candidate in history_rows:
            snapshot = restore_state_snapshot(candidate.snapshot)
            if snapshot.revision_id == revision_id:
                return snapshot
        return None

    def list_state_history(
        self, question_id: UUID
    ) -> tuple[StateSnapshot, ...]:
        rows = self.session.execute(
            select(StateHistoryRow)
            .where(StateHistoryRow.question_id == question_id)
            .order_by(StateHistoryRow.position)
        ).scalars()
        return tuple(restore_state_snapshot(r.snapshot) for r in rows)


__all__ = ["QuestionCoreRepository"]
