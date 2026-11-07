"""Candidate dual-entry: preprocessing branch and student_upload branch."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from .golden_samples import (
    build_preprocessing_candidate,
    build_student_upload_candidate,
)


class TestPreprocessingCandidate:
    def test_builds(self, contract):
        cand = build_preprocessing_candidate()
        assert cand.source_type == "preprocessing"

    def test_requires_manifest_hash(self, contract):
        cand = build_preprocessing_candidate()
        assert cand.core.ingestion.input_hashes.manifest_hash is not None

    def test_unit_provenance_preserved(self, contract):
        cand = build_preprocessing_candidate()
        unit = cand.source.unit
        assert unit.unit_id == "Q1"
        assert unit.stem_lines == (13, 13)
        assert unit.answer_lines == (388, 388)

    def test_source_docs_all_hashed(self, contract):
        cand = build_preprocessing_candidate()
        for ref in (
            cand.source.manifest_ref,
            cand.source.source_md_ref,
            cand.source.source_pdf_ref,
        ):
            assert ref is not None
            assert len(ref.content_hash) == 64

    def test_rejects_unhashed_manifest(self, contract):
        cand = build_preprocessing_candidate()
        dumped = cand.model_dump(mode="json")
        dumped["source"]["manifest_ref"]["content_hash"] = "nothex"
        with pytest.raises(ValidationError):
            contract.PreprocessingCandidate.model_validate(dumped)

    def test_discriminated_union_dispatch(self, contract):
        cand = build_preprocessing_candidate()
        dumped = cand.model_dump(mode="json")
        parsed = contract.candidate_adapter.validate_python(dumped)
        assert isinstance(parsed, contract.PreprocessingCandidate)


class TestStudentUploadCandidate:
    def test_builds_without_manifest(self, contract):
        cand = build_student_upload_candidate()
        assert cand.source_type == "student_upload"
        # No manifest is required on this branch.
        assert not hasattr(cand.source, "manifest_ref")

    def test_requires_uploader(self, contract):
        cand = build_student_upload_candidate()
        assert cand.source.uploaded_by.startswith("student:")

    def test_ocr_observations_carry_confidence(self, contract):
        cand = build_student_upload_candidate()
        obs = cand.source.observations[0]
        assert obs.confidence == 0.82
        # Absent confidence is "not measured", distinct from 1.0.
        assert cand.source.observations[1].confidence is None

    def test_missing_answers_flagged_not_filled(self, contract):
        cand = build_student_upload_candidate()
        assert cand.source.answers_declared_absent is True
        assert cand.core.completeness.value == "incomplete"

    def test_owner_scope_defaults_to_student(self, contract):
        cand = build_student_upload_candidate()
        assert cand.source.owner_scope.value == "student"

    def test_distribution_defaults_to_no_redistribution(self, contract):
        cand = build_student_upload_candidate()
        assert cand.source.distribution_policy.value == "no_redistribution"

    def test_discriminated_union_dispatch(self, contract):
        cand = build_student_upload_candidate()
        parsed = contract.candidate_adapter.validate_python(cand.model_dump(mode="json"))
        assert isinstance(parsed, contract.StudentUploadCandidate)


class TestUnionBoundary:
    def test_unknown_source_type_rejected(self, contract):
        with pytest.raises(ValidationError):
            contract.candidate_adapter.validate_python(
                {"source_type": "telepathy", "core": {}, "source": {}}
            )

    def test_branch_differences_survive(self, contract):
        """Both land in one contract but keep their source-specific fields."""
        pre = build_preprocessing_candidate()
        stu = build_student_upload_candidate()
        pre_dump = pre.model_dump(mode="json")
        stu_dump = stu.model_dump(mode="json")
        assert "manifest_ref" in pre_dump["source"]
        assert "manifest_ref" not in stu_dump["source"]
        assert "observations" in stu_dump["source"]
        assert "observations" not in pre_dump["source"]
