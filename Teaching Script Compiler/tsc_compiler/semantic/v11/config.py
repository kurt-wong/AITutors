"""Frozen V1.1 candidate configuration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from ..retrieval import SemanticConfig

INDEX_VERSION = "v1.1-candidate/1"


@dataclass(frozen=True)
class V11Config:
    exact_dense: float = 0.74
    exact_lexical: float = 0.55
    exact_margin: float = 0.02
    similar_dense: float = 0.85
    similar_lexical: float = 0.55
    similar_margin: float = 0.0
    exact_number_overlap: float = 0.5
    exact_option_overlap: float = 0.40
    top_k: int = 10

    def as_dict(self) -> dict:
        return {
            **asdict(self),
            "index_version": INDEX_VERSION,
        }

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_semantic_config(self) -> SemanticConfig:
        return SemanticConfig(
            exact_dense=self.exact_dense,
            exact_lexical=self.exact_lexical,
            exact_margin=self.exact_margin,
            similar_dense=self.similar_dense,
            similar_lexical=self.similar_lexical,
            similar_margin=self.similar_margin,
            top_k=self.top_k,
            exact_number_overlap=self.exact_number_overlap,
            exact_option_overlap=self.exact_option_overlap,
        )
