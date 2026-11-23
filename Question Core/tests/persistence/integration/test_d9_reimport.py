"""D9 C1/C2 regression on real PostgreSQL.

C1 — revision publication-state consistency (Owner D2-A):
  changing content appends a Revision and the superseded Revision leaves the
  published state; while the new one is unpublished the question is not
  servable, and after it is published ``published_revision()`` returns it.

C2 — logical paper-segment isolation:
  identity resolution (exact and section-drift fallback) is confined to one
  ``paper_segment_id``; a question number in segment A can never be reused by
  segment B, and a missing segment fails closed.

Every write happens in the dedicated test database; the production database is
never touched by this module.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from question_core.contracts.v1 import (
    Completeness,
    PreprocessingCandidate,
    QuestionAggregate,
    ReviewState,
    Revision,
    StateSnapshot,
    approve_revision,
    canonical_content_hash,
    publish_revision,
)
from question_core.persistence import QuestionCoreRepository, session_scope
from question_core.persistence.identity_resolve import AmbiguousIdentityError
from question_core.persistence.models import QuestionRow
from strict_adapter.ingest import persist_mapping
from tests.persistence.synthetic import (
    make_identity,
    make_instance,
    make_preprocessing_candidate,
    make_rich_revision,
)

PAPER = "synthetic_paper_2026"
SECTION = "第二部分"


def _anchor(segment: str = PAPER, section: str = SECTION, numbers=(12,)) -> dict:
    return {
        "paper_segment_id": segment,
        "section_id": f"{section}#1",
        "question_numbers": list(numbers),
        "source_hash": "a" * 64,
    }


def _candidate_with_key(key: str):
    data = make_preprocessing_candidate().model_dump(mode="json")
    data["core"]["candidate_id"] = str(uuid4())
    data["core"]["ingestion"]["candidate_idempotency_key"] = key
    return PreprocessingCandidate.model_validate(data)


def _aggregate(
    *,
    drop: int = 0,
    qid=None,
    segment: str = PAPER,
    section: str = SECTION,
    complete: bool = False,
) -> QuestionAggregate:
    identity = make_identity(qid) if qid else make_identity()
    question_id = identity.question_id
    base = make_rich_revision(question_id, revision_number=1)
    answers = base.answers[: len(base.answers) - drop] if drop else base.answers
    revision_id = uuid4()
    snapshot = None
    if complete:
        snapshot = StateSnapshot(
            revision_id=revision_id,
            content_hash=canonical_content_hash(
                base.content, *answers, *base.explanation_blocks
            ),
            completeness=Completeness.COMPLETE,
            review=ReviewState.PENDING_REVIEW,
        )
    revision = Revision.create(
        question_id=question_id,
        revision_id=revision_id,
        revision_number=1,
        question_type=base.question_type,
        content=base.content,
        answers=answers,
        explanation_blocks=base.explanation_blocks,
        evidence=base.evidence,
        created_by="d9-test",
        state=snapshot,
    )
    instance = make_instance(
        question_id,
        revision.revision_id,
        instance_id=uuid4(),
        source_document_id=PAPER,
        ordinal=1,
    )
    instance = instance.model_copy(update={})
    # segment is immutable on the contract only via validation; build via dump.
    return QuestionAggregate(
        identity=identity,
        revisions=(revision,),
        instances=(_with_segment(instance, segment, section),),
        state_history=(),
    )


def _with_segment(instance, segment: str, section: str):
    from question_core.contracts.v1 import QuestionInstance

    data = instance.model_dump(mode="json")
    data["paper_segment_id"] = segment
    data["section"] = section
    return QuestionInstance.model_validate(data)


def _mapping(candidate, anchor=None):
    return SimpleNamespace(
        unit_id="unit-12", candidate=candidate, identity_anchor=anchor or _anchor()
    )


def _admission(aggregate):
    return SimpleNamespace(
        aggregate=aggregate, question_id=str(aggregate.identity.question_id)
    )


def _question_count(repo) -> int:
    return repo.session.execute(select(func.count()).select_from(QuestionRow)).scalar_one()


def _latest_published(repo, question_id):
    return repo.get_question_aggregate(question_id).published_revision()


def _publish_revision(repo, question_id, revision_id):
    agg = repo.get_question_aggregate(question_id)
    revision = next(r for r in agg.revisions if r.revision_id == revision_id)
    approved = approve_revision(
        revision.state,
        approved_by="mimo-review",
        content_hash=revision.content_hash,
    )
    published = publish_revision(
        approved, acted_by="mimo-review", content_hash=revision.content_hash
    )
    repo.append_state_snapshot(question_id, published)


# ---------------------------------------------------------------------------
# C1
# ---------------------------------------------------------------------------


def test_published_rev1_is_retired_when_content_changes(engine, clean_db):
    first = _aggregate(complete=True)
    qid = first.identity.question_id
    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        repo.save_candidate_with_question(_candidate_with_key("qk2_" + "1" * 40), first)
        _publish_revision(repo, qid, first.revisions[0].revision_id)
        assert _latest_published(repo, qid).revision_id == first.revisions[0].revision_id

    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        record = persist_mapping(
            repo,
            _mapping(_candidate_with_key("qk2_" + "2" * 40)),
            _admission(_aggregate(drop=1, qid=qid, complete=True)),
            paper_id=PAPER,
        )
        assert record["persist"] == "revision_added"
        assert record.get("retired_revision_id") == str(first.revisions[0].revision_id)
        assert _latest_published(repo, qid) is None

    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        agg = repo.get_question_aggregate(qid)
        assert len(agg.revisions) == 2
        latest = max(agg.revisions, key=lambda r: r.revision_number)
        assert latest.state.publication == "unpublished"
        # history is intact: the old revision is withdrawn, not deleted
        by_rev = {}
        for snap in agg.state_history:
            by_rev[snap.revision_id] = snap
        assert by_rev[first.revisions[0].revision_id].publication == "withdrawn"


def test_publishing_rev2_makes_it_the_current_revision(engine, clean_db):
    first = _aggregate(complete=True)
    qid = first.identity.question_id
    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        repo.save_candidate_with_question(_candidate_with_key("qk2_" + "3" * 40), first)
        _publish_revision(repo, qid, first.revisions[0].revision_id)

    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        persist_mapping(
            repo,
            _mapping(_candidate_with_key("qk2_" + "4" * 40)),
            _admission(_aggregate(drop=1, qid=qid, complete=True)),
            paper_id=PAPER,
        )

    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        agg = repo.get_question_aggregate(qid)
        rev2 = max(agg.revisions, key=lambda r: r.revision_number)
        _publish_revision(repo, qid, rev2.revision_id)
        published = _latest_published(repo, qid)
        assert published is not None and published.revision_id == rev2.revision_id


def test_same_content_reimport_keeps_revision_published(engine, clean_db):
    first = _aggregate(complete=True)
    qid = first.identity.question_id
    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        repo.save_candidate_with_question(_candidate_with_key("qk2_" + "5" * 40), first)
        _publish_revision(repo, qid, first.revisions[0].revision_id)

    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        record = persist_mapping(
            repo,
            _mapping(_candidate_with_key("qk2_" + "6" * 40)),
            _admission(_aggregate(qid=qid, complete=True)),
            paper_id=PAPER,
        )
        assert record["persist"] == "skipped_duplicate"
        published = _latest_published(repo, qid)
        assert published is not None
        assert published.revision_id == first.revisions[0].revision_id
        assert len(repo.get_question_aggregate(qid).revisions) == 1


def test_repeated_content_changes_keep_only_current_published_version(engine, clean_db):
    first = _aggregate(complete=True)
    qid = first.identity.question_id
    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        repo.save_candidate_with_question(_candidate_with_key("qk2_" + "7" * 40), first)
        _publish_revision(repo, qid, first.revisions[0].revision_id)

    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        for key_char, drop in (("8", 1), ("9", 2)):
            persist_mapping(
                repo,
                _mapping(_candidate_with_key("qk2_" + key_char * 40)),
                _admission(_aggregate(drop=drop, qid=qid, complete=True)),
                paper_id=PAPER,
            )
        agg = repo.get_question_aggregate(qid)
        assert [r.revision_number for r in agg.revisions] == [1, 2, 3]
        assert _latest_published(repo, qid) is None
        by_rev = {s.revision_id: s for s in agg.state_history}
        assert by_rev[first.revisions[0].revision_id].publication == "withdrawn"


def test_failure_while_appending_rolls_back_everything(engine, clean_db):
    first = _aggregate(complete=True)
    qid = first.identity.question_id
    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        repo.save_candidate_with_question(_candidate_with_key("qk2_" + "a" * 40), first)
        _publish_revision(repo, qid, first.revisions[0].revision_id)

    calls = {"n": 0}
    real_append = QuestionCoreRepository.append_state_snapshot

    def flaky(self, question_id, snapshot):
        calls["n"] += 1
        if calls["n"] == 2:  # second append = the new revision snapshot
            raise RuntimeError("injected failure while appending state")
        return real_append(self, question_id, snapshot)

    def run_import():
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            repo.append_state_snapshot = flaky.__get__(repo, type(repo))
            persist_mapping(
                repo,
                _mapping(_candidate_with_key("qk2_" + "b" * 40)),
                _admission(_aggregate(drop=1, qid=qid, complete=True)),
                paper_id=PAPER,
            )

    # The exception must escape session_scope so the transaction rolls back.
    with pytest.raises(RuntimeError):
        run_import()

    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        agg = repo.get_question_aggregate(qid)
        assert len(agg.revisions) == 1, "transaction must roll back the appended revision"
        assert _latest_published(repo, qid).revision_id == first.revisions[0].revision_id


# ---------------------------------------------------------------------------
# C2
# ---------------------------------------------------------------------------


def test_same_number_in_two_segments_stays_independent(engine, clean_db):
    seg_a, seg_b = "paper-1/segA", "paper-1/segB"
    qa = _aggregate(segment=seg_a)
    qb = _aggregate(qid=uuid4(), segment=seg_b)
    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        repo.save_candidate_with_question(_candidate_with_key("qk2_" + "c" * 40), qa)
        repo.save_candidate_with_question(_candidate_with_key("qk2_" + "d" * 40), qb)

    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        record = persist_mapping(
            repo,
            _mapping(_candidate_with_key("qk2_" + "e" * 40), _anchor(segment=seg_b)),
            _admission(_aggregate(segment=seg_b)),
            paper_id=PAPER,
        )
        assert record["persist"] == "skipped_duplicate"
        assert record["question_id"] == str(qb.identity.question_id)
        assert _question_count(repo) == 2


def test_cross_segment_section_drift_cannot_reuse(engine, clean_db):
    """MIMO's counterexample, verified through the real DB query chain."""
    seg_a, seg_b = "paper-1/segA", "paper-1/segB"
    qa = _aggregate(qid=uuid4(), segment=seg_a, section="第一部分")
    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        repo.save_candidate_with_question(_candidate_with_key("qk2_" + "f" * 40), qa)

    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        # incoming: segment B, same question numbers, drifted section label
        record = persist_mapping(
            repo,
            _mapping(
                _candidate_with_key("qk2_" + "g" * 40),
                _anchor(segment=seg_b, section="完全不同的段名"),
            ),
            _admission(_aggregate(segment=seg_b, section="完全不同的段名")),
            paper_id=PAPER,
        )
        assert record["persist"] == "committed_new", "must not reuse segment A"
        assert record["question_id"] != str(qa.identity.question_id)
        assert _question_count(repo) == 2


