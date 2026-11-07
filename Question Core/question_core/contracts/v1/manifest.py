"""Contract Manifest: the generated, versioned description of this contract.

The Pydantic models are the single source of truth. Everything here is
*derived*: the JSON Schema, the Contract Manifest, and the schema hash.

``schema_hash`` is a SHA-256 over the generated JSON Schema document with
the ``schema_hash`` field of the manifest **removed** — it must never
recursively include itself.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import Field

from .common import CONTRACT_SCHEMA_ID, CONTRACT_VERSION, ContractModel, Sha256Hex
from . import answer as _answer
from . import candidate as _candidate
from . import content as _content
from . import evidence as _evidence
from . import idempotency as _idempotency
from . import question as _question
from . import state as _state

#: Root models that anchor the generated JSON Schema. Everything reachable
#: from these becomes part of the contract surface.
ROOT_MODELS: list[type[ContractModel]] = [
    _candidate.PreprocessingCandidate,
    _candidate.StudentUploadCandidate,
    _question.QuestionAggregate,
]

#: Every model class that belongs to the contract surface, for the manifest
#: inventory.
ALL_MODELS: list[type[ContractModel]] = [
    _answer.ChemicalAnswer,
    _answer.CompositeAnswer,
    _answer.CompositeSubAnswer,
    _answer.ExpressionAnswer,
    _answer.FillBlankAnswer,
    _answer.MultiChoiceAnswer,
    _answer.MultiStepAnswer,
    _answer.NumericAnswer,
    _answer.SingleChoiceAnswer,
    _candidate.CandidateCore,
    _candidate.OcrObservation,
    _candidate.PreprocessingCandidate,
    _candidate.PreprocessingSource,
    _candidate.PreprocessingUnitRef,
    _candidate.SourceDocumentRef,
    _candidate.StrictAnswerDeclaration,
    _candidate.StudentUploadCandidate,
    _candidate.StudentUploadSource,
    _content.Asset,
    _content.BBox,
    _content.ChemicalBlock,
    _content.ImageBlock,
    _content.Material,
    _content.MaterialRef,
    _content.MathBlock,
    _content.OptionItem,
    _content.QuestionBody,
    _content.QuestionContent,
    _content.TableCell,
    _content.TableBlock,
    _content.TextBlock,
    _evidence.EvidenceBundle,
    _evidence.EvidenceConflict,
    _evidence.EvidenceRecord,
    _evidence.SourceLocator,
    _evidence.SourceRef,
    _idempotency.IngestionIdentity,
    _idempotency.InputHashes,
    _question.QuestionAggregate,
    _question.QuestionIdentity,
    _question.QuestionInstance,
    _question.Revision,
    _state.ApprovalRecord,
    _state.PublicationRecord,
    _state.StateSnapshot,
]


class ContractManifest(ContractModel):
    """Versioned inventory of one contract release."""

    contract_version: str
    schema_id: str
    #: SHA-256 of the generated JSON Schema (see :func:`compute_schema_hash`).
    schema_hash: Sha256Hex | None = None
    schema_file: str
    generator: str = "question_core.contracts.v1.manifest"
    root_models: tuple[str, ...] = Field(default_factory=tuple)
    models: tuple[str, ...] = Field(default_factory=tuple)
    notes: str | None = None


def build_json_schema() -> dict[str, Any]:
    """Generate the JSON Schema (draft 2020-12) for the whole contract.

    Pydantic v2 emits 2020-12 by default. The root schema is a small
    wrapper that ``$ref``s each root model, so consumers can validate a
    Candidate or a QuestionAggregate against the same document.
    """
    defs: dict[str, Any] = {}
    roots: dict[str, Any] = {}
    for model in ROOT_MODELS:
        schema = model.model_json_schema(
            ref_template="#/$defs/{model}",
            mode="validation",
        )
        local_defs = schema.pop("$defs", {})
        defs.update(local_defs)
        roots[model.__name__] = schema

    document: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": CONTRACT_SCHEMA_ID,
        "title": f"AITutor Question Core contract v{CONTRACT_VERSION}",
        "x-contract-version": CONTRACT_VERSION,
        "properties": roots,
        "$defs": defs,
    }
    return document


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding used for hashing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_schema_hash(schema_document: dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON of the schema document.

    The document must **not** contain a ``schema_hash`` key — the hash must
    never include itself. This function refuses such input defensively.
    """
    if "schema_hash" in schema_document:
        raise ValueError(
            "schema document must not contain schema_hash; the hash must "
            "not recursively include itself"
        )
    blob = canonical_json(schema_document).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_manifest() -> ContractManifest:
    schema = build_json_schema()
    digest = compute_schema_hash(schema)
    return ContractManifest(
        contract_version=CONTRACT_VERSION,
        schema_id=CONTRACT_SCHEMA_ID,
        schema_hash=digest,
        schema_file="schema/v1/question_core.schema.json",
        root_models=[m.__name__ for m in ROOT_MODELS],
        models=[m.__name__ for m in ALL_MODELS],
        notes=(
            "Generated from Pydantic v2 models. Do not hand-edit the JSON "
            "Schema; regenerate it."
        ),
    )


def write_artifacts(output_root: str | Path) -> dict[str, str]:
    """Write schema + manifest under ``output_root``; return written paths."""
    root = Path(output_root)
    schema_dir = root / "schema" / "v1"
    schema_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir = root / "golden" / "v1"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    schema = build_json_schema()
    digest = compute_schema_hash(schema)
    schema_path = schema_dir / "question_core.schema.json"
    schema_path.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    manifest = build_manifest()
    manifest_path = manifest_dir / "contract_manifest.json"
    manifest_path.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "schema": str(schema_path),
        "manifest": str(manifest_path),
        "schema_hash": digest,
    }


__all__ = [
    "ALL_MODELS",
    "ContractManifest",
    "ROOT_MODELS",
    "build_json_schema",
    "build_manifest",
    "canonical_json",
    "compute_schema_hash",
    "write_artifacts",
]
