"""Lexical 'embedding' similarity via TF-IDF over token shingles, in pure Python.

This is the classical vector-space embedding: each submission becomes a sparse
TF-IDF vector over k-gram shingles fit on the per-problem corpus, and similarity
is cosine. A pluggable EmbeddingProvider interface lets a neural model (Voyage,
OpenAI, a local sentence-transformer) be dropped in without touching callers."""
from __future__ import annotations
import math
from collections import Counter
from typing import Dict, List, Protocol, Sequence

from .tokenizer import tokenize_code


def shingles(tokens: List[str], k: int = 3) -> List[str]:
    if len(tokens) < k:
        return ["\x1f".join(tokens)] if tokens else []
    return ["\x1f".join(tokens[i:i + k]) for i in range(len(tokens) - k + 1)]


class EmbeddingProvider(Protocol):
    def embed(self, docs: Sequence[List[str]]) -> List[Dict[str, float]]:
        """Map each token list to a sparse vector (feature -> weight)."""
        ...


class TfidfProvider:
    """Corpus-fit TF-IDF with sublinear term frequency and smoothed IDF."""

    def __init__(self, k: int = 3):
        self.k = k

    def embed(self, docs: Sequence[List[str]]) -> List[Dict[str, float]]:
        doc_shingles = [shingles(d, self.k) for d in docs]
        n = len(doc_shingles)
        df: Counter = Counter()
        for sh in doc_shingles:
            for term in set(sh):
                df[term] += 1
        idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
        vectors: List[Dict[str, float]] = []
        for sh in doc_shingles:
            tf = Counter(sh)
            vec = {t: (1.0 + math.log(c)) * idf[t] for t, c in tf.items()}
            norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            vectors.append({t: v / norm for t, v in vec.items()})
        return vectors


def cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    # iterate over the smaller vector
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(t, 0.0) for t, w in a.items())


def embed_sources(sources: Sequence[str], language: str,
                  provider: EmbeddingProvider | None = None) -> List[Dict[str, float]]:
    provider = provider or TfidfProvider()
    docs = [tokenize_code(s, language) for s in sources]
    return provider.embed(docs)
