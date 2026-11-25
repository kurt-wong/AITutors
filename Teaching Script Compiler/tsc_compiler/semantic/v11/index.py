"""Independent V1.1 candidate index (namespace + model/config binding)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..retrieval import SemanticIndex
from .config import INDEX_VERSION, V11Config


class V11IndexError(RuntimeError):
    pass


class V11IndexMismatch(V11IndexError):
    pass


def _canonical_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class V11Index:
    docs: list[Any]
    embeddings: np.ndarray
    config: V11Config
    adapter: Any
    meta: dict[str, Any]
    semantic_index: SemanticIndex

    # ---------------------------------------------------------------- build
    @classmethod
    def build(
        cls,
        catalog: list[dict[str, Any]],
        adapter: Any,
        out_dir: str | Path,
        *,
        namespace: str = "semantic_v11_gemma2",
    ) -> "V11Index":
        identity = adapter.identify()
        base = SemanticIndex.from_catalog(catalog, embedder=None)
        if not base.docs:
            raise V11IndexError("empty catalog; refusing to build an empty index")
        texts = [doc.text for doc in base.docs]
        embeddings = adapter.encode(texts, batch_size=8, is_query=False)
        embeddings = np.asarray(embeddings, dtype=np.float32)
        if embeddings.ndim != 2 or embeddings.shape[0] != len(base.docs):
            raise V11IndexError(
                f"embedding shape {embeddings.shape} does not match docs {len(base.docs)}"
            )
        if embeddings.shape[1] != identity.api_dim:
            raise V11IndexError(
                f"embedding dim {embeddings.shape[1]} != probed model dim {identity.api_dim}"
            )
        config = V11Config()
        corpus = [
            {
                "question_id": doc.question_id,
                "revision_id": doc.revision_id,
                "content_hash": (doc.entry or {}).get("content_hash"),
            }
            for doc in base.docs
        ]
        docs_payload = [
            {
                "question_id": doc.question_id,
                "revision_id": doc.revision_id,
                "subject": doc.subject,
                "question_type": doc.question_type,
                "printed_number": doc.printed_number,
                "source_document_id": doc.source_document_id,
                "text": doc.text,
                "entry": doc.entry,
            }
            for doc in base.docs
        ]
        meta = {
            "index_version": INDEX_VERSION,
            "namespace": namespace,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": identity.as_dict(),
            "dim": int(embeddings.shape[1]),
            "document_count": len(base.docs),
            "config": config.as_dict(),
            "config_hash": config.config_hash,
            "corpus_sha256": _canonical_hash(corpus),
            "docs_sha256": _canonical_hash(docs_payload),
            "embedding_dtype": str(embeddings.dtype),
            "stores_qcore_fact": False,
        }
        path = Path(out_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / "docs.json").write_text(
            json.dumps(docs_payload, ensure_ascii=False), encoding="utf-8"
        )
        np.save(path / "embeddings.npy", embeddings)
        (path / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return cls._assemble(base.docs, embeddings, config, adapter, meta)

    @classmethod
    def _assemble(cls, docs, embeddings, config: V11Config, adapter, meta) -> "V11Index":
        semantic = SemanticIndex(
            docs,
            embeddings=embeddings,
            config=config.to_semantic_config(),
            embedder=adapter,
        )
        return cls(
            docs=docs,
            embeddings=embeddings,
            config=config,
            adapter=adapter,
            meta=meta,
            semantic_index=semantic,
        )

    # ----------------------------------------------------------------- load
    @classmethod
    def load(
        cls,
        directory: str | Path,
        adapter: Any,
        *,
        expected_config: V11Config | None = None,
        verify_model: bool = True,
    ) -> "V11Index":
        path = Path(directory)
        meta_path = path / "meta.json"
        if not meta_path.is_file():
            raise V11IndexError(f"index meta missing: {meta_path}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("index_version") != INDEX_VERSION:
            raise V11IndexMismatch(f"index_version mismatch: {meta.get('index_version')}")
        if expected_config is not None and meta.get("config_hash") != expected_config.config_hash:
            raise V11IndexMismatch("index config_hash does not match the frozen V1.1 config")
        identity = adapter.identify()
        model_meta = meta.get("model") or {}
        if verify_model:
            if model_meta.get("name") != identity.name:
                raise V11IndexMismatch(
                    f"model name mismatch: index={model_meta.get('name')} adapter={identity.name}"
                )
            if model_meta.get("digest") != identity.digest:
                raise V11IndexMismatch(
                    "model digest mismatch: index and running Ollama model differ"
                )
        embeddings = np.load(path / "embeddings.npy").astype(np.float32)
        if embeddings.ndim != 2 or embeddings.shape[1] != int(meta.get("dim") or -1):
            raise V11IndexMismatch(
                f"embedding dim {embeddings.shape} != declared dim {meta.get('dim')}"
            )
        if verify_model and embeddings.shape[1] != identity.api_dim:
            raise V11IndexMismatch(
                f"embedding dim {embeddings.shape[1]} != adapter dim {identity.api_dim}"
            )
        docs_payload = json.loads((path / "docs.json").read_text(encoding="utf-8"))
        from ..retrieval import SemanticDoc  # local import keeps package boundaries clear

        docs = [
            SemanticDoc(
                question_id=row["question_id"],
                revision_id=row.get("revision_id") or "",
                subject=row.get("subject") or "unknown",
                question_type=row.get("question_type"),
                printed_number=row.get("printed_number"),
                source_document_id=row.get("source_document_id"),
                text=row["text"],
                entry=row.get("entry") or {},
            )
            for row in docs_payload
        ]
        if len(docs) != embeddings.shape[0]:
            raise V11IndexMismatch("docs count != embeddings count")
        if _canonical_hash(docs_payload) != meta.get("docs_sha256"):
            raise V11IndexMismatch("docs_sha256 mismatch; index files were modified")
        config = expected_config or V11Config()
        return cls._assemble(docs, embeddings, config, adapter, meta)

    # --------------------------------------------------------------- search
    def search(self, text: str, *, top_k: int | None = None, exclude_ids: set[str] | None = None):
        return self.semantic_index.search(text, top_k=top_k, exclude_ids=exclude_ids)

    def identity_summary(self) -> dict[str, Any]:
        return {
            "namespace": self.meta.get("namespace"),
            "index_version": self.meta.get("index_version"),
            "model": self.meta.get("model"),
            "dim": self.meta.get("dim"),
            "document_count": self.meta.get("document_count"),
            "config_hash": self.meta.get("config_hash"),
            "corpus_sha256": self.meta.get("corpus_sha256"),
            "created_at": self.meta.get("created_at"),
        }
