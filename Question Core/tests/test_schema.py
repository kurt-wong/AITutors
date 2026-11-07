"""Schema generation, JSON Schema 2020-12 validity, hash and golden snapshot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import GOLDEN_DIR, SCHEMA_PATH
from .golden_samples import (
    build_preprocessing_candidate,
    build_question_aggregate,
    build_student_upload_candidate,
    canonical_digest,
)


class TestJsonSchemaGeneration:
    def test_schema_is_draft_2020_12(self, schema_doc):
        assert schema_doc["$schema"] == (
            "https://json-schema.org/draft/2020-12/schema"
        )

    def test_schema_has_contract_id_and_version(self, schema_doc, contract):
        assert schema_doc["$id"] == contract.CONTRACT_SCHEMA_ID
        assert schema_doc["x-contract-version"] == contract.CONTRACT_VERSION

    def test_root_models_present(self, schema_doc):
        props = schema_doc["properties"]
        for name in (
            "PreprocessingCandidate",
            "StudentUploadCandidate",
            "QuestionAggregate",
        ):
            assert name in props, f"missing root model {name}"

    def test_defs_cover_all_models(self, schema_doc):
        defs = schema_doc["$defs"]
        # Spot-check the core models that every consumer needs.
        for name in (
            "Revision",
            "QuestionInstance",
            "EvidenceRecord",
            "EvidenceConflict",
            "StateSnapshot",
            "Asset",
            "TableBlock",
            "SingleChoiceAnswer",
            "NumericAnswer",
            "CompositeAnswer",
        ):
            assert name in defs, f"missing $defs entry {name}"

    def test_schema_file_written_matches_generated(self, schema_doc):
        assert SCHEMA_PATH.exists(), "schema file must be generated on disk"
        on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert on_disk == schema_doc


class TestSchemaHash:
    def test_hash_is_deterministic(self, schema_doc, schema_hash):
        again = __import__("hashlib").sha256(
            json.dumps(
                schema_doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        assert again == schema_hash

    def test_hash_excludes_itself(self, schema_doc):
        # compute_schema_hash refuses a document that already contains the
        # key, which is how the hash stays non-recursive.
        poisoned = dict(schema_doc)
        poisoned["schema_hash"] = "0" * 64
        with pytest.raises(ValueError, match="not recursively include"):
            __import__(
                "question_core.contracts.v1.manifest", fromlist=["x"]
            ).compute_schema_hash(poisoned)

    def test_manifest_hash_matches(self, schema_hash, contract):
        manifest = contract.build_manifest()
        assert manifest.schema_hash == schema_hash

    def test_manifest_lists_models(self, contract):
        manifest = contract.build_manifest()
        assert set(manifest.root_models) == {
            "PreprocessingCandidate",
            "StudentUploadCandidate",
            "QuestionAggregate",
        }
        assert "Revision" in manifest.models
        assert "EvidenceRecord" in manifest.models


class TestGoldenSnapshot:
    def test_golden_files_exist(self):
        for name in (
            "preprocessing_candidate.json",
            "student_upload_candidate.json",
            "question_aggregate.json",
            "golden_digests.json",
        ):
            assert (GOLDEN_DIR / name).exists(), f"missing golden {name}"

    def test_golden_preprocessing_round_trip(self):
        doc = json.loads(
            (GOLDEN_DIR / "preprocessing_candidate.json").read_text(encoding="utf-8")
        )
        parsed = __import__(
            "question_core.contracts.v1.candidate",
            fromlist=["x"],
        ).candidate_adapter.validate_python(doc)
        assert parsed.source_type == "preprocessing"
        # Re-serializing must produce the same canonical digest.
        assert canonical_digest(parsed.model_dump(mode="json")) == canonical_digest(doc)

    def test_golden_student_upload_round_trip(self):
        doc = json.loads(
            (GOLDEN_DIR / "student_upload_candidate.json").read_text(encoding="utf-8")
        )
        parsed = __import__(
            "question_core.contracts.v1.candidate",
            fromlist=["x"],
        ).candidate_adapter.validate_python(doc)
        assert parsed.source_type == "student_upload"
        assert canonical_digest(parsed.model_dump(mode="json")) == canonical_digest(doc)

    def test_golden_question_aggregate_round_trip(self, contract):
        doc = json.loads(
            (GOLDEN_DIR / "question_aggregate.json").read_text(encoding="utf-8")
        )
        parsed = contract.QuestionAggregate.model_validate(doc)
        assert canonical_digest(parsed.model_dump(mode="json")) == canonical_digest(doc)

    def test_golden_digests_stable(self):
        """Digest drift means the contract changed shape; review before
        regenerating the snapshot. N9: all three samples use fixed UUIDs
        and timestamps, so every digest must be reproducible."""
        recorded = json.loads(
            (GOLDEN_DIR / "golden_digests.json").read_text(encoding="utf-8")
        )
        for name, builder in (
            ("preprocessing_candidate.json", build_preprocessing_candidate),
            ("student_upload_candidate.json", build_student_upload_candidate),
            ("question_aggregate.json", build_question_aggregate),
        ):
            digest = canonical_digest(builder().model_dump(mode="json"))
            assert digest == recorded[name], f"golden drift in {name}"

    def test_golden_validates_against_json_schema(self, schema_doc):
        jsonschema = pytest.importorskip("jsonschema")
        validator_cls = jsonschema.validators.validator_for(schema_doc)
        validator_cls.check_schema(schema_doc)
        validator = validator_cls(schema_doc)

        doc = json.loads(
            (GOLDEN_DIR / "preprocessing_candidate.json").read_text(encoding="utf-8")
        )
        errors = list(
            validator.iter_errors({"PreprocessingCandidate": doc})
        )
        assert not errors, f"schema rejected golden: {errors[:3]}"

    def test_pydantic_is_single_source_of_truth(self, tmp_path, contract):
        """The on-disk schema must be regenerable from the models."""
        out = contract.write_artifacts(tmp_path)
        regenerated = json.loads(Path(out["schema"]).read_text(encoding="utf-8"))
        on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert regenerated == on_disk
