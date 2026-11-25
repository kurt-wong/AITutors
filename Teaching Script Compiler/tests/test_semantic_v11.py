# -*- coding: utf-8 -*-
"""Isolated V1.1 adapter/index contract tests (no Ollama required)."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from tsc_compiler.semantic.retrieval import SemanticConfig
from tsc_compiler.semantic.v11.config import V11Config
from tsc_compiler.semantic.v11.index import V11Index, V11IndexMismatch
from tsc_compiler.semantic.v11.model import (
    ModelIdentity,
    OllamaGemmaEmbedder,
    V11InputError,
)


def _entry(qid: str, stem: str) -> dict:
    return {
        "question_id": qid,
        "revision_id": qid + "-r1",
        "subject": "数学",
        "question_type": "single_choice",
        "printed_number": "1",
        "source_document_id": "paper",
        "content_hash": "c" * 64,
        "stem_text": stem,
        "material_text": "",
        "options_text": "A. 1 B. 2",
        "explanation_text": "",
        "has_image": False,
        "has_table": False,
        "has_math": True,
    }


class FakeAdapter:
    available = True

    def __init__(self, dim: int = 8, digest: str = "d" * 64):
        self.dim = dim
        self.identity = ModelIdentity(
            name="embeddinggemma-2:latest",
            digest=digest,
            size=1,
            modified_at=None,
            declared_dim=dim,
            api_dim=dim,
            context_length=1000,
            parameter_size="271M",
            quantization="Q8_0",
            capabilities=("embedding",),
        )

    def identify(self, *, refresh: bool = False):
        return self.identity

    def encode(self, texts, *, batch_size=1, is_query=False):
        vectors = []
        for text in texts:
            seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
            vectors.append(np.random.default_rng(seed).normal(size=self.dim).astype(np.float32))
        return np.asarray(vectors, dtype=np.float32)


def test_build_load_and_exact_search(tmp_path):
    catalog = [_entry("q1", "已知函数 $f(x)=x^2$，求最小值。"), _entry("q2", "电场中带电粒子的运动。")]
    adapter = FakeAdapter()
    index = V11Index.build(catalog, adapter, tmp_path, namespace="test_ns")
    assert index.meta["namespace"] == "test_ns"
    assert index.meta["dim"] == 8
    loaded = V11Index.load(tmp_path, adapter, expected_config=V11Config())
    result = loaded.search(loaded.docs[0].text)
    assert result["decision"] == "exact"
    assert result["exact"]["question_id"] == "q1"
    assert loaded.meta["stores_qcore_fact"] is False


def test_model_digest_mismatch_rejected(tmp_path):
    catalog = [_entry("q1", "已知函数 $f(x)=x^2$，求最小值。")]
    adapter = FakeAdapter()
    V11Index.build(catalog, adapter, tmp_path)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    meta["model"]["digest"] = "e" * 64
    (tmp_path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(V11IndexMismatch):
        V11Index.load(tmp_path, adapter, expected_config=V11Config())


def test_dimension_mismatch_rejected(tmp_path):
    catalog = [_entry("q1", "已知函数 $f(x)=x^2$，求最小值。")]
    adapter = FakeAdapter()
    V11Index.build(catalog, adapter, tmp_path)
    np.save(tmp_path / "embeddings.npy", np.zeros((1, 3), dtype=np.float32))
    with pytest.raises(V11IndexMismatch):
        V11Index.load(tmp_path, adapter, expected_config=V11Config())


def test_config_hash_is_frozen_and_changes():
    base = V11Config()
    assert base.exact_dense == 0.74
    assert base.similar_dense == 0.85
    assert base.similar_lexical == 0.55
    assert V11Config(exact_dense=0.75).config_hash != base.config_hash


def test_v1_defaults_unchanged():
    cfg = SemanticConfig()
    assert cfg.exact_dense == 0.84
    assert cfg.similar_dense == 0.80
    assert cfg.similar_lexical == 0.55


def test_input_validation_rejects_empty_and_oversize():
    adapter = OllamaGemmaEmbedder(max_chars=5)
    with pytest.raises(V11InputError):
        adapter._validate_texts(["   "])
    with pytest.raises(V11InputError):
        adapter._validate_texts(["123456"])
    assert adapter._validate_texts(["12345"]) == ["12345"]
