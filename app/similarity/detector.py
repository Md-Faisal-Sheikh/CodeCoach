"""Multi-signal plagiarism detector.

Combines three complementary signals into one score per submission pair:
  * winnow  -- token k-gram winnowing overlap (renaming/reformatting robust);
  * ast     -- Python AST node-type overlap (structural; renaming-immune);
  * tfidf   -- TF-IDF cosine over token shingles (lexical 'embedding').

Pairs above a threshold are linked into connected-component clusters that
surface likely collusion groups, not just isolated pairs."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import winnowing, ast_norm, embeddings
from .tokenizer import tokenize_code


@dataclass
class PairScore:
    a_id: int
    b_id: int
    combined: float
    winnow: float
    ast: Optional[float]
    tfidf: float


@dataclass
class Cluster:
    members: List[int]
    size: int
    max_score: float


@dataclass
class SimilarityReport:
    pairs: List[PairScore] = field(default_factory=list)
    clusters: List[Cluster] = field(default_factory=list)


def _combine(winnow: float, ast_s: Optional[float], tfidf: float) -> float:
    if ast_s is not None:
        return 0.45 * winnow + 0.35 * ast_s + 0.20 * tfidf
    return 0.60 * winnow + 0.40 * tfidf


def _components(n_ids: List[int], edges: List[Tuple[int, int]]) -> List[List[int]]:
    parent = {i: i for i in n_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups: Dict[int, List[int]] = {}
    for i in n_ids:
        groups.setdefault(find(i), []).append(i)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def analyze(submissions: List[Tuple[int, str]], language: str,
            *, pair_threshold: float = 0.35,
            cluster_threshold: float = 0.55) -> SimilarityReport:
    """submissions: list of (submission_id, source_code)."""
    ids = [sid for sid, _ in submissions]
    sources = [src for _, src in submissions]
    if len(ids) < 2:
        return SimilarityReport()

    token_lists = [tokenize_code(s, language) for s in sources]
    fps = [winnowing.fingerprints(t) for t in token_lists]
    ast_fps = [ast_norm.fingerprints(s) if language == "python" else None for s in sources]
    vecs = embeddings.embed_sources(sources, language)

    pairs: List[PairScore] = []
    cluster_edges: List[Tuple[int, int]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            w = winnowing.overlap(fps[i], fps[j])
            a_s = None
            if ast_fps[i] is not None and ast_fps[j] is not None:
                a_s = winnowing.overlap(ast_fps[i], ast_fps[j])
            t = embeddings.cosine(vecs[i], vecs[j])
            combined = _combine(w, a_s, t)
            if combined >= pair_threshold:
                pairs.append(PairScore(ids[i], ids[j], combined, w, a_s, t))
            if combined >= cluster_threshold:
                cluster_edges.append((ids[i], ids[j]))

    pairs.sort(key=lambda p: p.combined, reverse=True)
    comps = _components(ids, cluster_edges)
    score_lookup = {(p.a_id, p.b_id): p.combined for p in pairs}
    clusters = []
    for g in comps:
        mx = 0.0
        for x in range(len(g)):
            for y in range(x + 1, len(g)):
                mx = max(mx, score_lookup.get((g[x], g[y]), score_lookup.get((g[y], g[x]), 0.0)))
        clusters.append(Cluster(members=g, size=len(g), max_score=mx))
    clusters.sort(key=lambda c: c.max_score, reverse=True)
    return SimilarityReport(pairs=pairs, clusters=clusters)
