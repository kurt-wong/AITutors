"""Shared fixtures for the Question Core contract tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Question Core/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from question_core.contracts import v1  # noqa: E402

CONTRACT_ROOT = _PROJECT_ROOT / "question_core"
GOLDEN_DIR = CONTRACT_ROOT / "golden" / "v1"
SCHEMA_PATH = CONTRACT_ROOT / "schema" / "v1" / "question_core.schema.json"


@pytest.fixture(scope="session")
def contract():
    return v1


@pytest.fixture(scope="session")
def schema_doc():
    return v1.build_json_schema()


@pytest.fixture(scope="session")
def schema_hash(schema_doc):
    return v1.compute_schema_hash(schema_doc)


@pytest.fixture
def input_hashes():
    return v1.InputHashes(
        manifest_hash="a" * 64,
        source_md_hash="b" * 64,
        source_pdf_hash="c" * 64,
    )


@pytest.fixture
def ingestion(input_hashes):
    return v1.IngestionIdentity(
        candidate_idempotency_key=v1.derive_idempotency_key(
            source_type="preprocessing",
            source_document_id="doc/1",
            input_hashes=input_hashes,
        ),
        adapter_version="strict-adapter/0.1.0",
        input_hashes=input_hashes,
    )


@pytest.fixture
def simple_body():
    return v1.QuestionBody(
        local_id="q1",
        question_type=v1.QuestionType.SINGLE_CHOICE,
        stem_blocks=[v1.TextBlock(text="题干")],
        options=[
            v1.OptionItem(label="A", blocks=[v1.TextBlock(text="甲")]),
            v1.OptionItem(label="B", blocks=[v1.TextBlock(text="乙")]),
        ],
    )
