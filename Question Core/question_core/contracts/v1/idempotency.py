"""Ingestion identity: idempotency keys, batch runs and adapter versions.

Four distinct things (direction document §3.9):

1. **Logical source object identity** — what the input *is* (the paper, the
   upload). Captured by the input content hashes.
2. **A concrete ingestion run** — one execution that tried to bring that
   input in. ``ingestion_run_id``.
3. **Adapter version** — the code that did the mapping. Must be traceable;
   a new adapter version must never overwrite an existing review record.
4. **Input file content hashes** — manifest / source markdown / source PDF.

Re-running the same input must not produce duplicate candidates: that is
enforced through ``candidate_idempotency_key``, which is a pure function of
the logical source identity (not of the run).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from .common import ActorId, ContractModel, NoteText, Sha256Hex, utc_now


class InputHashes(ContractModel):
    """Content hashes of the artifacts an ingestion consumed.

    At least one hash must be present: an ingestion with no identity is not
    idempotent and must be rejected by the importer.
    """

    manifest_hash: Sha256Hex | None = None
    source_md_hash: Sha256Hex | None = None
    source_pdf_hash: Sha256Hex | None = None
    upload_blob_hash: Sha256Hex | None = None

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.manifest_hash,
                self.source_md_hash,
                self.source_pdf_hash,
                self.upload_blob_hash,
            )
        )


class IngestionIdentity(ContractModel):
    """Identity of one logical source object + one run that imported it.

    N5: at least one input hash is mandatory — an ingestion with no
    verifiable input identity is not traceable and not idempotent.
    """

    #: Pure function of the logical source identity (see
    #: :func:`derive_idempotency_key`). Two runs over the same input carry
    #: the same key; the importer dedupes on it.
    candidate_idempotency_key: Annotated[str, Field(min_length=16, max_length=200)]
    #: Identity of *this* run. Unique per execution.
    ingestion_run_id: UUID = Field(default_factory=uuid4)
    #: Version of the adapter that produced the mapping. Recorded so a later
    #: adapter version can be told apart without overwriting earlier
    #: outcomes.
    adapter_version: Annotated[str, Field(min_length=1, max_length=100)]
    input_hashes: InputHashes
    ingested_at: datetime = Field(default_factory=utc_now)
    ingested_by: ActorId | None = None
    note: NoteText | None = None

    @model_validator(mode="after")
    def _require_input_hash(self) -> "IngestionIdentity":
        # N5: refuse an ingestion that carries no input identity at all.
        if self.input_hashes.is_empty:
            raise ValueError(
                "IngestionIdentity requires at least one input hash "
                "(manifest_hash, source_md_hash, source_pdf_hash or "
                "upload_blob_hash); an unidentifiable ingestion cannot be "
                "deduplicated or traced"
            )
        return self


def derive_idempotency_key(
    *,
    source_type: str,
    source_document_id: str,
    input_hashes: InputHashes,
) -> str:
    """Deterministic idempotency key for a logical source object.

    Deliberately excludes ``ingestion_run_id`` and ``adapter_version``: the
    key identifies *what was imported*, not *which run did it*. Two runs of
    the same manifest therefore collide on the key and the importer can
    dedupe, while an adapter upgrade is recorded on the run, not on the key.
    """
    if input_hashes.is_empty:
        raise ValueError("cannot derive idempotency key without any input hash")
    payload = {
        "source_type": source_type,
        "source_document_id": source_document_id,
        "manifest_hash": input_hashes.manifest_hash,
        "source_md_hash": input_hashes.source_md_hash,
        "source_pdf_hash": input_hashes.source_pdf_hash,
        "upload_blob_hash": input_hashes.upload_blob_hash,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return f"qk1_{digest[:40]}"


__all__ = [
    "IngestionIdentity",
    "InputHashes",
    "derive_idempotency_key",
]
