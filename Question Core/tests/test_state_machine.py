"""Three-dimensional state model: the nine rules from the direction document."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from question_core.contracts.v1 import (
    Completeness,
    PublicationState,
    ReviewState,
    StateSnapshot,
    approve_revision,
    check_single_published,
    new_revision,
    publish_revision,
    withdraw_publication,
)

_HASH_A = "a" * 64
_HASH_B = "b" * 64


def _snap(**kw):
    rid = kw.pop("revision_id", uuid.uuid4())
    ch = kw.pop("content_hash", _HASH_A)
    return StateSnapshot(revision_id=rid, content_hash=ch, **kw)


def _pending(**kw):
    """Snapshot already in ``pending_review`` — the state a reviewer
    actually approves from. Rule: NOT_READY must pass through
    PENDING_REVIEW before approval."""
    kw.setdefault("completeness", Completeness.COMPLETE)
    return _snap(review=ReviewState.PENDING_REVIEW, **kw)


def _approved(**kw):
    ch = kw.pop("content_hash", _HASH_A)
    rid = kw.pop("revision_id", uuid.uuid4())
    snap = _pending(revision_id=rid, content_hash=ch, **kw)
    return approve_revision(snap, approved_by="reviewer:X", content_hash=ch)


def _published(**kw):
    ch = kw.pop("content_hash", _HASH_A)
    rid = kw.pop("revision_id", uuid.uuid4())
    snap = _approved(revision_id=rid, content_hash=ch, **kw)
    return publish_revision(snap, acted_by="publisher", content_hash=ch)


class TestReviewPath:
    def test_not_ready_cannot_go_straight_to_approved(self):
        snap = _snap(completeness=Completeness.COMPLETE)
        assert snap.can_transition_review(ReviewState.APPROVED) is False

    def test_not_ready_to_pending_review(self):
        snap = _snap(completeness=Completeness.COMPLETE)
        assert snap.can_transition_review(ReviewState.PENDING_REVIEW) is True

    def test_pending_review_allows_approval_when_complete(self):
        snap = _pending()
        assert snap.can_transition_review(ReviewState.APPROVED) is True


class TestRule1IncompleteNeverApproved:
    def test_model_rejects_incomplete_approved(self):
        with pytest.raises(ValidationError, match="incomplete"):
            _snap(
                completeness=Completeness.INCOMPLETE,
                review=ReviewState.APPROVED,
                approval=None,
            )

    def test_transition_refused_when_incomplete(self):
        snap = _snap(
            completeness=Completeness.INCOMPLETE,
            review=ReviewState.PENDING_REVIEW,
        )
        assert snap.can_transition_review(ReviewState.APPROVED) is False

    def test_complete_allows_approval(self):
        snap = _pending(completeness=Completeness.COMPLETE)
        assert snap.can_transition_review(ReviewState.APPROVED) is True


class TestRule2ApprovedIsNotPublished:
    def test_approved_stays_unpublished(self):
        approved = _approved()
        assert approved.review == ReviewState.APPROVED
        assert approved.publication == PublicationState.UNPUBLISHED


class TestRule3RejectedNeverPublished:
    def test_model_rejects_rejected_published(self):
        from question_core.contracts.v1 import PublicationRecord

        rid, ch = uuid.uuid4(), _HASH_A
        with pytest.raises(ValidationError, match="rejected"):
            StateSnapshot(
                revision_id=rid,
                content_hash=ch,
                completeness=Completeness.COMPLETE,
                review=ReviewState.REJECTED,
                publication=PublicationState.PUBLISHED,
                publication_record=PublicationRecord(
                    revision_id=rid,
                    content_hash=ch,
                    state=PublicationState.PUBLISHED,
                    acted_by="x",
                ),
            )


class TestRule4ContentChangeMakesNewRevision:
    def test_new_revision_requires_hash_change(self):
        snap = _snap()
        with pytest.raises(ValueError, match="must change content_hash"):
            new_revision(snap, revision_id=uuid.uuid4(), content_hash=_HASH_A)

    def test_new_revision_starts_clean(self):
        approved = _approved()
        nxt = new_revision(approved, revision_id=uuid.uuid4(), content_hash=_HASH_B)
        assert nxt.review == ReviewState.NOT_READY
        assert nxt.approval is None
        assert nxt.publication == PublicationState.UNPUBLISHED


class TestRule5ApprovalBindsRevisionAndHash:
    def test_approve_wrong_hash_refused(self):
        snap = _pending()
        with pytest.raises(ValueError, match="content_hash does not match"):
            approve_revision(snap, approved_by="r", content_hash=_HASH_B)

    def test_approval_record_carries_both(self):
        rid, ch = uuid.uuid4(), _HASH_A
        approved = _approved(revision_id=rid, content_hash=ch)
        assert approved.approval.revision_id == rid
        assert approved.approval.content_hash == ch

    def test_model_rejects_mismatched_approval(self):
        from question_core.contracts.v1 import ApprovalRecord

        rid, ch = uuid.uuid4(), _HASH_A
        with pytest.raises(ValidationError, match="must bind this"):
            StateSnapshot(
                revision_id=rid,
                content_hash=ch,
                completeness=Completeness.COMPLETE,
                review=ReviewState.APPROVED,
                approval=ApprovalRecord(
                    revision_id=uuid.uuid4(),
                    content_hash=ch,
                    approved_by="x",
                ),
            )

    def test_approved_without_record_rejected(self):
        with pytest.raises(ValidationError, match="requires an ApprovalRecord"):
            _snap(
                completeness=Completeness.COMPLETE,
                review=ReviewState.APPROVED,
            )


class TestRule6PublicationBindsRevisionAndHash:
    def test_publish_wrong_hash_refused(self):
        approved = _approved()
        with pytest.raises(ValueError, match="content_hash does not match"):
            publish_revision(approved, acted_by="r", content_hash=_HASH_B)

    def test_publication_record_carries_both(self):
        rid, ch = uuid.uuid4(), _HASH_A
        published = _published(revision_id=rid, content_hash=ch)
        assert published.publication_record.revision_id == rid
        assert published.publication_record.content_hash == ch


class TestRule7NewRevisionDoesNotInheritApproval:
    def test_inheritance_blocked(self):
        approved = _approved()
        nxt = new_revision(approved, revision_id=uuid.uuid4(), content_hash=_HASH_B)
        assert nxt.approval is None
        assert nxt.review == ReviewState.NOT_READY


class TestRule8SinglePublishedRevision:
    def test_two_published_rejected(self):
        snaps = [_published(), _published()]
        with pytest.raises(ValueError, match="multiple published"):
            check_single_published(snaps)

    def test_published_plus_withdrawn_ok(self):
        rid, ch = uuid.uuid4(), _HASH_A
        s = _published(revision_id=rid, content_hash=ch)
        s = withdraw_publication(s, acted_by="p", content_hash=ch)
        check_single_published([s])

    def test_aggregate_enforces_single_published(self, contract):
        qid = uuid.uuid4()
        rid1, rid2 = uuid.uuid4(), uuid.uuid4()

        def mk(rid, number):
            return contract.Revision.create(
                revision_id=rid,
                question_id=qid,
                revision_number=number,
                question_type="numeric",
                content=contract.QuestionContent(
                    bodies=[
                        contract.QuestionBody(
                            local_id="q",
                            question_type="numeric",
                            stem_blocks=[contract.TextBlock(text="x")],
                        )
                    ]
                ),
            )

        revs = [mk(rid1, 1), mk(rid2, 2)]
        states = [
            _published(revision_id=rid1, content_hash=revs[0].content_hash),
            _published(revision_id=rid2, content_hash=revs[1].content_hash),
        ]
        for i, (rev, st) in enumerate(zip(revs, states)):
            d = rev.model_dump(mode="json")
            d["state"] = st.model_dump(mode="json")
            revs[i] = contract.Revision.model_validate(d)
        with pytest.raises(ValidationError, match="multiple published"):
            contract.QuestionAggregate(
                identity=contract.QuestionIdentity(question_id=qid),
                revisions=revs,
            )


class TestRule9HistoryPreserved:
    def test_history_carries_every_event(self):
        rid, ch = uuid.uuid4(), _HASH_A
        snap = _pending(revision_id=rid, content_hash=ch)
        approved = approve_revision(
            snap, approved_by="r1", content_hash=ch, note="first"
        )
        published = publish_revision(
            approved, acted_by="p1", content_hash=ch, note="go"
        )
        withdrawn = withdraw_publication(
            published, acted_by="p1", content_hash=ch, note="back"
        )
        assert approved.approval is not None
        assert published.publication_record is not None
        assert withdrawn.publication_record.state == PublicationState.WITHDRAWN

    def test_snapshot_copy_does_not_mutate_original(self):
        snap = _pending()
        approved = approve_revision(snap, approved_by="r", content_hash=snap.content_hash)
        assert snap.review == ReviewState.PENDING_REVIEW, "original unchanged"
        assert approved.review == ReviewState.APPROVED


class TestUnpublishedIsNotUnreadable:
    def test_review_only_visibility_is_independent_of_publication(self, contract):
        """An unpublished candidate carries full content for reviewers."""
        cand = contract.PreprocessingCandidate(
            core=contract.CandidateCore(
                question_type="single_choice",
                content=contract.QuestionContent(
                    bodies=[
                        contract.QuestionBody(
                            local_id="q",
                            question_type="single_choice",
                            stem_blocks=[contract.TextBlock(text="完整题干")],
                            options=[
                                contract.OptionItem(
                                    label="A",
                                    blocks=[contract.TextBlock(text="甲")],
                                ),
                            ],
                        )
                    ]
                ),
                answers=[
                    contract.SingleChoiceAnswer(
                        answer_value="A",
                        visibility="review_only",
                        completeness="full",
                    )
                ],
                completeness=Completeness.COMPLETE,
                ingestion=contract.IngestionIdentity(
                    candidate_idempotency_key="k" * 20,
                    adapter_version="a/1",
                    input_hashes=contract.InputHashes(manifest_hash="a" * 64),
                ),
                content_visibility=contract.Visibility.REVIEW_ONLY,
            ),
            source=contract.PreprocessingSource(
                source_document_id="doc/1",
                manifest_ref=contract.SourceDocumentRef(
                    doc_role="manifest", content_hash="a" * 64
                ),
                unit=contract.PreprocessingUnitRef(
                    unit_id="Q1",
                    unit_type="standalone_question",
                ),
                answer_declaration=contract.StrictAnswerDeclaration(
                    attribution="declared",
                    evidence_kind="answer_lines",
                    declared_value="A",
                    completeness="complete",
                ),
            ),
        )
        assert cand.core.answers[0].answer_value == "A"
        assert cand.core.answer_visibility == contract.Visibility.REVIEW_ONLY
