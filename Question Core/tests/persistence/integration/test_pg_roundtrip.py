"""Real PostgreSQL round-trip tests: write → read → contract revalidation.

Every read path restores the exact contract object and re-runs its
validators; equality against the pre-write object is the consistency proof.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from question_core.contracts.v1 import canonical_content_hash, QuestionAggregate
from question_core.persistence import (
    NotFoundError,
    QuestionCoreRepository,
    health_check,
    session_scope,
)
from question_core.persistence.serialize import dump_contract

from tests.golden_samples import (
    build_preprocessing_candidate,
    build_question_aggregate,
    build_student_upload_candidate,
)
from tests.persistence.synthetic import (
    make_all_answers,
    make_identity,
    make_instance,
    make_preprocessing_candidate,
    make_published_revision,
    make_rich_aggregate,
    make_rich_revision,
    make_single_answer_revision,
    make_student_upload_candidate,
)

pytestmark = pytest.mark.pg

QID = UUID("00000000-0000-4000-8000-000000000055")


class TestCandidatePersistence:
    @pytest.mark.parametrize(
        "builder",
        [make_preprocessing_candidate, make_student_upload_candidate],
        ids=["preprocessing", "student_upload"],
    )
    def test_save_and_read_candidate(self, engine, clean_db, builder):
        candidate = builder()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_candidate(candidate)

        with session_scope(engine) as session:
            restored = QuestionCoreRepository(session).get_candidate(
                candidate.core.candidate_id
            )
        assert restored == candidate

    def test_get_candidate_by_idempotency_key(self, engine, clean_db):
        candidate = make_preprocessing_candidate()
        key = candidate.core.ingestion.candidate_idempotency_key
        version = candidate.core.ingestion.adapter_version
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_candidate(candidate)
        with session_scope(engine) as session:
            restored = QuestionCoreRepository(session).get_candidate_by_key(
                key, version
            )
        assert restored == candidate

    def test_missing_candidate_raises(self, engine, clean_db):
        with session_scope(engine) as session:
            with pytest.raises(NotFoundError):
                QuestionCoreRepository(session).get_candidate(
                    UUID("00000000-0000-4000-8000-00000000dead")
                )

    @pytest.mark.parametrize(
        "builder",
        [build_preprocessing_candidate, build_student_upload_candidate],
        ids=["preprocessing", "student_upload"],
    )
    def test_golden_candidate_persist(self, engine, clean_db, builder):
        # the golden builders use fixed UUIDs (digest determinism), so each
        # branch must be persisted against a clean database
        golden = builder()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_candidate(golden)
        with session_scope(engine) as session:
            restored = QuestionCoreRepository(session).get_candidate(
                golden.core.candidate_id
            )
        assert restored == golden
        assert dump_contract(restored) == dump_contract(golden)


class TestQuestionPersistence:
    def test_save_and_read_rich_aggregate(self, engine, clean_db):
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)

        with session_scope(engine) as session:
            restored = QuestionCoreRepository(session).get_question_aggregate(
                aggregate.identity.question_id
            )
        assert restored == aggregate
        assert dump_contract(restored) == dump_contract(aggregate)

    def test_golden_aggregate_persist(self, engine, clean_db):
        aggregate = build_question_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        with session_scope(engine) as session:
            restored = QuestionCoreRepository(session).get_question_aggregate(
                aggregate.identity.question_id
            )
        assert restored == aggregate

    def test_question_identity_read(self, engine, clean_db):
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        with session_scope(engine) as session:
            identity = QuestionCoreRepository(session).get_question_identity(
                aggregate.identity.question_id
            )
        assert identity == aggregate.identity

    def test_revision_read_by_id_and_list(self, engine, clean_db):
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            listed = repo.list_revisions(aggregate.identity.question_id)
            assert [r.revision_number for r in listed] == [1, 2]
            single = repo.get_revision(aggregate.revisions[0].revision_id)
        assert single == aggregate.revisions[0]
        assert listed == aggregate.revisions

    def test_instance_read(self, engine, clean_db):
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            instance = repo.get_instance(
                aggregate.instances[0].instance_id
            )
            listed = repo.list_instances(aggregate.identity.question_id)
        assert instance == aggregate.instances[0]
        assert len(listed) == 2

    def test_missing_question_raises(self, engine, clean_db):
        with session_scope(engine) as session:
            with pytest.raises(NotFoundError):
                QuestionCoreRepository(session).get_question_aggregate(
                    UUID("00000000-0000-4000-8000-00000000dead")
                )


class TestTypedAnswerCoverage:
    @pytest.mark.parametrize(
        "kind",
        [
            "single_choice",
            "multi_choice",
            "fill_blank",
            "composite",
            "multi_step",
            "numeric",
            "expression",
            "chemical",
            "composite_sub",
        ],
    )
    def test_each_typed_answer_survives_postgres(self, engine, clean_db, kind):
        answers = tuple(
            a for a in make_all_answers() if a.answer_type == kind
        )
        revision = make_single_answer_revision(QID, answer=answers)
        aggregate = QuestionAggregate(
            identity=make_identity(QID),
            revisions=(revision,),
            instances=(make_instance(QID, revision.revision_id),),
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        with session_scope(engine) as session:
            restored = QuestionCoreRepository(session).get_revision(
                revision.revision_id
            )
        assert restored == revision
        assert restored.answers[0].answer_type == kind


class TestRichStructureRestore:
    def test_evidence_composite_asset_table_restore(self, engine, clean_db):
        revision = make_rich_revision(QID)
        aggregate = QuestionAggregate(
            identity=make_identity(QID),
            revisions=(revision,),
            instances=(make_instance(QID, revision.revision_id),),
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        with session_scope(engine) as session:
            restored = QuestionCoreRepository(session).get_revision(
                revision.revision_id
            )

        assert restored == revision
        # content hash binding re-verified on read
        assert (
            canonical_content_hash(
                restored.content,
                *restored.answers,
                *restored.explanation_blocks,
            )
            == restored.content_hash
        )
        # Evidence: two records + one critical conflict with full relations
        evidence = restored.evidence
        assert len(evidence.records) == 2
        assert {r.source.source_kind.value for r in evidence.records} == {
            "source_markdown",
            "answer_table",
        }
        conflict = evidence.conflicts[0]
        assert conflict.is_critical is True
        assert set(conflict.evidence_ids) == {
            r.evidence_id for r in evidence.records
        }
        # Composite tree intact
        by_id = {b.local_id: b for b in restored.content.bodies}
        assert by_id["q1"].sub_question_ids == ("q1a", "q1b")
        assert by_id["q1a"].parent_question_ref == "q1"
        # Material + merged-cell table intact
        material = restored.content.materials[0]
        table = material.blocks[1]
        assert table.cells[0].rowspan == 2
        assert table.to_rows() == [["左侧", "右上"], ["左侧", "右下"]]
        # Asset reference intact (ids and pointers only, no media copying)
        asset = restored.content.assets[0]
        assert asset.asset_id == "fig-1"
        assert asset.storage_path == "assets/fig-1.png"
        assert asset.content_hash == "a" * 64

    def test_projection_rows_match_payload(self, engine, clean_db):
        revision = make_rich_revision(QID)
        aggregate = QuestionAggregate(
            identity=make_identity(QID),
            revisions=(revision,),
            instances=(make_instance(QID, revision.revision_id),),
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)

        from sqlalchemy import func, select
        from question_core.persistence.models import (
            AnswerRow,
            AssetRefRow,
            EvidenceConflictRow,
            EvidenceRecordRow,
            MaterialRefRow,
        )

        with session_scope(engine) as session:
            answers = session.execute(
                select(func.count())
                .select_from(AnswerRow)
                .where(AnswerRow.revision_id == revision.revision_id)
            ).scalar()
            records = session.execute(
                select(func.count())
                .select_from(EvidenceRecordRow)
                .where(
                    EvidenceRecordRow.revision_id == revision.revision_id
                )
            ).scalar()
            conflicts = session.execute(
                select(func.count())
                .select_from(EvidenceConflictRow)
                .where(
                    EvidenceConflictRow.revision_id == revision.revision_id
                )
            ).scalar()
            assets = session.execute(
                select(func.count())
                .select_from(AssetRefRow)
                .where(AssetRefRow.revision_id == revision.revision_id)
            ).scalar()
            materials = session.execute(
                select(func.count())
                .select_from(MaterialRefRow)
                .where(MaterialRefRow.revision_id == revision.revision_id)
            ).scalar()
        assert answers == len(revision.answers)
        assert records == 2
        assert conflicts == 1
        assert assets == 1
        assert materials == 1

    def test_published_revision_state_survives(self, engine, clean_db):
        revision = make_published_revision(QID)
        aggregate = QuestionAggregate(
            identity=make_identity(QID),
            revisions=(revision,),
            instances=(make_instance(QID, revision.revision_id),),
            state_history=(revision.state,),
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)
        with session_scope(engine) as session:
            restored = QuestionCoreRepository(session).get_question_aggregate(
                QID
            )
        assert restored == aggregate
        state = restored.revisions[0].state
        assert state.review.value == "approved"
        assert state.publication.value == "published"
        assert state.approval.approved_by == "reviewer-1"
        assert state.publication_record.acted_by == "publisher-1"
        assert restored.state_history == (revision.state,)


class TestCandidateWithQuestion:
    def test_combined_write_both_sides(self, engine, clean_db):
        candidate = make_preprocessing_candidate()
        aggregate = make_rich_aggregate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_candidate_with_question(
                candidate, aggregate
            )
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            assert (
                repo.get_candidate(candidate.core.candidate_id) == candidate
            )
            assert (
                repo.get_question_aggregate(
                    aggregate.identity.question_id
                )
                == aggregate
            )


class TestRestartPersistence:
    def test_data_survives_engine_restart(self, engine, clean_db):
        from question_core.persistence.config import DatabaseSettings
        from question_core.persistence.engine import create_db_engine

        from tests.persistence.integration.conftest import TEST_DATABASE_URL

        aggregate = make_rich_aggregate()
        candidate = make_preprocessing_candidate()
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_candidate_with_question(
                candidate, aggregate
            )

        engine.dispose()  # "restart": drop every pooled connection

        settings = DatabaseSettings.from_env(
            {"QCORE_DATABASE_URL": TEST_DATABASE_URL}
        )
        fresh = create_db_engine(settings)
        try:
            report = health_check(fresh)
            assert report["status"] == "ok"
            with session_scope(fresh) as session:
                repo = QuestionCoreRepository(session)
                assert (
                    repo.get_candidate(candidate.core.candidate_id)
                    == candidate
                )
                assert (
                    repo.get_question_aggregate(
                        aggregate.identity.question_id
                    )
                    == aggregate
                )
        finally:
            fresh.dispose()


class TestHealthCheck:
    def test_health_check_reports_database(self, engine):
        report = health_check(engine)
        assert report["status"] == "ok"
        assert report["database"].startswith("qcore_")
        assert "PostgreSQL" in report["server_version"]
