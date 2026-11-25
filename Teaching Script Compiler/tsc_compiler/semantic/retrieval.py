"""Semantic Retrieval V1: question representation, Top-K retrieval, 3-state decision.

Layers:
  1. dense  — bge-small-zh-v1.5 cosine (local, optional);
  2. lexical— IDF/BM25 token coverage over CJK bigrams/numbers/LaTeX/ASCII
              (reuses the frozen photo-search index);
  3. char   — character 3-gram cosine (already inside the lexical base).

Decision contract (fail-closed):
  * ``exact``   — same question; may enter the QCore teaching path;
  * ``similar`` — related question worth showing as a reference; never an identity;
  * ``unknown`` — no reliable exact/similar result; the caller must not teach.

``similar`` is never reported as ``exact``: identity requires both dense and
lexical evidence plus a margin over the runner-up. A tie at the top is
``unknown``, not a coin flip.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from ..normalize import normalize_for_search
from ..photo.index import SearchIndex, tokenize
from .embedding import DenseEmbedder, cosine_scores

DEFAULT_TOP_K = 10
#: Calibrated on 20 real photo-crop OCR queries + 37 real-phone negatives:
#: positives have lexical 0.60–0.86; negatives reach dense 0.91 but lexical
#: only 0.35–0.51. Identity therefore needs BOTH signals.
DEFAULT_EXACT_DENSE = 0.84
DEFAULT_EXACT_LEXICAL = 0.55
DEFAULT_EXACT_MARGIN = 0.02
DEFAULT_SIMILAR_DENSE = 0.80
DEFAULT_SIMILAR_LEXICAL = 0.55
DEFAULT_SIMILAR_MARGIN = 0.0

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_OPTION_MARK = re.compile(r"(?m)^\s*([A-DＡ-Ｄ])\s*[.、．:：]\s*")


def _parse_options(text: str) -> dict[str, str]:
    marks = list(_OPTION_MARK.finditer(str(text or "")))
    if len(marks) < 2:
        return {}
    out: dict[str, str] = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        label = mark.group(1).translate(str.maketrans("ＡＢＣＤ", "ABCD"))
        out[label] = normalize_for_search(str(text)[mark.end() : end])[:300]
    return out


def _char_cosine(left: str, right: str, n: int = 3) -> float:
    a = re.sub(r"\s+", "", left)
    b = re.sub(r"\s+", "", right)
    if len(a) < n or len(b) < n:
        return 0.0
    ca = {a[i : i + n]: 1 for i in range(len(a) - n + 1)}
    cb = {b[i : i + n]: 1 for i in range(len(b) - n + 1)}
    common = set(ca) & set(cb)
    return len(common) / max(len(set(ca) | set(cb)), 1)


def _option_overlap(query: str, entry: dict[str, Any]) -> float | None:
    """Mean per-label character overlap of A–D options, or None if not applicable."""
    query_options = _parse_options(query)
    doc_options = _parse_options(str(entry.get("options_text") or ""))
    if len(query_options) < 2 or len(doc_options) < 2:
        return None
    labels = sorted(set(query_options) & set(doc_options))
    if len(labels) < 2:
        return 0.0
    return sum(_char_cosine(query_options[k], doc_options[k]) for k in labels) / len(labels)


@dataclass(frozen=True)
class SemanticConfig:
    exact_dense: float = DEFAULT_EXACT_DENSE
    exact_lexical: float = DEFAULT_EXACT_LEXICAL
    exact_margin: float = DEFAULT_EXACT_MARGIN
    similar_dense: float = DEFAULT_SIMILAR_DENSE
    similar_lexical: float = DEFAULT_SIMILAR_LEXICAL
    similar_margin: float = DEFAULT_SIMILAR_MARGIN
    top_k: int = DEFAULT_TOP_K
    #: Require this Jaccard overlap of numeric tokens when the query carries
    #: numbers (a cheap, source-grounded identity guard).
    exact_number_overlap: float = 0.5
    #: When both query and candidate expose A–D options, their per-label
    #: character overlap must reach this floor before identity is granted.
    exact_option_overlap: float | None = 0.40

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SemanticDoc:
    question_id: str
    revision_id: str
    subject: str
    question_type: str | None
    printed_number: str | None
    source_document_id: str | None
    text: str
    entry: dict[str, Any] = field(default_factory=dict)


def doc_text(entry: dict[str, Any]) -> str:
    """Identity text: stem + material + options (never the explanation).

    The explanation is part of the catalog for provenance, but including it in
    the identity vector lets an explanation from question A retrieve question
    B just because they discuss the same concept.
    """
    return "\n".join(
        part
        for part in (
            entry.get("stem_text"),
            entry.get("material_text"),
            entry.get("options_text"),
        )
        if part
    ).strip()


def _numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(normalize_for_search(text)))


def _number_overlap(query: str, doc: str) -> float:
    """Coverage of the *document's* numbers by the query.

    A photo crop may include option numbers the catalog stem does not carry;
    that is extra query noise, not evidence against identity. What matters is
    that every number the candidate question declares is present in the query.
    """
    q, d = _numbers(query), _numbers(doc)
    if not d:
        return 1.0
    if not q:
        return 0.0
    return len(q & d) / len(d)


def _contains_identity(query: str, doc: str) -> bool:
    q = re.sub(r"\s+", "", normalize_for_search(query))
    d = re.sub(r"\s+", "", normalize_for_search(doc))
    if len(q) < 12 or len(d) < 12:
        return False
    shorter, longer = (q, d) if len(q) <= len(d) else (d, q)
    return shorter in longer and len(shorter) / len(longer) >= 0.6


class SemanticIndex:
    def __init__(
        self,
        docs: list[SemanticDoc],
        *,
        embeddings: np.ndarray | None = None,
        config: SemanticConfig | None = None,
        embedder: DenseEmbedder | None = None,
    ) -> None:
        self.docs = docs
        self.config = config or SemanticConfig()
        self.embeddings = embeddings
        self.embedder = embedder
        self.lexical = SearchIndex.from_catalog([d.entry for d in docs])

    # ------------------------------------------------------------------ build
    @classmethod
    def from_catalog(
        cls,
        catalog: Iterable[dict[str, Any]],
        *,
        embedder: DenseEmbedder | None = None,
        config: SemanticConfig | None = None,
    ) -> "SemanticIndex":
        docs: list[SemanticDoc] = []
        for entry in catalog:
            text = doc_text(entry)
            if not text:
                continue
            docs.append(
                SemanticDoc(
                    question_id=str(entry["question_id"]),
                    revision_id=str(entry.get("revision_id") or ""),
                    subject=str(entry.get("subject") or "unknown"),
                    question_type=entry.get("question_type"),
                    printed_number=entry.get("printed_number"),
                    source_document_id=entry.get("source_document_id"),
                    text=text,
                    entry=entry,
                )
            )
        embeddings = None
        if embedder is not None and embedder.available and docs:
            embeddings = embedder.encode([d.text for d in docs], is_query=False)
        return cls(docs, embeddings=embeddings, config=config, embedder=embedder)

    # ------------------------------------------------------------------- I/O
    def save(self, directory: str | Path) -> dict[str, Any]:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        docs_path = path / "docs.json"
        docs_path.write_text(
            json.dumps(
                [
                    {
                        "question_id": d.question_id,
                        "revision_id": d.revision_id,
                        "subject": d.subject,
                        "question_type": d.question_type,
                        "printed_number": d.printed_number,
                        "source_document_id": d.source_document_id,
                        "text": d.text,
                        "entry": d.entry,
                    }
                    for d in self.docs
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        if self.embeddings is not None:
            np.save(path / "embeddings.npy", self.embeddings)
        meta = {
            "documents": len(self.docs),
            "dense": self.embeddings is not None,
            "dim": int(self.embeddings.shape[1]) if self.embeddings is not None else 0,
            "config": self.config.as_dict(),
        }
        (path / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return meta

    @classmethod
    def load(
        cls,
        directory: str | Path,
        config: SemanticConfig | None = None,
        *,
        embedder: DenseEmbedder | None = None,
    ) -> "SemanticIndex":
        path = Path(directory)
        raw = json.loads((path / "docs.json").read_text(encoding="utf-8"))
        docs = [
            SemanticDoc(
                question_id=r["question_id"],
                revision_id=r.get("revision_id") or "",
                subject=r.get("subject") or "unknown",
                question_type=r.get("question_type"),
                printed_number=r.get("printed_number"),
                source_document_id=r.get("source_document_id"),
                text=r["text"],
                entry=r.get("entry") or {},
            )
            for r in raw
        ]
        embeddings = None
        emb_path = path / "embeddings.npy"
        if emb_path.is_file():
            embeddings = np.load(emb_path).astype(np.float32)
        return cls(docs, embeddings=embeddings, config=config, embedder=embedder)

    # -------------------------------------------------------------- retrieval
    def search(
        self,
        text: str,
        *,
        top_k: int | None = None,
        exclude_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        cfg = self.config
        query = str(text or "").strip()
        if not query:
            return {
                "decision": "unknown",
                "reason": "empty_query",
                "exact": None,
                "similar": [],
                "candidates": [],
                "thresholds": cfg.as_dict(),
            }
        limit = int(top_k or cfg.top_k)
        lexical_rows = self.lexical.query(query, limit=len(self.docs) or 1)
        lexical_by_id = {row["question_id"]: row for row in lexical_rows}
        dense = None
        if self.embeddings is not None and self.embeddings.size and self.embedder is not None:
            qv = self.embedder.encode([query], is_query=True)[0]
            dense = cosine_scores(self.embeddings, qv)

        candidates: list[dict[str, Any]] = []
        for i, doc in enumerate(self.docs):
            if exclude_ids and doc.question_id in exclude_ids:
                continue
            lex_row = lexical_by_id.get(doc.question_id) or {}
            lex_score = float(lex_row.get("score") or 0.0)
            lex_parts = lex_row.get("score_parts") or {}
            d = float(dense[i]) if dense is not None else 0.0
            score = 0.65 * d + 0.35 * lex_score if dense is not None else lex_score
            identity_text = "\n".join(
                part
                for part in (
                    doc.entry.get("stem_text"),
                    doc.entry.get("material_text"),
                )
                if part
            )
            candidates.append(
                {
                    "question_id": doc.question_id,
                    "revision_id": doc.revision_id,
                    "subject": doc.subject,
                    "question_type": doc.question_type,
                    "printed_number": doc.printed_number,
                    "source_document_id": doc.source_document_id,
                    "score": round(score, 4),
                    "dense": round(d, 4),
                    "lexical": round(lex_score, 4),
                    "lexical_parts": lex_parts,
                    "number_overlap": round(_number_overlap(query, identity_text or doc.text), 3),
                    "option_overlap": (
                        None
                        if (opt := _option_overlap(query, doc.entry)) is None
                        else round(opt, 3)
                    ),
                    "matched_tokens": (lex_row.get("matched_tokens") or [])[:8],
                }
            )
        candidates.sort(key=lambda c: c["score"], reverse=True)
        ranked = candidates[: max(limit, 2)]
        if not ranked:
            return {
                "decision": "unknown",
                "reason": "empty_index",
                "exact": None,
                "similar": [],
                "candidates": [],
                "thresholds": cfg.as_dict(),
            }

        top = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        margin = top["score"] - (second["score"] if second else 0.0)
        dense_margin = top["dense"] - (second["dense"] if second else 0.0)

        def _strong_exact(c: dict[str, Any]) -> bool:
            parts = c.get("lexical_parts") or {}
            if dense is not None:
                return (
                    c["dense"] >= cfg.exact_dense
                    and parts.get("lexical", 0.0) >= cfg.exact_lexical
                )
            # Sparse fallback: identity needs both lexical and character-ngram
            # evidence, not just one high aggregate score.
            return (
                c["lexical"] >= 0.75
                and parts.get("semantic", 0.0) >= 0.85
                and parts.get("lexical", 0.0) >= 0.70
            )

        # Byte-identical duplicates are a data issue (merge), not a retrieval
        # ambiguity: teach the top one and tag the duplicate group.
        duplicate_group = False
        if second:
            top_norm = re.sub(r"\s+", "", normalize_for_search(self._doc_text(top["question_id"])))
            second_norm = re.sub(r"\s+", "", normalize_for_search(self._doc_text(second["question_id"])))
            duplicate_group = len(top_norm) > 20 and top_norm == second_norm

        # A stem-only query has no option layer to compare; identity then needs
        # a very high dense score (OCR crops include options in the product
        # path, so this only tightens fragment/manual queries).
        query_has_options = len(_parse_options(query)) >= 2
        contains = _contains_identity(query, self._doc_text(top["question_id"]))
        option_ok = True
        if query_has_options and top.get("option_overlap") is not None:
            option_ok = top["option_overlap"] >= cfg.exact_option_overlap
        stem_only_high = (
            query_has_options
            or top["dense"] >= 0.93
            or duplicate_group
            or contains
        )
        exact_ok = (
            stem_only_high
            and _strong_exact(top)
            and option_ok
            and (
                margin >= cfg.exact_margin
                or dense_margin >= cfg.exact_margin
                or duplicate_group
            )
            and top["number_overlap"] >= cfg.exact_number_overlap
        )
        # A second candidate that also looks exact makes identity ambiguous
        # only when it is genuinely close; a merely floor-clearing runner-up
        # does not outrank a clearly better top-1.
        second_exact = bool(second and _strong_exact(second) and not duplicate_group)
        second_contends = bool(
            second_exact and (margin < cfg.exact_margin or dense_margin < cfg.exact_margin)
        )

        decision = "unknown"
        reason = "no_reliable_match"
        if second_contends:
            decision, reason = "unknown", "ambiguous_top2_exact"
        elif exact_ok:
            decision, reason = "exact", "dense+lexical+margin"
        elif (
            (top["dense"] >= cfg.similar_dense if dense is not None else top["lexical"] >= 0.60)
            and top["lexical_parts"].get("lexical", 0.0) >= cfg.similar_lexical
            and margin >= cfg.similar_margin
        ):
            decision, reason = "similar", "dense>=similar_threshold"

        # Source-containment is a strong identity signal but only when it
        # agrees with the numeric guard; it can rescue a short OCR query.
        if decision == "unknown" and contains and top["number_overlap"] >= 0.99 and not second_exact:
            if top["dense"] >= cfg.similar_dense if dense is not None else True:
                decision, reason = "exact", "normalized_text_containment"

        for i, c in enumerate(ranked):
            if i == 0 and decision == "exact":
                c["relation"] = "exact"
            elif i < 3 and decision in {"exact", "similar"} and c["score"] >= cfg.similar_dense * 0.8:
                c["relation"] = "similar"
            else:
                c["relation"] = "below_threshold"
        exact = ranked[0] if decision == "exact" else None
        similar = [
            c
            for i, c in enumerate(ranked)
            if c["relation"] == "similar" and (exact is None or c["question_id"] != exact["question_id"])
        ][:3]
        return {
            "decision": decision,
            "reason": reason,
            "query": query,
            "exact": exact,
            "similar": similar,
            "candidates": ranked[:limit],
            "top1_margin": round(margin, 4),
            "duplicate_group": duplicate_group,
            "thresholds": cfg.as_dict(),
            "dense_enabled": dense is not None,
        }

    def _doc_text(self, question_id: str) -> str:
        for d in self.docs:
            if d.question_id == question_id:
                return d.text
        return ""
