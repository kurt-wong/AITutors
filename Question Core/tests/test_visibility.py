"""Visibility, PII and distribution policy.

The key separation: publishing a question never grants the right to
redistribute the teacher's PDF or images. The two axes are independent
fields, and each field (answer / explanation / evidence) carries its own
visibility.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestVisibilityLevels:
    def test_three_levels(self, contract):
        assert {v.value for v in contract.Visibility} == {
            "review_only",
            "student_after_submit",
            "public",
        }

    def test_review_only_is_default_on_candidate(self, contract):
        cand_core = contract.CandidateCore(
            question_type="single_choice",
            content=contract.QuestionContent(
                bodies=[
                    contract.QuestionBody(
                        local_id="q",
                        question_type="single_choice",
                        stem_blocks=[contract.TextBlock(text="x")],
                    )
                ]
            ),
            ingestion=contract.IngestionIdentity(
                candidate_idempotency_key="k" * 20,
                adapter_version="a/1",
                input_hashes=contract.InputHashes(manifest_hash="a" * 64),
            ),
        )
        assert cand_core.content_visibility == contract.Visibility.REVIEW_ONLY
        assert cand_core.answer_visibility == contract.Visibility.REVIEW_ONLY
        assert cand_core.evidence_visibility == contract.Visibility.REVIEW_ONLY

    def test_answer_and_explanation_independent(self, contract):
        core = contract.CandidateCore(
            question_type="short_answer",
            content=contract.QuestionContent(
                bodies=[
                    contract.QuestionBody(
                        local_id="q",
                        question_type="short_answer",
                        stem_blocks=[contract.TextBlock(text="x")],
                    )
                ]
            ),
            answers=[
                contract.SingleChoiceAnswer(
                    answer_value="A", visibility="student_after_submit"
                )
            ],
            answer_visibility="student_after_submit",
            explanation_visibility="review_only",
            ingestion=contract.IngestionIdentity(
                candidate_idempotency_key="k" * 20,
                adapter_version="a/1",
                input_hashes=contract.InputHashes(manifest_hash="a" * 64),
            ),
        )
        assert core.answer_visibility.value == "student_after_submit"
        assert core.explanation_visibility == contract.Visibility.REVIEW_ONLY

    def test_invalid_visibility_rejected(self, contract):
        with pytest.raises(ValidationError):
            contract.CandidateCore(
                question_type="single_choice",
                content=contract.QuestionContent(
                    bodies=[
                        contract.QuestionBody(
                            local_id="q",
                            question_type="single_choice",
                            stem_blocks=[contract.TextBlock(text="x")],
                        )
                    ]
                ),
                ingestion=contract.IngestionIdentity(
                    candidate_idempotency_key="k" * 20,
                    adapter_version="a/1",
                    input_hashes=contract.InputHashes(manifest_hash="a" * 64),
                ),
                content_visibility="everyone_forever",
            )


class TestPublicationVersusRedistribution:
    def test_distribution_policy_is_separate_field(self, contract):
        """A published question may still forbid PDF/image redistribution.

        F3: permission facts live on the source branch (single source of
        truth), not on CandidateCore. This test pins the separation.
        """
        source = contract.PreprocessingSource(
            source_document_id="doc/1",
            manifest_ref=contract.SourceDocumentRef(
                doc_role="manifest", content_hash="a" * 64
            ),
            unit=contract.PreprocessingUnitRef(
                unit_id="Q1", unit_type="standalone_question"
            ),
            owner_scope=contract.OwnerScope.PUBLIC_BANK,
            distribution_policy=contract.DistributionPolicy.NO_REDISTRIBUTION,
        )
        assert source.owner_scope == contract.OwnerScope.PUBLIC_BANK
        assert (
            source.distribution_policy
            == contract.DistributionPolicy.NO_REDISTRIBUTION
        )
        # The two axes are independent fields.
        assert source.owner_scope != source.distribution_policy

    def test_distribution_policies(self, contract):
        assert {p.value for p in contract.DistributionPolicy} == {
            "unknown",
            "no_redistribution",
            "internal_only",
            "redistributable",
        }


class TestPiiAndOwnership:
    def test_pii_status(self, contract):
        assert {p.value for p in contract.PiiStatus} == {
            "none",
            "suspected",
            "confirmed",
        }

    def test_owner_scopes(self, contract):
        assert {o.value for o in contract.OwnerScope} == {
            "public_bank",
            "school",
            "teacher",
            "student",
        }

    def test_student_upload_defaults(self, contract):
        from .golden_samples import build_student_upload_candidate

        cand = build_student_upload_candidate()
        assert cand.source.owner_scope == contract.OwnerScope.STUDENT
        assert cand.source.pii_status == contract.PiiStatus.SUSPECTED
        assert (
            cand.source.distribution_policy
            == contract.DistributionPolicy.NO_REDISTRIBUTION
        )
        # F3: permission facts live on the source branch only — CandidateCore
        # no longer duplicates them, so the contradiction class cannot occur.
        assert not hasattr(cand.core, "owner_scope")
        assert not hasattr(cand.core, "pii_status")
        assert not hasattr(cand.core, "distribution_policy")
        assert cand.core.answer_visibility == contract.Visibility.REVIEW_ONLY
