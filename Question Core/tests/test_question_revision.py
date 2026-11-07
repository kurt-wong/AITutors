"""Question identity, Revision versioning and Instance separation."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from question_core.contracts.v1 import (
    Completeness,
    QuestionAggregate,
    QuestionBody,
    QuestionContent,
    QuestionIdentity,
    QuestionInstance,
    QuestionType,
    Revision,
    StateSnapshot,
    TextBlock,
)

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


def _content(text="题干"):
    return QuestionContent(
        bodies=[
            QuestionBody(
                local_id="q",
                question_type=QuestionType.SHORT_ANSWER,
                stem_blocks=[TextBlock(text=text)],
            )
        ]
    )


def _revision(qid, rid, number, ch, content=None):
    return Revision.create(
        revision_id=rid,
        question_id=qid,
        revision_number=number,
        question_type=QuestionType.SHORT_ANSWER,
        content=content or _content(),
    )


class TestIdentitySeparation:
    def test_question_id_is_uuid_not_content_hash(self, contract):
        ident = QuestionIdentity(identity_fingerprint="fp-abcdef")
        assert isinstance(ident.question_id, uuid.UUID)

    def test_fingerprint_differs_from_content_hash(self, contract):
        """Fingerprint is for matching; content_hash is for integrity. They
        are separate fields and neither may stand in for question_id."""
        ident = QuestionIdentity(identity_fingerprint="fp-same-xx")
        rev = Revision.create(
            revision_id=uuid.uuid4(),
            question_id=ident.question_id,
            revision_number=1,
            question_type=QuestionType.SHORT_ANSWER,
            content=_content(),
        )
        assert ident.identity_fingerprint != rev.content_hash

    def test_same_fingerprint_does_not_merge_automatically(self, contract):
        """Two questions with equal fingerprints are merge *candidates*, not
        one question. The contract keeps them separate."""
        q1 = QuestionIdentity(identity_fingerprint="fp-dup-xxx")
        q2 = QuestionIdentity(identity_fingerprint="fp-dup-xxx")
        assert q1.question_id != q2.question_id

    def test_content_hash_is_not_question_id(self, contract):
        with pytest.raises(ValidationError):
            QuestionIdentity.model_validate(
                {"question_id": _HASH_A}  # 64-hex is not a UUID
            )


class TestRevisionVersioning:
    def test_new_content_makes_new_revision(self, contract):
        qid = uuid.uuid4()
        r1 = _revision(qid, uuid.uuid4(), 1, _HASH_A)
        r2 = _revision(qid, uuid.uuid4(), 2, _HASH_B, _content("修正后的题干"))
        agg = QuestionAggregate(
            identity=QuestionIdentity(question_id=qid), revisions=[r1, r2]
        )
        assert agg.current_revision().revision_number == 2

    def test_duplicate_revision_number_rejected(self, contract):
        qid = uuid.uuid4()
        r1 = _revision(qid, uuid.uuid4(), 1, _HASH_A)
        r2 = _revision(qid, uuid.uuid4(), 1, _HASH_B)
        with pytest.raises(ValidationError, match="revision_number must be unique"):
            QuestionAggregate(
                identity=QuestionIdentity(question_id=qid), revisions=[r1, r2]
            )

    def test_revision_must_belong_to_question(self, contract):
        qid = uuid.uuid4()
        r1 = Revision.create(
            revision_id=uuid.uuid4(),
            question_id=uuid.uuid4(),  # different question!
            revision_number=1,
            question_type=QuestionType.SHORT_ANSWER,
            content=_content(),
        )
        with pytest.raises(ValidationError, match="must match identity"):
            QuestionAggregate(
                identity=QuestionIdentity(question_id=qid), revisions=[r1]
            )

    def test_state_binding_enforced(self, contract):
        qid = uuid.uuid4()
        rid = uuid.uuid4()
        content = _content()
        # Build a valid revision first to learn the correct content_hash.
        good = Revision.create(
            revision_id=rid,
            question_id=qid,
            revision_number=1,
            question_type=QuestionType.SHORT_ANSWER,
            content=content,
        )
        bad_state = StateSnapshot(
            revision_id=uuid.uuid4(), content_hash=good.content_hash
        )
        with pytest.raises(ValidationError, match="state.revision_id"):
            Revision(
                revision_id=rid,
                question_id=qid,
                revision_number=1,
                content_hash=good.content_hash,
                question_type=QuestionType.SHORT_ANSWER,
                content=content,
                state=bad_state,
            )


class TestInstanceSeparation:
    def test_same_question_two_instances(self, contract):
        qid = uuid.uuid4()
        rid = uuid.uuid4()
        rev = _revision(qid, rid, 1, _HASH_A)
        i1 = QuestionInstance(
            question_id=qid,
            revision_id=rid,
            source_document_id="paper_2020_national",
            printed_number="1",
            question_numbers=[1],
        )
        i2 = QuestionInstance(
            question_id=qid,
            revision_id=rid,
            source_document_id="paper_2021_mock",
            printed_number="5",
            question_numbers=[5],
        )
        agg = QuestionAggregate(
            identity=QuestionIdentity(question_id=qid),
            revisions=[rev],
            instances=[i1, i2],
        )
        assert len(agg.instances) == 2
        assert {i.source_document_id for i in agg.instances} == {
            "paper_2020_national",
            "paper_2021_mock",
        }

    def test_instance_must_reference_known_revision(self, contract):
        qid = uuid.uuid4()
        rev = _revision(qid, uuid.uuid4(), 1, _HASH_A)
        bad = QuestionInstance(
            question_id=qid,
            revision_id=uuid.uuid4(),  # not in revisions
            source_document_id="doc/1",
        )
        with pytest.raises(ValidationError, match="unknown revision"):
            QuestionAggregate(
                identity=QuestionIdentity(question_id=qid),
                revisions=[rev],
                instances=[bad],
            )

    def test_instance_must_belong_to_question(self, contract):
        qid = uuid.uuid4()
        rid = uuid.uuid4()
        rev = _revision(qid, rid, 1, _HASH_A)
        bad = QuestionInstance(
            question_id=uuid.uuid4(),
            revision_id=rid,
            source_document_id="doc/1",
        )
        with pytest.raises(ValidationError, match="must match identity"):
            QuestionAggregate(
                identity=QuestionIdentity(question_id=qid),
                revisions=[rev],
                instances=[bad],
            )


class TestAggregateIntegrity:
    def test_empty_revisions_rejected(self, contract):
        with pytest.raises(ValidationError):
            QuestionAggregate(
                identity=QuestionIdentity(), revisions=[]
            )

    def test_published_revision_lookup(self, contract):
        from question_core.contracts.v1 import (
            ReviewState,
            approve_revision,
            publish_revision,
        )

        qid = uuid.uuid4()
        rid = uuid.uuid4()
        rev = _revision(qid, rid, 1, _HASH_A)
        state = StateSnapshot(
            revision_id=rid,
            content_hash=rev.content_hash,
            completeness=Completeness.COMPLETE,
            review=ReviewState.PENDING_REVIEW,
        )
        state = approve_revision(state, approved_by="r", content_hash=rev.content_hash)
        state = publish_revision(state, acted_by="p", content_hash=rev.content_hash)
        rev_data = rev.model_dump(mode="json")
        rev_data["state"] = state.model_dump(mode="json")
        rev = Revision.model_validate(rev_data)
        agg = QuestionAggregate(
            identity=QuestionIdentity(question_id=qid), revisions=[rev]
        )
        assert agg.published_revision() is not None
        assert agg.published_revision().revision_id == rid

    def test_serialization_round_trip(self, contract):
        qid = uuid.uuid4()
        rid = uuid.uuid4()
        rev = _revision(qid, rid, 1, _HASH_A, _content("含公式 $x^2$"))
        inst = QuestionInstance(
            question_id=qid, revision_id=rid, source_document_id="doc/1"
        )
        agg = QuestionAggregate(
            identity=QuestionIdentity(question_id=qid, identity_fingerprint="fp-xxxxxx"),
            revisions=[rev],
            instances=[inst],
        )
        dumped = agg.model_dump(mode="json")
        again = QuestionAggregate.model_validate(dumped)
        assert again.model_dump(mode="json") == dumped
