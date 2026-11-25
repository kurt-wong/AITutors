"""Ollama embeddinggemma-2 adapter (isolated V1.1 candidate).

The adapter never imports or mutates the BGE V1 embedder. It records the exact
Ollama model digest and probes the real embedding dimension; metadata-reported
``embedding_length`` is kept separately because it can disagree with the API
output (for embeddinggemma-2 it reports 512 while /api/embed returns 768).
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Sequence

import numpy as np
import requests

DEFAULT_MODEL = "embeddinggemma-2:latest"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MAX_CHARS = 100_000


class V11ModelError(RuntimeError):
    pass


class V11ModelUnavailable(V11ModelError):
    pass


class V11ModelIdentityError(V11ModelError):
    pass


class V11DimensionMismatch(V11ModelError):
    pass


class V11InputError(V11ModelError):
    pass


@dataclass(frozen=True)
class ModelIdentity:
    name: str
    digest: str
    size: int
    modified_at: str | None
    declared_dim: int | None
    api_dim: int
    context_length: int | None
    parameter_size: str | None
    quantization: str | None
    capabilities: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            **asdict(self),
            "capabilities": list(self.capabilities),
            "dimension_mismatch_metadata_vs_api": (
                self.declared_dim is not None and self.declared_dim != self.api_dim
            ),
        }


class OllamaGemmaEmbedder:
    """Small, explicit Ollama client; no silent fallback and no truncation."""

    available = True

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        base_url: str | None = None,
        max_chars: int = DEFAULT_MAX_CHARS,
        timeout: float = 600.0,
    ) -> None:
        self.model = model
        self.base_url = (base_url or os.environ.get("TSC_V11_OLLAMA_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.max_chars = max_chars
        self.timeout = timeout
        self._session = requests.Session()
        self._identity: ModelIdentity | None = None

    # ------------------------------------------------------------------ HTTP
    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = self._session.post(
                self.base_url + path, json=payload, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise V11ModelUnavailable(f"Ollama request failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise V11ModelUnavailable(
                f"Ollama HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise V11ModelUnavailable("Ollama returned non-JSON") from exc

    def _get(self, path: str) -> dict:
        try:
            response = self._session.get(self.base_url + path, timeout=60)
        except requests.RequestException as exc:
            raise V11ModelUnavailable(f"Ollama request failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise V11ModelUnavailable(
                f"Ollama HTTP {response.status_code}: {response.text[:200]}"
            )
        return response.json()

    # -------------------------------------------------------------- identity
    def identify(self, *, refresh: bool = False) -> ModelIdentity:
        if self._identity is not None and not refresh:
            return self._identity
        tags = self._get("/api/tags").get("models") or []
        entry = next(
            (
                item
                for item in tags
                if item.get("name") == self.model or item.get("model") == self.model
            ),
            None,
        )
        if entry is None:
            raise V11ModelIdentityError(f"model not found in /api/tags: {self.model}")
        digest = str(entry.get("digest") or "")
        if not digest:
            raise V11ModelIdentityError("model digest missing")
        show = self._post("/api/show", {"model": self.model})
        details = entry.get("details") or show.get("details") or {}
        model_info = show.get("model_info") or {}
        context = details.get("context_length")
        if context is None:
            for key, value in model_info.items():
                if key.endswith("context_length"):
                    context = value
                    break
        declared_dim = details.get("embedding_length")
        if declared_dim is None:
            for key, value in model_info.items():
                if key.endswith("embedding_length"):
                    declared_dim = value
                    break
        probe = self._post("/api/embed", {"model": self.model, "input": ["dimension probe"]})
        embeddings = probe.get("embeddings") or []
        if not embeddings or not embeddings[0]:
            raise V11DimensionMismatch("empty probe embedding")
        api_dim = len(embeddings[0])
        self._identity = ModelIdentity(
            name=str(entry.get("name") or self.model),
            digest=digest,
            size=int(entry.get("size") or 0),
            modified_at=entry.get("modified_at"),
            declared_dim=int(declared_dim) if declared_dim is not None else None,
            api_dim=api_dim,
            context_length=int(context) if context is not None else None,
            parameter_size=details.get("parameter_size"),
            quantization=details.get("quantization_level"),
            capabilities=tuple(show.get("capabilities") or entry.get("capabilities") or ()),
        )
        return self._identity

    # -------------------------------------------------------------- validate
    def _validate_texts(self, texts: Sequence[str]) -> list[str]:
        clean: list[str] = []
        for index, text in enumerate(texts):
            value = str(text or "")
            if not value.strip():
                raise V11InputError(f"empty text at index {index}")
            if len(value) > self.max_chars:
                raise V11InputError(
                    f"text at index {index} is {len(value)} chars > configured "
                    f"max_chars={self.max_chars}; refusing silent truncation"
                )
            clean.append(value)
        return clean

    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: int = 1,
        is_query: bool = False,
    ) -> np.ndarray:
        clean = self._validate_texts(texts)
        if not clean:
            return np.zeros((0, self.identify().api_dim), dtype=np.float32)
        dim = self.identify().api_dim
        size = max(1, int(batch_size))
        collected: list[list[float]] = []
        for start in range(0, len(clean), size):
            chunk = clean[start : start + size]
            payload = self._post("/api/embed", {"model": self.model, "input": chunk})
            embeddings = payload.get("embeddings") or []
            if len(embeddings) != len(chunk):
                raise V11ModelIdentityError(
                    f"embedding count mismatch: {len(embeddings)} != {len(chunk)}"
                )
            for index, vector in enumerate(embeddings):
                if len(vector) != dim:
                    raise V11DimensionMismatch(
                        f"embedding {index} has dim {len(vector)}, expected {dim}"
                    )
            collected.extend(embeddings)
        return np.asarray(collected, dtype=np.float32)


def text_stats(texts: Sequence[str], *, max_chars: int = DEFAULT_MAX_CHARS) -> dict:
    lengths = [len(str(t or "")) for t in texts]
    return {
        "count": len(lengths),
        "max_chars": max(lengths) if lengths else 0,
        "over_limit": sum(1 for n in lengths if n > max_chars),
        "empty": sum(1 for t in texts if not str(t or "").strip()),
    }
