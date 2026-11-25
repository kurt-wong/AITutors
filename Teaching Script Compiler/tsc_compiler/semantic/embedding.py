"""Local dense embedding adapter (bge-small-zh-v1.5) with an explicit fallback.

The model file is *not* vendored in git. Operators either set
``TSC_EMBEDDING_MODEL`` to a local directory or accept the sparse lexical
fallback. The adapter is deliberately lazy: importing this module never
imports torch or transformers.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

import numpy as np

DEFAULT_MODEL_ENV = "TSC_EMBEDDING_MODEL"
#: bge-small-zh-v1.5's asymmetric retrieval instruction. Question↔question
#: identity matching is symmetric, so the default is empty; operators can set
#: a prefix when the query is a short natural-language search phrase.
DEFAULT_QUERY_PREFIX = ""


class DenseEmbedder:
    """Mean-pooled, L2-normalized sentence embeddings on CPU."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        *,
        device: str = "cpu",
        max_length: int = 512,
        query_prefix: str | None = None,
    ) -> None:
        path = Path(model_path or os.environ.get(DEFAULT_MODEL_ENV, "") or "")
        self.model_path = path if str(path) else None
        self.device = device
        self.max_length = max_length
        self.query_prefix = DEFAULT_QUERY_PREFIX if query_prefix is None else query_prefix
        self._tokenizer = None
        self._model = None
        self._torch = None
        self.available = bool(self.model_path and (self.model_path / "config.json").is_file())

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self.available:
            raise RuntimeError(
                "dense embedding model unavailable; set TSC_EMBEDDING_MODEL to a "
                "local bge-small-zh-v1.5 directory"
            )
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_path))
        self._model = AutoModel.from_pretrained(str(self.model_path))
        self._model.eval()
        self._model.to(self.device)

    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: int = 16,
        is_query: bool = False,
    ) -> np.ndarray:
        if not texts:
            return np.zeros((0, 512), dtype=np.float32)
        if not self.available:
            raise RuntimeError("dense embedding model unavailable")
        self._load()
        torch = self._torch
        prefix = self.query_prefix if (is_query and self.query_prefix) else ""
        vectors: list[np.ndarray] = []
        with torch.no_grad():
            for start in range(0, len(texts), batch_size):
                batch = [prefix + str(t) for t in texts[start : start + batch_size]]
                encoded = self._tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                encoded = {k: v.to(self.device) for k, v in encoded.items()}
                output = self._model(**encoded).last_hidden_state
                mask = encoded["attention_mask"].unsqueeze(-1).float()
                pooled = (output * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
                vectors.append(pooled.cpu().numpy().astype(np.float32))
        return np.vstack(vectors)


def cosine_scores(matrix: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Cosine similarity for an already L2-normalized matrix and query."""
    if matrix.size == 0:
        return np.zeros((0,), dtype=np.float32)
    q = query.reshape(-1)
    q = q / (np.linalg.norm(q) + 1e-12)
    m = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12)
    return (m @ q).astype(np.float32)
