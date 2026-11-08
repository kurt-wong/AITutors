"""SQLAlchemy 2.0 table definitions for Question Core persistence.

Layout (all tables prefixed ``qcore_``):

* ``qcore_candidates``        — one ingestion candidate (full payload JSONB).
* ``qcore_questions``         — logical question identity.
* ``qcore_revisions``         — immutable content versions (payload JSONB is
  the authoritative restore source; a trigger rejects UPDATE/DELETE).
* ``qcore_question_instances``— one occurrence of a question inside one paper.
* ``qcore_state_history``     — append-only StateSnapshot history of a question.
* ``qcore_answer_rows``       — one row per TypedAnswer of a candidate/revision.
* ``qcore_evidence_records``  — one row per EvidenceRecord.
* ``qcore_evidence_conflicts``— one row per EvidenceConflict.
* ``qcore_asset_refs``        — Asset references (ids + storage pointers only;
  media bytes are never copied here).
* ``qcore_material_refs``     — Material references.

The child tables (answers / evidence / assets / materials) are queryable
projections carrying ownership FKs and uniqueness constraints.  They are
written from the same contract models, in the same transaction, as the
payload JSONB on the parent row.  Restoring a contract object always goes
through the payload JSONB plus full contract re-validation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# One-of owner columns shared by the projection tables: exactly one of
# candidate_id / revision_id must be set.
_ONE_OWNER_CHECK = CheckConstraint(
    "(candidate_id IS NOT NULL)::int + (revision_id IS NOT NULL)::int = 1",
    name="ck_%(table_owner)s_one_owner",
)


class CandidateRow(Base):
    __tablename__ = "qcore_candidates"
    __table_args__ = (
        # P0-2 fix: uniqueness is per adapter version so results of
        # different adapter versions can coexist (upgrade traceability).
        # adapter_version is NOT NULL (the contract requires a non-empty
        # version), so the PostgreSQL "NULLs never collide" quirk cannot
        # occur - there is no NULL component in this unique key.
        UniqueConstraint(
            "idempotency_key",
            "adapter_version",
            name="uq_candidate_key_version",
        ),
    )

    candidate_id: Mapped[UUID] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(Text, nullable=False)
    completeness: Mapped[str] = mapped_column(Text, nullable=False)
    ingestion_run_id: Mapped[UUID] = mapped_column(nullable=False)
    adapter_version: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    contract_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    row_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QuestionRow(Base):
    __tablename__ = "qcore_questions"

    question_id: Mapped[UUID] = mapped_column(primary_key=True)
    identity_fingerprint: Mapped[str | None] = mapped_column(Text)
    embedding_ref: Mapped[str | None] = mapped_column(Text)
    contract_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    row_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RevisionRow(Base):
    __tablename__ = "qcore_revisions"
    __table_args__ = (
        UniqueConstraint(
            "question_id", "revision_number", name="uq_revision_question_number"
        ),
        # Referential pairing target for the composite FK on instances:
        # an instance may only reference a revision of ITS OWN question.
        UniqueConstraint(
            "question_id", "revision_id", name="uq_revision_question_ref"
        ),
    )

    revision_id: Mapped[UUID] = mapped_column(primary_key=True)
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("qcore_questions.question_id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(Text, nullable=False)
    answer_visibility: Mapped[str] = mapped_column(Text, nullable=False)
    explanation_visibility: Mapped[str] = mapped_column(Text, nullable=False)
    #: Denormalised projections of ``state`` for cheap lifecycle queries.
    completeness: Mapped[str] = mapped_column(Text, nullable=False)
    review_state: Mapped[str] = mapped_column(Text, nullable=False)
    publication_state: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    contract_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    change_note: Mapped[str | None] = mapped_column(Text)
    row_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InstanceRow(Base):
    __tablename__ = "qcore_question_instances"
    __table_args__ = (
        # Natural "occurrence slot": one question occupies one position in
        # one source document.  A second write of the same slot is a
        # duplicate instance, whichever UUID it carries.
        UniqueConstraint(
            "question_id",
            "source_document_id",
            "ordinal",
            name="uq_instance_slot",
        ),
        # Composite FK: the (question_id, revision_id) pair must exist in
        # qcore_revisions.  This rejects Question A + Revision of Question B
        # AT THE DATABASE level - python checks are not the only defence.
        ForeignKeyConstraint(
            ["question_id", "revision_id"],
            ["qcore_revisions.question_id", "qcore_revisions.revision_id"],
            name="fk_instance_revision_pair",
        ),
    )

    instance_id: Mapped[UUID] = mapped_column(primary_key=True)
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("qcore_questions.question_id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("qcore_revisions.revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_document_id: Mapped[str] = mapped_column(Text, nullable=False)
    printed_number: Mapped[str | None] = mapped_column(Text)
    question_numbers: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'")
    )
    section: Mapped[str | None] = mapped_column(Text)
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    contract_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    row_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StateHistoryRow(Base):
    __tablename__ = "qcore_state_history"
    __table_args__ = (
        UniqueConstraint("question_id", "position", name="uq_state_history_pos"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("qcore_questions.question_id", ondelete="RESTRICT"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    row_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AnswerRow(Base):
    __tablename__ = "qcore_answer_rows"
    __table_args__ = (
        CheckConstraint(
            "(candidate_id IS NOT NULL)::int + (revision_id IS NOT NULL)::int = 1",
            name="ck_answer_rows_one_owner",
        ),
        Index(
            "uq_answer_rev_pos",
            "revision_id",
            "position",
            unique=True,
            postgresql_where=text("revision_id IS NOT NULL"),
        ),
        Index(
            "uq_answer_cand_pos",
            "candidate_id",
            "position",
            unique=True,
            postgresql_where=text("candidate_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("qcore_candidates.candidate_id", ondelete="CASCADE")
    )
    revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("qcore_revisions.revision_id", ondelete="RESTRICT")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    answer_type: Mapped[str] = mapped_column(Text, nullable=False)
    completeness: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class EvidenceRecordRow(Base):
    __tablename__ = "qcore_evidence_records"
    __table_args__ = (
        CheckConstraint(
            "(candidate_id IS NOT NULL)::int + (revision_id IS NOT NULL)::int = 1",
            name="ck_evidence_records_one_owner",
        ),
        Index(
            "uq_evidence_rev_id",
            "revision_id",
            "evidence_id",
            unique=True,
            postgresql_where=text("revision_id IS NOT NULL"),
        ),
        Index(
            "uq_evidence_cand_id",
            "candidate_id",
            "evidence_id",
            unique=True,
            postgresql_where=text("candidate_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("qcore_candidates.candidate_id", ondelete="CASCADE")
    )
    revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("qcore_revisions.revision_id", ondelete="RESTRICT")
    )
    evidence_id: Mapped[UUID] = mapped_column(nullable=False)
    target_path: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_role: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_status: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class EvidenceConflictRow(Base):
    __tablename__ = "qcore_evidence_conflicts"
    __table_args__ = (
        CheckConstraint(
            "(candidate_id IS NOT NULL)::int + (revision_id IS NOT NULL)::int = 1",
            name="ck_evidence_conflicts_one_owner",
        ),
        Index(
            "uq_conflict_rev_id",
            "revision_id",
            "conflict_id",
            unique=True,
            postgresql_where=text("revision_id IS NOT NULL"),
        ),
        Index(
            "uq_conflict_cand_id",
            "candidate_id",
            "conflict_id",
            unique=True,
            postgresql_where=text("candidate_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("qcore_candidates.candidate_id", ondelete="CASCADE")
    )
    revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("qcore_revisions.revision_id", ondelete="RESTRICT")
    )
    conflict_id: Mapped[UUID] = mapped_column(nullable=False)
    target_path: Mapped[str] = mapped_column(Text, nullable=False)
    is_critical: Mapped[bool] = mapped_column(nullable=False)
    resolution: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class AssetRefRow(Base):
    __tablename__ = "qcore_asset_refs"
    __table_args__ = (
        CheckConstraint(
            "(candidate_id IS NOT NULL)::int + (revision_id IS NOT NULL)::int = 1",
            name="ck_asset_refs_one_owner",
        ),
        Index(
            "uq_asset_rev_id",
            "revision_id",
            "asset_id",
            unique=True,
            postgresql_where=text("revision_id IS NOT NULL"),
        ),
        Index(
            "uq_asset_cand_id",
            "candidate_id",
            "asset_id",
            unique=True,
            postgresql_where=text("candidate_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("qcore_candidates.candidate_id", ondelete="CASCADE")
    )
    revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("qcore_revisions.revision_id", ondelete="RESTRICT")
    )
    asset_id: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class MaterialRefRow(Base):
    __tablename__ = "qcore_material_refs"
    __table_args__ = (
        CheckConstraint(
            "(candidate_id IS NOT NULL)::int + (revision_id IS NOT NULL)::int = 1",
            name="ck_material_refs_one_owner",
        ),
        Index(
            "uq_material_rev_id",
            "revision_id",
            "material_id",
            unique=True,
            postgresql_where=text("revision_id IS NOT NULL"),
        ),
        Index(
            "uq_material_cand_id",
            "candidate_id",
            "material_id",
            unique=True,
            postgresql_where=text("candidate_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("qcore_candidates.candidate_id", ondelete="CASCADE")
    )
    revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("qcore_revisions.revision_id", ondelete="RESTRICT")
    )
    material_id: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


# ---------------------------------------------------------------------------
# Immutability trigger for stored revision content
# ---------------------------------------------------------------------------

REVISION_IMMUTABILITY_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION qcore_block_revision_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'qcore_revisions rows are immutable: % is not allowed', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql
"""

REVISION_IMMUTABILITY_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS qcore_revisions_immutable ON qcore_revisions;
CREATE TRIGGER qcore_revisions_immutable
BEFORE UPDATE OR DELETE ON qcore_revisions
FOR EACH ROW EXECUTE FUNCTION qcore_block_revision_mutation()
"""


# ---------------------------------------------------------------------------
# Append-only trigger for state history (the current-state authority)
# ---------------------------------------------------------------------------

STATE_HISTORY_IMMUTABILITY_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION qcore_block_state_history_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'qcore_state_history rows are append-only: % is not allowed', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql
"""

STATE_HISTORY_IMMUTABILITY_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS qcore_state_history_immutable ON qcore_state_history;
CREATE TRIGGER qcore_state_history_immutable
BEFORE UPDATE OR DELETE ON qcore_state_history
FOR EACH ROW EXECUTE FUNCTION qcore_block_state_history_mutation()
"""
