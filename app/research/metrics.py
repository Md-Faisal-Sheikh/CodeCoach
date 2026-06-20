"""Pure-Python statistics for the study. No numpy/scipy dependency.

Covers the three measurable claims:
  * autograder vs human agreement  -> Cohen's kappa (weighted + unweighted),
    exact-match rate, adjacent (+/-1 bucket) rate, Pearson & Spearman on scores.
  * hint quality                   -> mean helpfulness / correctness per source
    (baseline vs llm vs heuristic), with n and std.
  * over-hinting                   -> leakage rate per source, plus agreement
    between the automated leak flag and human "reveals_solution" judgements.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


# --------------------------------------------------------------------------- #
# basic descriptive helpers
# --------------------------------------------------------------------------- #
def mean(xs: Sequence[float]) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs: Sequence[float]) -> float:
    xs = list(xs)
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _rank(xs: Sequence[float]) -> List[float]:
    """Fractional (average) ranks, 1-based, ties shared."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    return pearson(_rank(xs), _rank(ys))


# --------------------------------------------------------------------------- #
# agreement / kappa
# --------------------------------------------------------------------------- #
def cohen_kappa(a: Sequence, b: Sequence, *, weighted: bool = False,
                categories: Optional[List] = None) -> Optional[float]:
    """Cohen's kappa between two raters over discrete labels.

    weighted=True applies linear weights over *ordered numeric* categories
    (suitable for 1..5 ratings or ordinal score buckets), so near-misses are
    penalised less than far-misses.
    """
    if len(a) != len(b) or not a:
        return None
    if categories is None:
        categories = sorted(set(a) | set(b))
    idx = {c: i for i, c in enumerate(categories)}
    k = len(categories)
    if k < 2:
        return None
    n = len(a)
    obs = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b):
        obs[idx[x]][idx[y]] += 1.0

    row = [sum(obs[i]) for i in range(k)]
    col = [sum(obs[i][j] for i in range(k)) for j in range(k)]

    if weighted:
        w = [[1.0 - abs(i - j) / (k - 1) for j in range(k)] for i in range(k)]
    else:
        w = [[1.0 if i == j else 0.0 for j in range(k)] for i in range(k)]

    po = sum(w[i][j] * obs[i][j] for i in range(k) for j in range(k)) / n
    pe = sum(w[i][j] * row[i] * col[j] for i in range(k) for j in range(k)) / (n * n)
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1.0 - pe)


def exact_match_rate(a: Sequence, b: Sequence) -> Optional[float]:
    if len(a) != len(b) or not a:
        return None
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


def adjacent_rate(a: Sequence[float], b: Sequence[float], tol: float = 1.0) -> Optional[float]:
    """Fraction of pairs within `tol` of each other (for bucketed/ordinal scores)."""
    if len(a) != len(b) or not a:
        return None
    return sum(1 for x, y in zip(a, b) if abs(x - y) <= tol) / len(a)


def mae(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    if len(a) != len(b) or not a:
        return None
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


# --------------------------------------------------------------------------- #
# study-level aggregations
# --------------------------------------------------------------------------- #
@dataclass
class GroupStat:
    source: str
    n: int
    helpfulness_mean: float
    helpfulness_std: float
    correctness_mean: float
    correctness_std: float
    leak_rate: float            # fraction of hints in this group flagged leaked
    reveals_rate: Optional[float]  # human "reveals_solution" rate, if rated


@dataclass
class GradingAgreement:
    n: int
    exact_bucket: Optional[float]
    adjacent_bucket: Optional[float]
    kappa_unweighted: Optional[float]
    kappa_weighted: Optional[float]
    pearson: Optional[float]
    spearman: Optional[float]
    mae_score: Optional[float]


@dataclass
class LeakAgreement:
    n: int                       # hints with a human reveals_solution judgement
    auto_leak_rate: float
    human_reveal_rate: float
    agreement: Optional[float]   # raw agreement of auto-flag vs human bool
    kappa: Optional[float]


def _bucket(score: float) -> int:
    """Map a [0,1] score to an ordinal bucket: 0 fail / 1 partial / 2 pass."""
    if score >= 0.999:
        return 2
    if score >= 0.5:
        return 1
    return 0


def grading_agreement(auto_scores: Sequence[float],
                      human_scores: Sequence[float]) -> GradingAgreement:
    """Compare autograder vs human on the same submissions (scores in [0,1])."""
    auto_b = [_bucket(s) for s in auto_scores]
    human_b = [_bucket(s) for s in human_scores]
    cats = [0, 1, 2]
    return GradingAgreement(
        n=len(auto_scores),
        exact_bucket=exact_match_rate(auto_b, human_b),
        adjacent_bucket=adjacent_rate(auto_b, human_b, tol=1),
        kappa_unweighted=cohen_kappa(auto_b, human_b, categories=cats),
        kappa_weighted=cohen_kappa(auto_b, human_b, weighted=True, categories=cats),
        pearson=pearson(auto_scores, human_scores),
        spearman=spearman(auto_scores, human_scores),
        mae_score=mae(auto_scores, human_scores),
    )


def group_hint_stats(rows: Sequence[dict]) -> List[GroupStat]:
    """rows: dicts with keys source, helpfulness, correctness, leaked (bool),
    reveals_solution (Optional[bool]). Aggregates per source."""
    by_src: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        by_src[r["source"]].append(r)

    out: List[GroupStat] = []
    for src, items in sorted(by_src.items()):
        helps = [i["helpfulness"] for i in items if i.get("helpfulness")]
        corrs = [i["correctness"] for i in items if i.get("correctness")]
        leaks = [1.0 if i.get("leaked") else 0.0 for i in items]
        reveals = [i["reveals_solution"] for i in items
                   if i.get("reveals_solution") is not None]
        out.append(GroupStat(
            source=src,
            n=len(items),
            helpfulness_mean=round(mean(helps), 3),
            helpfulness_std=round(stdev(helps), 3),
            correctness_mean=round(mean(corrs), 3),
            correctness_std=round(stdev(corrs), 3),
            leak_rate=round(mean(leaks), 3) if leaks else 0.0,
            reveals_rate=round(mean([1.0 if x else 0.0 for x in reveals]), 3)
            if reveals else None,
        ))
    return out


def leak_agreement(rows: Sequence[dict]) -> LeakAgreement:
    """Agreement between the automated leak flag and human reveals_solution."""
    paired = [(bool(r["leaked"]), bool(r["reveals_solution"]))
              for r in rows if r.get("reveals_solution") is not None]
    if not paired:
        return LeakAgreement(0, 0.0, 0.0, None, None)
    auto = [int(a) for a, _ in paired]
    human = [int(h) for _, h in paired]
    return LeakAgreement(
        n=len(paired),
        auto_leak_rate=round(mean(auto), 3),
        human_reveal_rate=round(mean(human), 3),
        agreement=round(exact_match_rate(auto, human), 3),
        kappa=cohen_kappa(auto, human, categories=[0, 1]),
    )


def cliffs_delta(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Non-parametric effect size (e.g. llm helpfulness vs baseline). Range
    [-1,1]; positive means xs tends to exceed ys."""
    if not xs or not ys:
        return None
    gt = lt = 0
    for x in xs:
        for y in ys:
            if x > y:
                gt += 1
            elif x < y:
                lt += 1
    return (gt - lt) / (len(xs) * len(ys))
