"""Unit tests: contract ⇄ payload serialization (no database)."""

from __future__ import annotations

import json
from uuid import UUID

import pytest

from question_core.contracts.v1 import (
    MathBlock,
    TextBlock,
    canonical_content_hash,
    compute_schema_hash,
    build_json_schema,
)
from question_core.persistence.exceptions import ContractViolationError
from question_core.persistence.serialize import (
    dump_contract,
    restore_aggregate,
    restore_candidate,
    restore_instance,
    restore_revision,
)

from .synthetic import (
    make_all_answers,
    make_preprocessing_candidate,
    make_published_revision,
    make_rich_aggregate,
    make_rich_revision,
    make_single_answer_revision,
    make_student_upload_candidate,
    make_instance,
    make_identity,
)

QID = UUID("00000000-0000-4000-8000-000000000055")


def _json_roundtrip(payload: dict) -> dict:
    """Simulate JSONB storage: dumps to a JSON string and parses back."""
    return json.loads(json.dumps(payload, ensure_ascii=False))


class TestRevisionSerialization:
    def test_rich_revision_round_trip(self):
        rev = make_rich_revision(QID)
        restored = restore_revision(_json_roundtrip(dump_contract(rev)))
        assert restored == rev
        assert restored.content_hash == rev.content_hash
        # content hash binding re-verified by the contract validator:
        assert (
            canonical_content_hash(
                restored.content,
                *restored.answers,
                *restored.explanation_blocks,
            )
            == restored.content_hash
        )

    def test_explanation_blocks_rehydrated(self):
        rev = make_rich_revision(QID)
        restored = restore_revision(_json_roundtrip(dump_contract(rev)))
        for block in restored.explanation_blocks:
            assert not isinstance(block, dict), (
                "explanation_blocks items must be rebuilt as contract models"
            )
        assert isinstance(restored.explanation_blocks[0], TextBlock)
        assert isinstance(restored.explanation_blocks[1], MathBlock)

    def test_unknown_explanation_block_rejected(self):
        rev = make_rich_revision(QID)
        payload = _json_roundtrip(dump_contract(rev))
        payload["explanation_blocks"] = [{"no_discriminator": True}]
        with pytest.raises(ContractViolationError):
            restore_revision(payload)

    def test_all_typed_answers_round_trip(self):
        rev = make_single_answer_revision(QID, answer=make_all_answers())
        restored = restore_revision(_json_roundtrip(dump_contract(rev)))
        assert restored == rev
        assert [
            a.answer_type for a in restored.answers
        ] == [a.answer_type for a in rev.answers]

    @pytest.mark.parametrize(
        "kind",
        [
            "single_choice",
            "multi_choice",
            "fill_blank",
            "numeric",
            "expression",
            "chemical",
            "multi_step",
            "composite",
            "composite_sub",
        ],
    )
    def test_each_answer_kind_survives(self, kind):
        rev = make_single_answer_revision(QID)
        answers = tuple(
            a for a in make_all_answers() if a.answer_type == kind
        )
        rev2 = make_single_answer_revision(QID, answer=answers)
        restored = restore_revision(_json_roundtrip(dump_contract(rev2)))
        assert restored == rev2
        assert restored.answers[0].answer_type == kind

    def test_published_revision_state_round_trip(self):
        rev = make_published_revision(QID)
        restored = restore_revision(_json_roundtrip(dump_contract(rev)))
        assert restored == rev
        assert restored.state is not None
        assert restored.state.approval is not None
        assert restored.state.publication_record is not None

    def test_corrupt_payload_raises_contract_violation(self):
        rev = make_single_answer_revision(QID)
        payload = _json_roundtrip(dump_contract(rev))
        payload["revision_number"] = 0  # violates ge=1
        with pytest.raises(ContractViolationError):
            restore_revision(payload)


class TestCandidateSerialization:
    def test_preprocessing_candidate_round_trip(self):
        cand = make_preprocessing_candidate()
        restored = restore_candidate(_json_roundtrip(dump_contract(cand)))
        assert restored == cand
        assert restored.source_type == "preprocessing"

    def test_student_upload_candidate_round_trip(self):
        cand = make_student_upload_candidate()
        restored = restore_candidate(_json_roundtrip(dump_contract(cand)))
        assert restored == cand
        assert restored.source_type == "student_upload"

    def test_branch_differences_survive(self):
        pre = restore_candidate(
            _json_roundtrip(dump_contract(make_preprocessing_candidate()))
        )
        stu = restore_candidate(
            _json_roundtrip(dump_contract(make_student_upload_candidate()))
        )
        assert pre.source.owner_scope.value == "public_bank"
        assert stu.source.owner_scope.value == "student"
        assert stu.source.uploaded_by == "student-42"


class TestAggregateSerialization:
    def test_rich_aggregate_round_trip(self):
        from question_core.persistence.serialize import (
            restore_identity,
            restore_state_snapshot,
        )

        agg = make_rich_aggregate()
        parts = _json_roundtrip(
            {
                "identity": dump_contract(agg.identity),
                "revisions": [dump_contract(r) for r in agg.revisions],
                "instances": [dump_contract(i) for i in agg.instances],
                "state_history": [
                    dump_contract(s) for s in agg.state_history
                ],
            }
        )
        restored = restore_aggregate(
            identity=restore_identity(parts["identity"]),
            revisions=tuple(restore_revision(r) for r in parts["revisions"]),
            instances=tuple(restore_instance(i) for i in parts["instances"]),
            state_history=tuple(
                restore_state_snapshot(s) for s in parts["state_history"]
            ),
        )
        assert restored == agg
        # evidence / composite / asset info intact
        rich = restored.revisions[0]
        assert len(rich.evidence.records) == 2
        assert len(rich.evidence.conflicts) == 1
        assert rich.evidence.conflicts[0].is_critical is True
        assert any(b.local_id == "q1a" for b in rich.content.bodies)
        assert rich.content.materials[0].material_id == "mat-1"
        assert rich.content.assets[0].asset_id == "fig-1"
        # merged-cell table survives inside the material blocks
        table = rich.content.materials[0].blocks[1]
        assert table.n_rows == 2 and table.n_cols == 2
        assert table.cells[0].rowspan == 2


class TestSchemaBaselineUntouched:
    def test_schema_hash_unchanged(self):
        expected = (
            "0cba7f5a0c0f85bb024bbb99fda381f2a20e0e4a783390a1e4b3710a601a4f14"
        )
        assert compute_schema_hash(build_json_schema()) == expected