def test_legacy_instance_without_segment_matches_only_single_segment_default(engine, clean_db):
    first = _aggregate(segment=PAPER)  # contract stores the paper id as segment
    legacy = first.instances[0].model_dump(mode="json")
    legacy["paper_segment_id"] = None
    from question_core.contracts.v1 import QuestionInstance

    first = first.model_copy(update={})
    # rebuild the aggregate with a legacy instance (no segment stored)
    first = QuestionAggregate(
        identity=first.identity,
        revisions=first.revisions,
        instances=(QuestionInstance.model_validate(legacy),),
        state_history=(),
    )
    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        repo.save_candidate_with_question(_candidate_with_key("qk2_" + "h" * 40), first)

    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        # single-segment default == paper id -> legacy row is eligible
        same = persist_mapping(
            repo,
            _mapping(_candidate_with_key("qk2_" + "i" * 40)),
            _admission(_aggregate(qid=first.identity.question_id)),
            paper_id=PAPER,
        )
        assert same["persist"] == "skipped_duplicate"

        # a multi-segment anchor must NOT attach the legacy row to a segment
        other = persist_mapping(
            repo,
            _mapping(
                _candidate_with_key("qk2_" + "j" * 40),
                _anchor(segment="paper-1/听力A"),
            ),
            _admission(_aggregate(qid=uuid4(), segment="paper-1/听力A")),
            paper_id=PAPER,
        )
        assert other["persist"] == "committed_new"
        assert _question_count(repo) == 2


def test_duplicate_question_numbers_inside_one_segment_fail_closed(engine, clean_db):
    first = _aggregate(segment=PAPER)
    twin = _aggregate(qid=uuid4(), segment=PAPER)
    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        repo.save_candidate_with_question(_candidate_with_key("qk2_" + "k" * 40), first)
        repo.save_candidate_with_question(_candidate_with_key("qk2_" + "l" * 40), twin)
        assert _question_count(repo) == 2

    with session_scope(engine) as session:
        repo = QuestionCoreRepository(session)
        with pytest.raises(AmbiguousIdentityError):
            persist_mapping(
                repo,
                _mapping(_candidate_with_key("qk2_" + "m" * 40)),
                _admission(_aggregate()),
                paper_id=PAPER,
            )
        assert _question_count(repo) == 2
