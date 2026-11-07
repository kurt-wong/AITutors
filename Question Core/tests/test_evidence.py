"""Evidence: multiple sources, conflicts, JSON Pointer targeting, append-only."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def _record(target, value, source_id, role="answer", eid=None):
    from question_core.contracts.v1 import (
        EvidenceRecord,
        SourceLocator,
        SourceRef,
        SourceKind,
    )

    kwargs = dict(
        target_path=target,
        evidence_role=role,
        source=SourceRef(
            source_id=source_id,
            source_kind=SourceKind.SOURCE_MARKDOWN,
            content_hash="a" * 64,
        ),
        locators=[SourceLocator(kind="line_range", line_start=1, line_end=1)],
        raw_value=value,
    )
    return EvidenceRecord(**kwargs)


class TestMultipleEvidencePerTarget:
    def test_two_records_same_target(self, contract):
        r1 = _record("/answers/0/answer_value", "B", "paper.md")
        r2 = _record("/answers/0/answer_value", "B", "manifest.json")
        bundle = contract.EvidenceBundle(records=[r1, r2])
        assert len(bundle.for_target("/answers/0/answer_value")) == 2

    def test_bundle_rejects_duplicate_ids(self, contract):
        r1 = _record("/a", "x", "s1")
        r2 = r1.model_copy()
        with pytest.raises(ValidationError, match="duplicate evidence_id"):
            contract.EvidenceBundle(records=[r1, r2])


class TestConflict:
    def test_conflict_records_both_sides(self, contract):
        r1 = _record("/answers/0/answer_value", "B", "manifest.json")
        r2 = _record("/answers/0/answer_value", "C", "answer_table")
        conflict = contract.EvidenceConflict(
            target_path="/answers/0/answer_value",
            evidence_ids=[r1.evidence_id, r2.evidence_id],
            is_critical=True,
        )
        bundle = contract.EvidenceBundle(records=[r1, r2], conflicts=[conflict])
        assert len(bundle.unresolved_critical()) == 1

    def test_conflict_needs_two_evidence(self, contract):
        with pytest.raises(ValidationError):
            contract.EvidenceConflict(
                target_path="/a", evidence_ids=[_record("/a", "x", "s").evidence_id]
            )

    def test_unresolved_conflict_cannot_carry_winner(self, contract):
        r1 = _record("/a", "x", "s1")
        r2 = _record("/a", "y", "s2")
        with pytest.raises(ValidationError, match="unresolved conflict"):
            contract.EvidenceConflict(
                target_path="/a",
                evidence_ids=[r1.evidence_id, r2.evidence_id],
                winning_evidence_id=r1.evidence_id,
            )

    def test_resolved_conflict_requires_adjudicator(self, contract):
        r1 = _record("/a", "x", "s1")
        r2 = _record("/a", "y", "s2")
        with pytest.raises(ValidationError, match="requires resolved_by"):
            contract.EvidenceConflict(
                target_path="/a",
                evidence_ids=[r1.evidence_id, r2.evidence_id],
                resolution="human_adjudicated",
            )

    def test_resolved_conflict_may_name_winner(self, contract):
        r1 = _record("/a", "x", "s1")
        r2 = _record("/a", "y", "s2")
        c = contract.EvidenceConflict(
            target_path="/a",
            evidence_ids=[r1.evidence_id, r2.evidence_id],
            resolution="human_adjudicated",
            resolved_by="reviewer:Kurtw",
            winning_evidence_id=r1.evidence_id,
        )
        assert c.winning_evidence_id == r1.evidence_id

    def test_winner_must_be_among_the_disagreeing(self, contract):
        r1 = _record("/a", "x", "s1")
        r2 = _record("/a", "y", "s2")
        outsider = _record("/b", "z", "s3")
        with pytest.raises(ValidationError, match="winning_evidence_id"):
            contract.EvidenceConflict(
                target_path="/a",
                evidence_ids=[r1.evidence_id, r2.evidence_id],
                resolution="human_adjudicated",
                resolved_by="reviewer:X",
                winning_evidence_id=outsider.evidence_id,
            )

    def test_conflict_referencing_unknown_evidence_rejected(self, contract):
        r1 = _record("/a", "x", "s1")
        import uuid

        ghost = uuid.uuid4()
        with pytest.raises(ValidationError, match="unknown evidence"):
            contract.EvidenceBundle(
                records=[r1],
                conflicts=[
                    contract.EvidenceConflict(
                        target_path="/a",
                        evidence_ids=[r1.evidence_id, ghost],
                    )
                ],
            )

    def test_no_source_precedence_baked_in(self, contract):
        """The contract must not silently prefer one source kind over
        another; precedence is an explicit adjudication."""
        r1 = _record("/a", "x", "manifest.json")
        r2 = _record("/a", "y", "human_review")
        bundle = contract.EvidenceBundle(records=[r1, r2])
        # Both survive; nothing was dropped or auto-ranked.
        assert len(bundle.records) == 2
        assert {r.source.source_kind for r in bundle.records} == {
            r1.source.source_kind,
            r2.source.source_kind,
        }


class TestJsonPointerTargeting:
    def test_pointer_into_nested_answer(self, contract):
        ptr = "/answers/0/answer_value"
        rec = _record(ptr, "0.10", "paper.md")
        assert rec.target_path == ptr

    def test_pointer_allows_escaped_tokens(self, contract):
        rec = _record("/a~0b/c~1d", "x", "s")
        assert rec.target_path == "/a~0b/c~1d"

    def test_invalid_pointer_rejected(self, contract):
        with pytest.raises(ValidationError):
            _record("answers/0", "x", "s")  # missing leading slash

    def test_locator_range_validated(self, contract):
        with pytest.raises(ValidationError, match="line_end"):
            contract.SourceLocator(kind="line_range", line_start=10, line_end=5)

    def test_page_region_locator(self, contract):
        loc = contract.SourceLocator(kind="page_region", page=3, bbox=(0.1, 0.2, 0.3, 0.4))
        assert loc.page == 3


class TestEvidencePreservation:
    def test_new_evidence_does_not_replace_old(self, contract):
        r1 = _record("/a", "B", "manifest.json")
        r2 = _record("/a", "B", "answer_table")
        r3 = _record("/a", "B", "human_review")
        bundle = contract.EvidenceBundle(records=[r1, r2, r3])
        assert len(bundle.records) == 3, "append-only: nothing is overwritten"

    def test_status_marks_superseded_without_deleting(self, contract):
        r1 = _record("/a", "B", "old.md")
        r1_data = r1.model_dump(mode="json")
        r1_data["evidence_status"] = "superseded"
        r1_superseded = contract.EvidenceRecord.model_validate(r1_data)
        r2 = _record("/a", "C", "new.md")
        bundle = contract.EvidenceBundle(records=[r1_superseded, r2])
        assert len(bundle.records) == 2
        assert bundle.records[0].evidence_status == contract.EvidenceStatus.SUPERSEDED
