"""Task C: Candidate idempotency key = (idempotency_key, adapter_version).

Semantics: results of DIFFERENT adapter versions coexist (upgrade
traceability); the same (key, version) pair is rejected.  adapter_version
is NOT NULL at the database, so the PostgreSQL NULL-inequality quirk
cannot occur - a NULL version insert is rejected outright.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text

from question_core.persistence import (
    DuplicateCandidateError,
    NotFoundError,
    QuestionCoreRepository,
    session_scope,
)
from question_core.persistence.models import CandidateRow

from tests.persistence.synthetic import make_preprocessing_candidate

pytestmark = pytest.mark.pg


def _candidate_with_version(
    adapter_version: str,
    *,
    candidate_id: str,
    run_id: str,
    doc_id: str = "synthetic_doc_pre",
):
    cand = make_preprocessing_candidate(
        candidate_id=UUID(candidate_id), doc_id=doc_id
    )
    ingestion = cand.core.ingestion
    from question_core.contracts.v1 import IngestionIdentity

    new_ingestion = IngestionIdentity(
        candidate_idempotency_key=ingestion.candidate_idempotency_key,
        ingestion_run_id=UUID(run_id),
        adapter_version=adapter_version,
        input_hashes=ingestion.input_hashes,
        ingested_at=ingestion.ingested_at,
    )
    core = cand.core.model_validate(
        {**cand.core.model_dump(mode="json"), "ingestion": new_ingestion.model_dump(mode="json")}
    )
    return type(cand).model_validate(
        {**cand.model_dump(mode="json"), "core": core.model_dump(mode="json")}
    )


class TestIdempotencyKeyVersioning:
    def test_same_key_same_version_rejected(self, engine, clean_db):
        first = _candidate_with_version(
            "strict-adapter/0.1.0",
            candidate_id="00000000-0000-4000-8000-000000000101",
            run_id="00000000-0000-4000-8000-000000000201",
        )
        twin = _candidate_with_version(
            "strict-adapter/0.1.0",
            candidate_id="00000000-0000-4000-8000-000000000102",
            run_id="00000000-0000-4000-8000-000000000202",
        )
        assert (
            first.core.ingestion.candidate_idempotency_key
            == twin.core.ingestion.candidate_idempotency_key
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_candidate(first)
        with pytest.raises(DuplicateCandidateError):
            with session_scope(engine) as session:
                QuestionCoreRepository(session).save_candidate(twin)

    def test_same_key_different_version_allowed(self, engine, clean_db):
        v1 = _candidate_with_version(
            "strict-adapter/0.1.0",
            candidate_id="00000000-0000-4000-8000-000000000101",
            run_id="00000000-0000-4000-8000-000000000201",
        )
        v2 = _candidate_with_version(
            "strict-adapter/0.2.0",
            candidate_id="00000000-0000-4000-8000-000000000102",
            run_id="00000000-0000-4000-8000-000000000202",
        )
        key = v1.core.ingestion.candidate_idempotency_key
        assert key == v2.core.ingestion.candidate_idempotency_key
        assert (
            v1.core.ingestion.ingestion_run_id
            != v2.core.ingestion.ingestion_run_id
        )

        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_candidate(v1)
            QuestionCoreRepository(session).save_candidate(v2)

        with session_scope(engine) as session:
            rows = session.query(CandidateRow).filter_by(
                idempotency_key=key
            ).all()
        assert len(rows) == 2
        assert {r.adapter_version for r in rows} == {
            "strict-adapter/0.1.0",
            "strict-adapter/0.2.0",
        }

    def test_new_version_does_not_overwrite_old(self, engine, clean_db):
        v1 = _candidate_with_version(
            "strict-adapter/0.1.0",
            candidate_id="00000000-0000-4000-8000-000000000101",
            run_id="00000000-0000-4000-8000-000000000201",
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_candidate(v1)
        v2 = _candidate_with_version(
            "strict-adapter/0.2.0",
            candidate_id="00000000-0000-4000-8000-000000000102",
            run_id="00000000-0000-4000-8000-000000000202",
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_candidate(v2)
            restored_v1 = QuestionCoreRepository(session).get_candidate(
                v1.core.candidate_id
            )
        assert restored_v1 == v1  # untouched by the newer version
        assert restored_v1.core.ingestion.adapter_version == "strict-adapter/0.1.0"

    def test_query_distinguishes_versions(self, engine, clean_db):
        v1 = _candidate_with_version(
            "strict-adapter/0.1.0",
            candidate_id="00000000-0000-4000-8000-000000000101",
            run_id="00000000-0000-4000-8000-000000000201",
        )
        v2 = _candidate_with_version(
            "strict-adapter/0.2.0",
            candidate_id="00000000-0000-4000-8000-000000000102",
            run_id="00000000-0000-4000-8000-000000000202",
        )
        key = v1.core.ingestion.candidate_idempotency_key
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            repo.save_candidate(v1)
            repo.save_candidate(v2)
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            assert (
                repo.get_candidate_by_key(key, "strict-adapter/0.1.0") == v1
            )
            assert (
                repo.get_candidate_by_key(key, "strict-adapter/0.2.0") == v2
            )
            with pytest.raises(NotFoundError):
                repo.get_candidate_by_key(key, "strict-adapter/9.9.9")

    def test_adapter_version_null_rejected_by_database(self, engine, clean_db):
        """Explicit NULL policy: adapter_version is NOT NULL at the
        database (the contract requires a non-empty version), so a NULL
        can never enter the unique key and PostgreSQL's NULL-inequality
        semantics never apply."""
        import uuid as uuid_mod

        with pytest.raises(Exception) as exc:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO qcore_candidates (candidate_id, "
                        "source_type, idempotency_key, question_type, "
                        "completeness, ingestion_run_id, adapter_version, "
                        "payload, contract_created_at) VALUES "
                        "(:cid, 'preprocessing', 'qk1_null_version_test', "
                        "'single_choice', 'incomplete', :rid, NULL, "
                        "'{}'::jsonb, now())"
                    ),
                    {"cid": uuid_mod.uuid4(), "rid": uuid_mod.uuid4()},
                )
        assert "not-null" in str(exc.value).lower() or "null" in str(
            exc.value
        ).lower()

    def test_unique_constraint_matches_repository_behavior(
        self, engine, clean_db
    ):
        """The duplicate rejection is enforced by the database unique
        constraint (not by a python-only check): inserting the same
        (key, version) via raw SQL also fails."""
        first = _candidate_with_version(
            "strict-adapter/0.1.0",
            candidate_id="00000000-0000-4000-8000-000000000101",
            run_id="00000000-0000-4000-8000-000000000201",
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_candidate(first)
        key = first.core.ingestion.candidate_idempotency_key
        with pytest.raises(Exception) as exc:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO qcore_candidates (candidate_id, "
                        "source_type, idempotency_key, question_type, "
                        "completeness, ingestion_run_id, adapter_version, "
                        "payload, contract_created_at) VALUES "
                        "(:cid, 'preprocessing', :key, 'single_choice', "
                        "'incomplete', :rid, 'strict-adapter/0.1.0', "
                        "'{}'::jsonb, now())"
                    ),
                    {
                        "cid": __import__("uuid").uuid4(),
                        "key": key,
                        "rid": __import__("uuid").uuid4(),
                    },
                )
        assert "uq_candidate_key_version" in str(exc.value)

    def test_different_source_gets_different_key(self, engine, clean_db):
        a = make_preprocessing_candidate(
            candidate_id=UUID("00000000-0000-4000-8000-000000000111"),
            doc_id="synthetic_doc_pre_a",
        )
        b = make_preprocessing_candidate(
            candidate_id=UUID("00000000-0000-4000-8000-000000000112"),
            doc_id="synthetic_doc_pre_b",
        )
        assert (
            a.core.ingestion.candidate_idempotency_key
            != b.core.ingestion.candidate_idempotency_key
        )
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            repo.save_candidate(a)
            repo.save_candidate(b)
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            assert (
                repo.get_candidate_by_key(
                    a.core.ingestion.candidate_idempotency_key,
                    "strict-adapter/0.1.0",
                )
                == a
            )
