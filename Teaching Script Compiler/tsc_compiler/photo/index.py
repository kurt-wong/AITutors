"""Candidate retrieval index over the published QCore catalog.

Layered by design (spec §10):

1. lexical — IDF-weighted token coverage over CJK n-grams, numbers, LaTeX
   commands and ASCII terms;
2. semantic-light — character 3-gram cosine over normalized text (a real
   vector comparison, no external embedding service in this round);
3. structural — image / table / math presence must agree.

The index is built from QCore catalog entries only. Nothing in the query can
add a document.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ..normalize import normalize_for_search

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_LATEX = re.compile(r"\\[A-Za-z]+")
_ASCII = re.compile(r"[a-zA-Z]{2,}")


def tokenize(text: str) -> list[str]:
    text = normalize_for_search(text)
    tokens: list[str] = []
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            tokens.append("z:" + run)
        else:
            for i in range(len(run) - 1):
                tokens.append("z:" + run[i : i + 2])
    for number in _NUMBER.findall(text):
        tokens.append("n:" + number)
    for command in _LATEX.findall(text):
        tokens.append("c:" + command)
    for word in _ASCII.findall(text):
        tokens.append("w:" + word.lower())
    return tokens


def char_ngrams(text: str, n: int = 3) -> Counter:
    compact = re.sub(r"\s+", "", normalize_for_search(text))
    return Counter(compact[i : i + n] for i in range(max(0, len(compact) - n + 1)))


@dataclass
class Document:
    question_id: str
    tokens: Counter
    length: int
    ngrams: Counter
    text: str
    has_image: bool
    has_table: bool
    has_math: bool
    entry: dict[str, Any] = field(default_factory=dict)


class SearchIndex:
    def __init__(self, documents: list[Document]):
        self.documents = documents
        self.df: Counter = Counter()
        for doc in documents:
            self.df.update(set(doc.tokens))
        self.n_docs = max(1, len(documents))
        self.avg_length = sum(d.length for d in documents) / self.n_docs or 1.0

    @classmethod
    def from_catalog(cls, catalog: list[dict[str, Any]]) -> "SearchIndex":
        documents = []
        for entry in catalog:
            text = " ".join(
                part
                for part in (
                    entry.get("stem_text"),
                    entry.get("material_text"),
                    entry.get("options_text"),
                    entry.get("explanation_text"),
                )
                if part
            )
            tokens = Counter(tokenize(text))
            documents.append(
                Document(
                    question_id=entry["question_id"],
                    tokens=tokens,
                    length=sum(tokens.values()),
                    ngrams=char_ngrams(text),
                    text=text,
                    has_image=bool(entry.get("has_image")),
                    has_table=bool(entry.get("has_table")),
                    has_math=bool(entry.get("has_math")),
                    entry=entry,
                )
            )
        return cls(documents)

    def _idf(self, token: str) -> float:
        df = self.df.get(token, 0)
        return math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))

    def _idf_max(self) -> float:
        return math.log(1 + (self.n_docs + 0.5) / 0.5)

    def lexical(self, doc: Document, query_tokens: Counter) -> tuple[float, list[str]]:
        matched: list[str] = []
        total_weight = 0.0
        matched_weight = 0.0
        for token, count in query_tokens.items():
            weight = self._idf(token) * min(count, 3)
            total_weight += weight
            if token in doc.tokens:
                matched_weight += weight
                matched.append(token)
        if total_weight == 0:
            return 0.0, []
        coverage = matched_weight / total_weight
        # Blend coverage with a BM25 term so repeated strong matches still rank.
        k1, b = 1.2, 0.75
        bm25 = 0.0
        for token in matched:
            tf = doc.tokens[token]
            denom = tf + k1 * (1 - b + b * doc.length / self.avg_length)
            bm25 += self._idf(token) * tf * (k1 + 1) / max(denom, 1e-9)
        bm25_norm = bm25 / (bm25 + 6.0) if bm25 else 0.0
        return 0.65 * coverage + 0.35 * bm25_norm, matched

    def semantic(self, doc: Document, query_ngrams: Counter) -> float:
        if not query_ngrams or not doc.ngrams:
            return 0.0
        common = set(query_ngrams) & set(doc.ngrams)
        numerator = sum(query_ngrams[g] * doc.ngrams[g] for g in common)
        q_norm = math.sqrt(sum(v * v for v in query_ngrams.values()))
        d_norm = math.sqrt(sum(v * v for v in doc.ngrams.values()))
        return numerator / max(q_norm * d_norm, 1e-9)

    def structural(
        self,
        doc: Document,
        *,
        query_has_image: bool,
        query_has_table: bool,
        query_has_math: bool,
    ) -> float:
        pairs = [
            (query_has_image, doc.has_image),
            (query_has_table, doc.has_table),
            (query_has_math, doc.has_math),
        ]
        score = 0.0
        for query_flag, doc_flag in pairs:
            if query_flag and doc_flag:
                score += 1.0
            elif query_flag and not doc_flag:
                score += 0.0
            elif not query_flag and doc_flag:
                score += 0.3
            else:
                score += 0.5
        return score / len(pairs)

    def query(
        self,
        text: str,
        *,
        limit: int = 8,
        query_has_image: bool = False,
        query_has_table: bool = False,
        query_has_math: bool = True,
        exclude: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        query_tokens = Counter(tokenize(text))
        query_ngrams = char_ngrams(text)
        scored: list[dict[str, Any]] = []
        for doc in self.documents:
            if exclude and doc.question_id in exclude:
                continue
            lexical, matched = self.lexical(doc, query_tokens)
            sem = self.semantic(doc, query_ngrams)
            struct = self.structural(
                doc,
                query_has_image=query_has_image,
                query_has_table=query_has_table,
                query_has_math=query_has_math,
            )
            base = 0.55 * lexical + 0.25 * sem + 0.20 * struct
            scored.append(
                {
                    "question_id": doc.question_id,
                    "score": round(base, 4),
                    "score_parts": {
                        "lexical": round(lexical, 4),
                        "semantic": round(sem, 4),
                        "structure": round(struct, 4),
                        "llm": None,
                    },
                    "matched_tokens": matched,
                    "entry": doc.entry,
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]
