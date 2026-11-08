"""Task D: Revision content immutability + State History as the single
authority for current lifecycle state.

Current state is DERIVED from the append-only qcore_state_history table -
never from the review_state / publication_state projection columns on
qcore_revisions (those are creation-time snapshots only).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import text

from question_core.contracts.v1 import (
    ApprovalRecord,
    Completeness,
    PublicationState,
    QuestionAggregate,
    ReviewState,
    StateSnapshot,
)
from question_core.persistence import (
    QuestionCoreRepository,
    session_scope,
)

from tests.persistence.synthetic import (
    make_identity,
    make_instance,
    make_rich_revision,
)

pytestmark = pytest.mark.pg

QID = UUID("00000000-0000-4000-8000-000000000055")
RID = UUID("00000000-0000-4000-8000-000000000066")


def _not_ready_snapshot(revision) -> StateSnapshot:
    return StateSnapshot(
        revision_id=revision.revision_id,
        content_hash=revision.content_hash,
        completeness=Completeness.INCOMPLETE,
        review=ReviewState.NOT_READY,
        publication=PublicationState.UNPUBLISHED,
    )


def _approved_snapshot(revision) -> StateSnapshot:
    content_hash = revision.content_hash
    approval = ApprovalRecord(
        revision_id=revision.revision_id,
        content_hash=content_hash,
        approved_by="reviewer-1",
        approved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        confirmed_fields=("content",),
    )
    return StateSnapshot(
        revision_id=revision.revision_id,
        content_hash=content_hash,
        completeness=Completeness.COMPLETE,
        review=ReviewState.APPROVED,
        publication=PublicationState.UNPUBLISHED,
        approval=approval,
    )


class TestStateHistoryAuthority:
    def _saved_revision(self, engine, clean_db):
        revision = make_rich_revision(QID, revision_number=1, revision_id=RID)
        initial = _not_ready_snapshot(revision)
        aggregate = QuestionAggregate(
            identity=make_identity(QID),
            revisions=(revision,),
            instances=(make_instance(QID, revision.revision_id),),
            state_history=(initial,),
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        return revision, initial

    def test_append_and_current_state(self, engine, clean_db):
        revision, initial = self._saved_revision(engine, clean_db)

        approved = _approved_snapshot(revision)
        with session_scope(engine) as session:
            QuestionCoreRepository(session).append_state_snapshot(
                QID, approved
            )

        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            current = repo.get_current_state(QID)
            history = repo.list_state_history(QID)
            revision_current = repo.get_revision_current_state(
                revision.revision_id
            )

        # current state is derived from history -> approved
        assert current is not None
        assert current.review == ReviewState.APPROVED
        assert revision_current is not None
        assert revision_current.review == ReviewState.APPROVED
        # history still retains the initial not_ready snapshot
        assert [s.review for s in history] == [
            ReviewState.NOT_READY,
            ReviewState.APPROVED,
        ]
        assert history[0] == initial

    def test_current_state_not_taken_from_projection_columns(
        self, engine, clean_db
    ):
        """The revision row's creation-time snapshot columns still say
        not_ready after the history advanced - proof that current state
        comes from qcore_state_history, not from the projection."""
        revision, _ = self._saved_revision(engine, clean_db)
        approved = _approved_snapshot(revision)
        with session_scope(engine) as session:
            QuestionCoreRepository(session).append_state_snapshot(
                QID, approved
            )

        with engine.connect() as conn:
            review_col, pub_col = conn.execute(
                text(
                    "SELECT review_state, publication_state "
                    "FROM qcore_revisions WHERE revision_id = :rid"
                ),
                {"rid": revision.revision_id},
            ).one()
        assert review_col == "not_ready"  # creation snapshot unchanged
        assert pub_col == "unpublished"

        with session_scope(engine) as session:
            current = QuestionCoreRepository(session).get_current_state(QID)
        assert current.review == ReviewState.APPROVED

    def test_revision_payload_and_content_unchanged_after_append(
        self, engine, clean_db
    ):
        revision, _ = self._saved_revision(engine, clean_db)
        before = revision
        approved = _approved_snapshot(revision)
        with session_scope(engine) as session:
            QuestionCoreRepository(session).append_state_snapshot(
                QID, approved
            )

        with session_scope(engine) as session:
            after = QuestionCoreRepository(session).get_revision(
                revision.revision_id
            )
        assert after == before  # payload incl. answers/explanation/evidence
        assert after.content_hash == before.content_hash
        assert after.answers == before.answers
        assert after.explanation_blocks == before.explanation_blocks
        assert after.evidence == before.evidence
        assert after.content == before.content

    def test_direct_update_rejected(self, engine, clean_db):
        revision, _ = self._saved_revision(engine, clean_db)
        with pytest.raises(Exception) as exc:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE qcore_revisions SET payload = "
                        "'{\"tampered\": true}'::jsonb WHERE revision_id = :rid"
                    ),
                    {"rid": revision.revision_id},
                )
        assert "immutable" in str(exc.value)

    def test_direct_delete_rejected(self, engine, clean_db):
        revision, _ = self._saved_revision(engine, clean_db)
        with pytest.raises(Exception) as exc:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "DELETE FROM qcore_revisions WHERE revision_id = :rid"
                    ),
                    {"rid": revision.revision_id},
                )
        assert "immutable" in str(exc.value)

    def test_history_is_append_only(self, engine, clean_db):
        revision, _ = self._saved_revision(engine, clean_db)
        approved = _approved_snapshot(revision)
        with session_scope(engine) as session:
            QuestionCoreRepository(session).append_state_snapshot(
                QID, approved
            )
        # both snapshots accumulate: earlier rows are never replaced
        with session_scope(engine) as session:
            history = QuestionCoreRepository(session).list_state_history(QID)
        assert len(history) == 2
        assert history[0].review == ReviewState.NOT_READY
        assert history[1].review == ReviewState.APPROVED
        with engine.connect() as conn:
            positions = conn.execute(
                text(
                    "SELECT position FROM qcore_state_history "
                    "WHERE question_id = :qid ORDER BY position"
                ),
                {"qid": QID},
            ).scalars().all()
        assert positions == [0, 1]

    def test_unknown_question_append_rejected(self, engine, clean_db):
        from question_core.persistence import NotFoundError

        revision = make_rich_revision(QID, revision_id=RID)
        snapshot = _not_ready_snapshot(revision)
        with pytest.raises(NotFoundError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).append_state_snapshot(
                    UUID("00000000-0000-4000-8000-00000000dead"), snapshot
                )


class TestStrictAppendValidation:
    """R1-FIX-2: a state snapshot must prove which exact revision content
    it describes before it may enter the history."""

    QID_B = UUID("00000000-0000-4000-8000-0000000000b0")
    RID_B = UUID("00000000-0000-4000-8000-0000000000b1")

    def _saved_revision(self, engine, clean_db):
        revision = make_rich_revision(QID, revision_number=1, revision_id=RID)
        aggregate = QuestionAggregate(
            identity=make_identity(QID),
            revisions=(revision,),
            instances=(make_instance(QID, revision.revision_id),),
            state_history=(),
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        return revision

    def test_unknown_revision_rejected(self, engine, clean_db):
        from question_core.persistence import NotFoundError

        self._saved_revision(engine, clean_db)
        ghost = make_rich_revision(
            QID,
            revision_number=2,
            revision_id=UUID("00000000-0000-4000-8000-00000000dead"),
        )
        snapshot = _not_ready_snapshot(ghost)  # revision never stored
        with pytest.raises(NotFoundError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).append_state_snapshot(
                    QID, snapshot
                )

    def test_foreign_question_revision_rejected(self, engine, clean_db):
        from question_core.persistence import PersistenceError

        self._saved_revision(engine, clean_db)
        rev_b = make_rich_revision(
            self.QID_B, revision_number=1, revision_id=self.RID_B
        )
        agg_b = QuestionAggregate(
            identity=make_identity(self.QID_B),
            revisions=(rev_b,),
            instances=(
                make_instance(
                    self.QID_B,
                    self.RID_B,
                    instance_id=UUID("00000000-0000-4000-8000-0000000000b2"),
                ),
            ),
            state_history=(),
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(agg_b)

        # snapshot valid for rev_b, but filed under question A
        snapshot = _not_ready_snapshot(rev_b)
        with pytest.raises(PersistenceError) as exc:
            with session_scope(engine) as session:
                QuestionCoreRepository(session).append_state_snapshot(
                    QID, snapshot
                )
        assert "does not belong to" in str(exc.value)

    def test_content_hash_mismatch_rejected(self, engine, clean_db):
        from question_core.persistence import PersistenceError

        revision = self._saved_revision(engine, clean_db)
        bogus = StateSnapshot(
            revision_id=revision.revision_id,
            content_hash="f" * 64,  # wrong hash
            completeness=Completeness.INCOMPLETE,
            review=ReviewState.NOT_READY,
            publication=PublicationState.UNPUBLISHED,
        )
        with pytest.raises(PersistenceError) as exc:
            with session_scope(engine) as session:
                QuestionCoreRepository(session).append_state_snapshot(
                    QID, bogus
                )
        assert "content_hash" in str(exc.value)

    def test_valid_revision_and_hash_append_ok(self, engine, clean_db):
        revision = self._saved_revision(engine, clean_db)
        snapshot = _not_ready_snapshot(revision)
        with session_scope(engine) as session:
            QuestionCoreRepository(session).append_state_snapshot(
                QID, snapshot
            )
        with session_scope(engine) as session:
            history = QuestionCoreRepository(session).list_state_history(QID)
        assert history == (snapshot,)

    def test_failed_append_leaves_no_rows(self, engine, clean_db):
        from question_core.persistence import (
            NotFoundError,
            PersistenceError,
        )

        revision = self._saved_revision(engine, clean_db)
        good = _not_ready_snapshot(revision)
        with session_scope(engine) as session:
            QuestionCoreRepository(session).append_state_snapshot(QID, good)

        attempts = []
        ghost = _not_ready_snapshot(
            make_rich_revision(
                QID,
                revision_number=2,
                revision_id=UUID("00000000-0000-4000-8000-00000000dead"),
            )
        )
        bogus = StateSnapshot(
            revision_id=revision.revision_id,
            content_hash="f" * 64,
            completeness=Completeness.INCOMPLETE,
            review=ReviewState.NOT_READY,
            publication=PublicationState.UNPUBLISHED,
        )
        for snap in (ghost, bogus):
            with pytest.raises((NotFoundError, PersistenceError)):
                with session_scope(engine) as session:
                    QuestionCoreRepository(session).append_state_snapshot(
                        QID, snap
                    )
            attempts.append(snap)

        with session_scope(engine) as session:
            history = QuestionCoreRepository(session).list_state_history(QID)
        assert history == (good,)  # only the valid row exists

    def test_aggregate_contains_no_invalid_snapshots(self, engine, clean_db):
        from question_core.persistence import PersistenceError

        revision = self._saved_revision(engine, clean_db)
        good = _not_ready_snapshot(revision)
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            repo.append_state_snapshot(QID, good)
            bogus = StateSnapshot(
                revision_id=revision.revision_id,
                content_hash="f" * 64,
                completeness=Completeness.INCOMPLETE,
                review=ReviewState.NOT_READY,
                publication=PublicationState.UNPUBLISHED,
            )
            with pytest.raises(PersistenceError):
                repo.append_state_snapshot(QID, bogus)

        with session_scope(engine) as session:
            aggregate = QuestionCoreRepository(session).get_question_aggregate(
                QID
            )
        assert aggregate.state_history == (good,)


class TestNoHistoryMeansNone:
    """R1-FIX-2: without history the current state is None - the creation
    -time snapshot inside the immutable revision payload is NOT used as a
    state source."""

    def test_no_history_returns_none_even_with_creation_snapshot(
        self, engine, clean_db
    ):
        from tests.persistence.synthetic import make_published_revision

        revision = make_published_revision(QID, revision_id=RID)
        assert revision.state is not None  # payload carries a creation state
        aggregate = QuestionAggregate(
            identity=make_identity(QID),
            revisions=(revision,),
            instances=(make_instance(QID, revision.revision_id),),
            state_history=(),  # no history recorded
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)

        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            assert repo.get_revision_current_state(RID) is None
            assert repo.get_current_state(QID) is None

    def test_with_history_returns_latest(self, engine, clean_db):
        revision = make_rich_revision(QID, revision_number=1, revision_id=RID)
        aggregate = QuestionAggregate(
            identity=make_identity(QID),
            revisions=(revision,),
            instances=(make_instance(QID, revision.revision_id),),
            state_history=(),
        )
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            repo.save_question_aggregate(aggregate)
            first = _not_ready_snapshot(revision)
            second = _approved_snapshot(revision)
            repo.append_state_snapshot(QID, first)
            repo.append_state_snapshot(QID, second)

        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            assert repo.get_revision_current_state(RID) == second
            assert repo.get_current_state(QID) == second


class TestStateHistoryDbProtection:
    """R1-FIX-2 F5: raw SQL cannot rewrite history either."""

    def _history_row(self, engine, clean_db):
        revision = make_rich_revision(QID, revision_number=1, revision_id=RID)
        aggregate = QuestionAggregate(
            identity=make_identity(QID),
            revisions=(revision,),
            instances=(make_instance(QID, revision.revision_id),),
            state_history=(_not_ready_snapshot(revision),),
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        return revision

    def test_raw_update_rejected(self, engine, clean_db):
        self._history_row(engine, clean_db)
        with pytest.raises(Exception) as exc:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE qcore_state_history SET position = 99 "
                        "WHERE question_id = :qid"
                    ),
                    {"qid": QID},
                )
        assert "append-only" in str(exc.value)

    def test_raw_delete_rejected(self, engine, clean_db):
        self._history_row(engine, clean_db)
        with pytest.raises(Exception) as exc:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "DELETE FROM qcore_state_history WHERE question_id = :qid"
                    ),
                    {"qid": QID},
                )
        assert "append-only" in str(exc.value)

    def test_failed_mutation_preserves_history(self, engine, clean_db):
        revision = self._history_row(engine, clean_db)
        for stmt in (
            "UPDATE qcore_state_history SET snapshot = '{}'::jsonb "
            "WHERE question_id = :qid",
            "DELETE FROM qcore_state_history WHERE question_id = :qid",
        ):
            with pytest.raises(Exception):
                with engine.begin() as conn:
                    conn.execute(text(stmt), {"qid": QID})
        with session_scope(engine) as session:
            history = QuestionCoreRepository(session).list_state_history(QID)
        assert history == (_not_ready_snapshot(revision),)

    def test_revision_immutability_still_enforced(self, engine, clean_db):
        self._history_row(engine, clean_db)
        with pytest.raises(Exception) as exc:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE qcore_revisions SET payload = "
                        "'{\"x\": 1}'::jsonb WHERE revision_id = :rid"
                    ),
                    {"rid": RID},
                )
        assert "immutable" in str(exc.value)
