"""Task E: Question/Revision composite foreign key + Instance occurrence.

The (question_id, revision_id) pair of every instance row must exist in
qcore_revisions - Question A may never point at a Revision of Question B.
The DATABASE rejects the illegal combination directly (composite FK
fk_instance_revision_pair); python checks are not the only defence.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text

from question_core.contracts.v1 import QuestionAggregate
from question_core.persistence import (
    DuplicateInstanceError,
    PersistenceError,
    QuestionCoreRepository,
    session_scope,
)

from tests.persistence.synthetic import (
    make_identity,
    make_instance,
    make_rich_aggregate,
    make_rich_revision,
    make_single_answer_revision,
)

pytestmark = pytest.mark.pg

QID_A = UUID("00000000-0000-4000-8000-0000000000a0")
QID_B = UUID("00000000-0000-4000-8000-0000000000b0")
RID_A = UUID("00000000-0000-4000-8000-0000000000a1")
RID_B = UUID("00000000-0000-4000-8000-0000000000b1")


def _save_two_questions(engine):
    """Question A (revision A) and Question B (revision B), both valid."""
    rev_a = make_rich_revision(QID_A, revision_number=1, revision_id=RID_A)
    agg_a = QuestionAggregate(
        identity=make_identity(QID_A),
        revisions=(rev_a,),
        instances=(
            make_instance(
                QID_A,
                RID_A,
                instance_id=UUID("00000000-0000-4000-8000-0000000000a2"),
                source_document_id="paper_a",
            ),
        ),
    )
    rev_b = make_single_answer_revision(
        QID_B, revision_number=1, revision_id=RID_B
    )
    agg_b = QuestionAggregate(
        identity=make_identity(QID_B),
        revisions=(rev_b,),
        instances=(
            make_instance(
                QID_B,
                RID_B,
                instance_id=UUID("00000000-0000-4000-8000-0000000000b2"),
                source_document_id="paper_b",
            ),
        ),
    )
    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        repo.save_question_aggregate(agg_a)
        repo.save_question_aggregate(agg_b)
    return agg_a, agg_b


class TestCompositeForeignKey:
    def test_matching_pairs_allowed(self, engine, clean_db):
        agg_a, agg_b = _save_two_questions(engine)
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            assert (
                repo.get_question_aggregate(QID_A) == agg_a
            )
            assert (
                repo.get_question_aggregate(QID_B) == agg_b
            )

    def test_mismatched_pair_rejected_by_database(self, engine, clean_db):
        """Raw SQL bypasses every python check - only the composite FK
        stands between the write and the database."""
        _save_two_questions(engine)
        import uuid as uuid_mod

        with pytest.raises(Exception) as exc:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO qcore_question_instances ("
                        "instance_id, question_id, revision_id, "
                        "source_document_id, question_numbers, ordinal, "
                        "payload, contract_created_at) VALUES ("
                        ":iid, :qid, :rid, 'paper_x', '{}', 1, "
                        "'{}'::jsonb, now())"
                    ),
                    {
                        "iid": uuid_mod.uuid4(),
                        "qid": QID_A,  # question A ...
                        "rid": RID_B,  # ... pointing at revision of B
                    },
                )
        assert "fk_instance_revision_pair" in str(exc.value)

    def test_mismatched_pair_rejected_via_repository(self, engine, clean_db):
        _save_two_questions(engine)
        bad = make_instance(
            QID_A,  # question A
            RID_B,  # revision of question B
            instance_id=UUID("00000000-0000-4000-8000-0000000000c3"),
            source_document_id="paper_x",
        )
        with pytest.raises(PersistenceError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).add_instance(bad)

    def test_illegal_combo_rolls_back_whole_transaction(
        self, engine, clean_db
    ):
        """A combined write whose instance carries a mismatched pair fails
        at the database and rolls the whole transaction back.

        Both questions/revisions already exist, so the COMPOSITE FK is
        what rejects the pair (not a missing-row FK).
        """
        _save_two_questions(engine)
        aggregate = make_rich_aggregate()  # a third, fresh question
        bad_instance = make_instance(
            aggregate.identity.question_id,
            RID_B,  # revision of question B - pair does not exist
            instance_id=UUID("00000000-0000-4000-8000-0000000000c4"),
            source_document_id="paper_x",
        )

        with pytest.raises(PersistenceError) as exc:
            with session_scope(engine) as session:
                repo = QuestionCoreRepository(session)
                repo.save_question_aggregate(
                    QuestionAggregate(
                        identity=aggregate.identity,
                        revisions=aggregate.revisions,
                    )
                )
                repo.add_instance(bad_instance)
        assert "fk_instance_revision_pair" in str(exc.value)

        from sqlalchemy import func, select

        from question_core.persistence.models import (
            InstanceRow,
            QuestionRow,
            RevisionRow,
        )

        with session_scope(engine) as session:
            # the failed combined write left nothing; the two pre-existing
            # questions are untouched
            assert (
                session.execute(
                    select(func.count()).select_from(QuestionRow)
                ).scalar()
                == 2
            )
            assert (
                session.execute(
                    select(func.count()).select_from(RevisionRow)
                ).scalar()
                == 2
            )
            assert (
                session.execute(
                    select(func.count()).select_from(InstanceRow)
                ).scalar()
                == 2
            )

    def test_normal_aggregate_round_trip_still_works(self, engine, clean_db):
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        with session_scope(engine) as session:
            restored = QuestionCoreRepository(session).get_question_aggregate(
                aggregate.identity.question_id
            )
        assert restored == aggregate


class TestInstanceOccurrence:
    """Occurrence semantics: one question occupies one slot
    (question_id, source_document_id, ordinal); printed_number is display
    info only.  Re-importing the same position must not duplicate."""

    def test_duplicate_import_creates_no_duplicate_instance(
        self, engine, clean_db
    ):
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)

        # re-import of the SAME occurrence: same slot, fresh UUID
        reimport = make_instance(
            aggregate.identity.question_id,
            aggregate.instances[0].revision_id,
            instance_id=UUID("00000000-0000-4000-8000-0000000000d1"),
            source_document_id=aggregate.instances[0].source_document_id,
            ordinal=aggregate.instances[0].ordinal,
        )
        with pytest.raises(DuplicateInstanceError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).add_instance(reimport)

        with session_scope(engine) as session:
            listed = QuestionCoreRepository(session).list_instances(
                aggregate.identity.question_id
            )
        assert len(listed) == 2  # exactly the two original occurrences

    def test_printed_number_is_not_identity(self, engine, clean_db):
        """Same slot with a different printed_number is still the same
        occurrence and is rejected."""
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)

        clone = make_instance(
            aggregate.identity.question_id,
            aggregate.instances[0].revision_id,
            instance_id=UUID("00000000-0000-4000-8000-0000000000d2"),
            source_document_id=aggregate.instances[0].source_document_id,
            ordinal=aggregate.instances[0].ordinal,
        )
        from question_core.contracts.v1 import QuestionInstance

        payload = clone.model_dump(mode="json")
        payload["printed_number"] = "99"
        clone2 = QuestionInstance.model_validate(payload)
        with pytest.raises(DuplicateInstanceError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).add_instance(clone2)

    def test_same_question_two_papers_two_instances(self, engine, clean_db):
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        extra = make_instance(
            aggregate.identity.question_id,
            aggregate.instances[0].revision_id,
            instance_id=UUID("00000000-0000-4000-8000-0000000000d3"),
            source_document_id="another_paper_2026",
            ordinal=1,
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).add_instance(extra)
        with session_scope(engine) as session:
            listed = QuestionCoreRepository(session).list_instances(
                aggregate.identity.question_id
            )
        assert len(listed) == 3
