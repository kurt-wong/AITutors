"""Real PostgreSQL transaction tests: rollback, duplicate boundaries and
revision immutability."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text

from question_core.contracts.v1 import QuestionAggregate
from question_core.persistence import (
    DuplicateCandidateError,
    DuplicateInstanceError,
    DuplicateQuestionError,
    DuplicateRevisionError,
    QuestionCoreRepository,
    session_scope,
)
from question_core.persistence.models import (
    CandidateRow,
    InstanceRow,
    QuestionRow,
    RevisionRow,
)

from tests.persistence.synthetic import (
    make_identity,
    make_instance,
    make_preprocessing_candidate,
    make_rich_aggregate,
    make_rich_revision,
    make_single_answer_revision,
)

pytestmark = pytest.mark.pg

QID = UUID("00000000-0000-4000-8000-000000000055")


def _count(engine, model) -> int:
    from sqlalchemy import func, select

    with session_scope(engine) as session:
        return session.execute(
            select(func.count()).select_from(model)
        ).scalar()


class TestTransactionalRollback:
    def test_failed_aggregate_leaves_nothing_behind(self, engine, clean_db):
        """Two instances of the same aggregate share one occurrence slot:
        the second INSERT violates the natural key mid-transaction, so the
        candidate written in the same transaction must be rolled back too."""
        aggregate = make_rich_aggregate()
        duplicate_slot = make_instance(
            aggregate.identity.question_id,
            aggregate.revisions[0].revision_id,
            instance_id=UUID("00000000-0000-4000-8000-000000000099"),
            source_document_id=aggregate.instances[0].source_document_id,
            ordinal=aggregate.instances[0].ordinal,
        )
        broken = QuestionAggregate(
            identity=aggregate.identity,
            revisions=aggregate.revisions,
            instances=aggregate.instances + (duplicate_slot,),
            state_history=aggregate.state_history,
        )
        candidate = make_preprocessing_candidate()

        with pytest.raises(DuplicateInstanceError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).save_candidate_with_question(
                    candidate, broken
                )

        # nothing persisted: no half-written question, no candidate
        assert _count(engine, QuestionRow) == 0
        assert _count(engine, RevisionRow) == 0
        assert _count(engine, InstanceRow) == 0
        assert _count(engine, CandidateRow) == 0

    def test_instance_id_collision_rolls_back_combined_write(
        self, engine, clean_db
    ):
        """A second combined write re-uses an existing instance_id: the
        failure happens after the new candidate rows were INSERTed in the
        same transaction and must roll them back."""
        first = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(first)

        candidate = make_preprocessing_candidate(
            candidate_id=UUID("00000000-0000-4000-8000-0000000000c9"),
            doc_id="synthetic_doc_pre_2",
        )
        other_identity = make_identity(
            UUID("00000000-0000-4000-8000-000000000056")
        )
        revision = make_rich_revision(
            other_identity.question_id,
            revision_id=UUID("00000000-0000-4000-8000-000000000067"),
        )
        colliding_instance = make_instance(
            other_identity.question_id,
            revision.revision_id,
            instance_id=first.instances[0].instance_id,  # <-- existing id
            source_document_id="another_paper",
        )
        second = QuestionAggregate(
            identity=other_identity,
            revisions=(revision,),
            instances=(colliding_instance,),
        )

        with pytest.raises(DuplicateInstanceError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).save_candidate_with_question(
                    candidate, second
                )

        # the first aggregate is intact; the failed write left nothing
        assert _count(engine, QuestionRow) == 1
        assert _count(engine, CandidateRow) == 0
        with session_scope(engine) as session:
            assert session.get(CandidateRow, candidate.core.candidate_id) is None


class TestDuplicateBoundaries:
    def test_same_aggregate_twice_rejected(self, engine, clean_db):
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        with pytest.raises(DuplicateQuestionError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).save_question_aggregate(
                    aggregate
                )

    def test_same_candidate_id_twice_rejected(self, engine, clean_db):
        candidate = make_preprocessing_candidate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_candidate(candidate)
        with pytest.raises(DuplicateCandidateError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).save_candidate(candidate)

    def test_same_idempotency_key_same_version_rejected(
        self, engine, clean_db
    ):
        """Idempotency boundary (per adapter version): re-importing the
        same logical source with the same adapter version must NOT create
        a second candidate.  Different adapter versions coexist - see
        test_pg_idempotency.py for the versioning rules."""
        first = make_preprocessing_candidate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_candidate(first)

        second = make_preprocessing_candidate(
            candidate_id=UUID("00000000-0000-4000-8000-0000000000c3"),
        )  # same doc_id -> same idempotency key, same adapter version
        assert (
            second.core.ingestion.candidate_idempotency_key
            == first.core.ingestion.candidate_idempotency_key
        )
        assert (
            second.core.ingestion.adapter_version
            == first.core.ingestion.adapter_version
        )
        with pytest.raises(DuplicateCandidateError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).save_candidate(second)
        assert _count(engine, CandidateRow) == 1

    def test_duplicate_revision_number_rejected(self, engine, clean_db):
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)

        clash = make_single_answer_revision(
            aggregate.identity.question_id,
            revision_number=1,  # already taken
            revision_id=UUID("00000000-0000-4000-8000-000000000068"),
        )
        with pytest.raises(DuplicateRevisionError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).add_revision(clash)

    def test_duplicate_revision_id_rejected(self, engine, clean_db):
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)

        clash = make_single_answer_revision(
            aggregate.identity.question_id,
            revision_number=3,
            revision_id=aggregate.revisions[0].revision_id,  # existing id
        )
        with pytest.raises(DuplicateRevisionError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).add_revision(clash)

    def test_duplicate_instance_slot_rejected(self, engine, clean_db):
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)

        clone = make_instance(
            aggregate.identity.question_id,
            aggregate.instances[0].revision_id,
            instance_id=UUID("00000000-0000-4000-8000-00000000009a"),
            source_document_id=aggregate.instances[0].source_document_id,
            ordinal=aggregate.instances[0].ordinal,
        )
        with pytest.raises(DuplicateInstanceError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).add_instance(clone)

    def test_duplicate_instance_id_rejected(self, engine, clean_db):
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)

        clone = make_instance(
            aggregate.identity.question_id,
            aggregate.instances[0].revision_id,
            instance_id=aggregate.instances[0].instance_id,
            source_document_id="different_paper",
            ordinal=1,
        )
        with pytest.raises(DuplicateInstanceError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).add_instance(clone)

    def test_append_revision_is_allowed(self, engine, clean_db):
        """Distinct content gets a distinct revision_number and lands."""
        identity = make_identity(QID)
        revision = make_rich_revision(QID, revision_number=1)
        aggregate = QuestionAggregate(
            identity=identity,
            revisions=(revision,),
            instances=(make_instance(QID, revision.revision_id),),
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)

        extra = make_single_answer_revision(QID, revision_number=2)
        with session_scope(engine) as session:
            QuestionCoreRepository(session).add_revision(extra)
        with session_scope(engine) as session:
            listed = QuestionCoreRepository(session).list_revisions(QID)
        assert [r.revision_number for r in listed] == [1, 2]
        assert listed[1] == extra


class TestRevisionImmutability:
    def _persisted_revision(self, engine, clean_db):
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        return aggregate.revisions[0]

    def test_update_rejected_by_trigger(self, engine, clean_db):
        revision = self._persisted_revision(engine, clean_db)
        with pytest.raises(Exception) as exc:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE qcore_revisions SET payload = "
                        "'{\"tampered\": true}'::jsonb "
                        "WHERE revision_id = :rid"
                    ),
                    {"rid": revision.revision_id},
                )
        assert "immutable" in str(exc.value)

    def test_update_content_columns_rejected(self, engine, clean_db):
        revision = self._persisted_revision(engine, clean_db)
        with pytest.raises(Exception) as exc:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE qcore_revisions SET content_hash = :h "
                        "WHERE revision_id = :rid"
                    ),
                    {"h": "f" * 64, "rid": revision.revision_id},
                )
        assert "immutable" in str(exc.value)

    def test_delete_rejected_by_trigger(self, engine, clean_db):
        revision = self._persisted_revision(engine, clean_db)
        with pytest.raises(Exception) as exc:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "DELETE FROM qcore_revisions WHERE revision_id = :rid"
                    ),
                    {"rid": revision.revision_id},
                )
        assert "immutable" in str(exc.value)

    def test_payload_unchanged_after_failed_mutation(self, engine, clean_db):
        revision = self._persisted_revision(engine, clean_db)
        original = revision
        for statement, params in (
            (
                "UPDATE qcore_revisions SET payload = '{\"x\": 1}'::jsonb "
                "WHERE revision_id = :rid",
                {"rid": revision.revision_id},
            ),
            (
                "UPDATE qcore_revisions SET revision_number = 99 "
                "WHERE revision_id = :rid",
                {"rid": revision.revision_id},
            ),
            (
                "DELETE FROM qcore_revisions WHERE revision_id = :rid",
                {"rid": revision.revision_id},
            ),
        ):
            with pytest.raises(Exception):
                with engine.begin() as conn:
                    conn.execute(text(statement), params)

        with session_scope(engine) as session:
            restored = QuestionCoreRepository(session).get_revision(
                revision.revision_id
            )
        assert restored == original
