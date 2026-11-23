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
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from .common import ActorId, ContractModel, NoteText, Sha256Hex, utc_now

#: Identity-key schema version. ``qk1_`` = legacy (processing hashes were part
#: of the identity); ``qk2_`` = source-anchored identity (D9 fix).
IDENTITY_VERSION = 2
IDENTITY_KEY_PREFIX = "qk2_"
LEGACY_IDENTITY_KEY_PREFIX = "qk1_"

#: Dash variants collapse to ``-``; brackets/punctuation are noise in section
#: labels that drift between processing rounds (see D9 evidence, 2026-11-23).
_DASH_CHARS = "\u2010\u2011\u2012\u2013\u2014\u2015\uff0d"
_BRACKET_CHARS = "[]\u3010\u3011()\uff08\uff09<>\u300a\u300b\u3014\u3015\u3008\u3009"
_TRAILING_PUNCT = ":\uff1a\u3001,\uff0c;\uff1b\u3002\uff0e. "


class IdentityAnchorError(ValueError):
    """The unit cannot be anchored to a stable source identity."""


@dataclass(frozen=True)
class IdentityAnchor:
    """Stable, source-anchored identity of one Question (D9).

    ``paper_segment_id`` — logical paper inside a PDF (double-paper PDFs must
    declare segments; a single-paper PDF uses the PDF's paper id).
    ``section_id`` — ``normalize_section_label(label) + '#' + ordinal``.
    ``question_numbers`` — the printed question numbers the unit covers, taken
    from ``question_numbers`` (``printed_number`` is not trustworthy: English
    composite units store a section-relative number there).
    ``source_hash`` — the original PDF hash (or upload blob hash). Processing
    artifacts (manifest / OCR markdown) are deliberately absent.
    """

    paper_segment_id: str
    section_id: str
    question_numbers: tuple[int, ...]
    source_hash: str

    def as_dict(self) -> dict:
        return {
            "paper_segment_id": self.paper_segment_id,
            "section_id": self.section_id,
            "question_numbers": list(self.question_numbers),
            "source_hash": self.source_hash,
        }

    def validate(self) -> "IdentityAnchor":
        if not self.paper_segment_id.strip():
            raise IdentityAnchorError("paper_segment_id is required for identity")
        if not self.question_numbers:
            raise IdentityAnchorError(
                "question_numbers is required for identity; a unit without "
                "printed question numbers has no stable anchor (D9: do not "
                "fall back to positional ids)"
            )
        if not self.source_hash:
            raise IdentityAnchorError("source_hash is required for identity")
        return self


def normalize_section_label(label: str | None) -> str:
    """Canonical form of a section label.

    Measured drift across five manifests of the same paper (2026-11-23):
    ``【化学—选修3：物质结构与性质】`` / ``[化学-选修5：有机化学基础]`` /
    ``化学-选修5：有机化学基础`` and empty labels. Normalisation makes the
    bracketed/half-width/punctuation variants collide; emptiness stays empty
    (a missing section is a manifest-quality problem, not something identity
    may paper over with positional guessing).
    """
    if not label:
        return ""
    s = unicodedata.normalize("NFKC", str(label))
    for ch in _DASH_CHARS:
        s = s.replace(ch, "-")
    for ch in _BRACKET_CHARS:
        s = s.replace(ch, "")
    s = re.sub(r"\s+", "", s)
    return s.rstrip(_TRAILING_PUNCT)


def build_section_id(label: str | None, ordinal: int) -> str:
    """``normalized_label#ordinal`` — ordinal disambiguates repeated labels."""
    if ordinal < 1:
        raise IdentityAnchorError(f"section ordinal must be >= 1, got {ordinal}")
    return f"{normalize_section_label(label)}#{ordinal}"


def derive_identity_key(anchor: IdentityAnchor) -> str:
    """``qk2_`` key: pure function of the source anchor (D9).

    Manifest / OCR markdown / adapter version never enter this key, so
    re-processing an unchanged source can no longer mint a new Question
    identity.
    """
    anchor.validate()
    payload = {
        "identity_version": IDENTITY_VERSION,
        "paper_segment_id": anchor.paper_segment_id,
        "section_id": anchor.section_id,
        "question_numbers": list(anchor.question_numbers),
        "source_hash": anchor.source_hash,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return f"{IDENTITY_KEY_PREFIX}{digest[:40]}"


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
    """LEGACY ``qk1_`` key — do not use for new Question identities (D9).

    This is the historical key: it includes ``manifest_hash`` /
    ``source_md_hash``, so regenerating a manifest mints a brand-new key and
    the importer creates a duplicate Question. Kept only so historical
    candidate rows and old fixtures remain readable.

    New ingestion must use :func:`derive_identity_key` (``qk2_``), whose
    inputs are source-anchored only.
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
    return f"{LEGACY_IDENTITY_KEY_PREFIX}{digest[:40]}"


__all__ = [
    "IDENTITY_KEY_PREFIX",
    "IDENTITY_VERSION",
    "IdentityAnchor",
    "IdentityAnchorError",
    "IngestionIdentity",
    "InputHashes",
    "build_section_id",
    "derive_idempotency_key",
    "derive_identity_key",
    "normalize_section_label",
]
