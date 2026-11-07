"""Idempotency keys and ingestion identity."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestIdempotencyKey:
    def test_same_input_same_key(self, contract):
        h = contract.InputHashes(manifest_hash="a" * 64, source_md_hash="b" * 64)
        k1 = contract.derive_idempotency_key(
            source_type="preprocessing", source_document_id="doc/1", input_hashes=h
        )
        k2 = contract.derive_idempotency_key(
            source_type="preprocessing", source_document_id="doc/1", input_hashes=h
        )
        assert k1 == k2

    def test_different_input_different_key(self, contract):
        h1 = contract.InputHashes(manifest_hash="a" * 64)
        h2 = contract.InputHashes(manifest_hash="b" * 64)
        k1 = contract.derive_idempotency_key(
            source_type="preprocessing", source_document_id="doc/1", input_hashes=h1
        )
        k2 = contract.derive_idempotency_key(
            source_type="preprocessing", source_document_id="doc/1", input_hashes=h2
        )
        assert k1 != k2

    def test_different_doc_different_key(self, contract):
        h = contract.InputHashes(manifest_hash="a" * 64)
        k1 = contract.derive_idempotency_key(
            source_type="preprocessing", source_document_id="doc/1", input_hashes=h
        )
        k2 = contract.derive_idempotency_key(
            source_type="preprocessing", source_document_id="doc/2", input_hashes=h
        )
        assert k1 != k2

    def test_key_excludes_run_id(self, contract):
        """The key identifies *what* was imported, not *which run* did it."""
        h = contract.InputHashes(manifest_hash="a" * 64)
        key = contract.derive_idempotency_key(
            source_type="preprocessing", source_document_id="doc/1", input_hashes=h
        )
        run1 = contract.IngestionIdentity(
            candidate_idempotency_key=key,
            adapter_version="a/1",
            input_hashes=h,
        )
        run2 = contract.IngestionIdentity(
            candidate_idempotency_key=key,
            adapter_version="a/1",
            input_hashes=h,
        )
        assert run1.ingestion_run_id != run2.ingestion_run_id
        assert run1.candidate_idempotency_key == run2.candidate_idempotency_key

    def test_empty_hashes_rejected(self, contract):
        with pytest.raises(ValueError, match="without any input hash"):
            contract.derive_idempotency_key(
                source_type="preprocessing",
                source_document_id="doc/1",
                input_hashes=contract.InputHashes(),
            )

    def test_upload_branch_key_distinct_from_preprocessing(self, contract):
        h = contract.InputHashes(upload_blob_hash="e" * 64)
        k = contract.derive_idempotency_key(
            source_type="student_upload",
            source_document_id="doc/1",
            input_hashes=h,
        )
        h2 = contract.InputHashes(manifest_hash="e" * 64)
        k2 = contract.derive_idempotency_key(
            source_type="preprocessing",
            source_document_id="doc/1",
            input_hashes=h2,
        )
        assert k != k2


class TestAdapterVersionTraceability:
    def test_adapter_version_recorded(self, contract):
        ident = contract.IngestionIdentity(
            candidate_idempotency_key="k" * 20,
            adapter_version="strict-adapter/0.2.0",
            input_hashes=contract.InputHashes(manifest_hash="a" * 64),
        )
        assert ident.adapter_version == "strict-adapter/0.2.0"

    def test_two_runs_with_different_adapter_keep_distinct_runs(self, contract):
        """An adapter upgrade must be traceable and must not overwrite the
        earlier outcome — different run ids, same logical key."""
        h = contract.InputHashes(manifest_hash="a" * 64)
        key = contract.derive_idempotency_key(
            source_type="preprocessing", source_document_id="doc/1", input_hashes=h
        )
        v1 = contract.IngestionIdentity(
            candidate_idempotency_key=key,
            adapter_version="strict-adapter/0.1.0",
            input_hashes=h,
        )
        v2 = contract.IngestionIdentity(
            candidate_idempotency_key=key,
            adapter_version="strict-adapter/0.2.0",
            input_hashes=h,
        )
        assert v1.ingestion_run_id != v2.ingestion_run_id
        assert v1.candidate_idempotency_key == v2.candidate_idempotency_key
        assert v1.adapter_version != v2.adapter_version


class TestInputHashes:
    def test_at_least_one_hash(self, contract):
        assert contract.InputHashes().is_empty is True
        assert contract.InputHashes(manifest_hash="a" * 64).is_empty is False

    def test_invalid_hash_rejected(self, contract):
        with pytest.raises(ValidationError):
            contract.InputHashes(manifest_hash="xyz")
