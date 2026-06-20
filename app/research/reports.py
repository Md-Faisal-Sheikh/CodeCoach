"""Turn raw study rows into CSV tables and (optionally) PNG charts.

CSV is always written with the stdlib `csv` module. Charts are attempted with
matplotlib if it is installed; if not, we skip them silently so the platform has
zero hard plotting dependency. Everything lands under data/reports/.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..config import DATA_DIR
from . import metrics


REPORT_DIR = DATA_DIR / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _write_csv(path: Path, header: Sequence[str], rows: Sequence[Sequence]) -> Path:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    return path


def write_hint_quality_csv(group_stats: Sequence[metrics.GroupStat],
                           path: Optional[Path] = None) -> Path:
    path = path or REPORT_DIR / "hint_quality_by_source.csv"
    rows = [
        [g.source, g.n, g.helpfulness_mean, g.helpfulness_std,
         g.correctness_mean, g.correctness_std, g.leak_rate,
         "" if g.reveals_rate is None else g.reveals_rate]
        for g in group_stats
    ]
    return _write_csv(
        path,
        ["source", "n", "helpfulness_mean", "helpfulness_std",
         "correctness_mean", "correctness_std", "leak_rate", "human_reveals_rate"],
        rows,
    )


def write_grading_agreement_csv(ga: metrics.GradingAgreement,
                                path: Optional[Path] = None) -> Path:
    path = path or REPORT_DIR / "grading_agreement.csv"
    rows = [
        ["n", ga.n],
        ["exact_bucket_match", _fmt(ga.exact_bucket)],
        ["adjacent_bucket_match", _fmt(ga.adjacent_bucket)],
        ["cohen_kappa_unweighted", _fmt(ga.kappa_unweighted)],
        ["cohen_kappa_weighted_linear", _fmt(ga.kappa_weighted)],
        ["pearson_r", _fmt(ga.pearson)],
        ["spearman_rho", _fmt(ga.spearman)],
        ["mae_score", _fmt(ga.mae_score)],
    ]
    return _write_csv(path, ["metric", "value"], rows)


def write_leak_agreement_csv(la: metrics.LeakAgreement,
                             path: Optional[Path] = None) -> Path:
    path = path or REPORT_DIR / "leak_agreement.csv"
    rows = [
        ["n_human_rated", la.n],
        ["auto_leak_rate", _fmt(la.auto_leak_rate)],
        ["human_reveal_rate", _fmt(la.human_reveal_rate)],
        ["auto_vs_human_agreement", _fmt(la.agreement)],
        ["cohen_kappa", _fmt(la.kappa)],
    ]
    return _write_csv(path, ["metric", "value"], rows)


def write_per_hint_csv(rows: Sequence[dict], path: Optional[Path] = None) -> Path:
    """Long-format dump: one row per rated hint. Useful for external analysis."""
    path = path or REPORT_DIR / "hint_ratings_long.csv"
    header = ["hint_id", "submission_id", "source", "level", "helpfulness",
              "correctness", "reveals_solution", "leaked", "leakage_score"]
    out = []
    for r in rows:
        out.append([
            r.get("hint_id", ""), r.get("submission_id", ""), r.get("source", ""),
            r.get("level", ""), r.get("helpfulness", ""), r.get("correctness", ""),
            "" if r.get("reveals_solution") is None else int(bool(r["reveals_solution"])),
            int(bool(r.get("leaked"))), r.get("leakage_score", ""),
        ])
    return _write_csv(path, header, out)


def _fmt(v: Optional[float]) -> str:
    return "" if v is None else f"{v:.4f}"


# --------------------------------------------------------------------------- #
# optional charts
# --------------------------------------------------------------------------- #
def _matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except Exception:
        return None


def chart_hint_quality(group_stats: Sequence[metrics.GroupStat],
                       path: Optional[Path] = None) -> Optional[Path]:
    plt = _matplotlib()
    if plt is None or not group_stats:
        return None
    path = path or REPORT_DIR / "hint_quality.png"
    sources = [g.source for g in group_stats]
    x = range(len(sources))
    helx = [g.helpfulness_mean for g in group_stats]
    corx = [g.correctness_mean for g in group_stats]
    fig, ax = plt.subplots(figsize=(7, 4))
    width = 0.38
    ax.bar([i - width / 2 for i in x], helx, width, label="Helpfulness")
    ax.bar([i + width / 2 for i in x], corx, width, label="Correctness")
    ax.set_xticks(list(x))
    ax.set_xticklabels(sources)
    ax.set_ylabel("Mean rating (1-5)")
    ax.set_title("Hint quality by source")
    ax.set_ylim(0, 5)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def chart_leak_rates(group_stats: Sequence[metrics.GroupStat],
                     path: Optional[Path] = None) -> Optional[Path]:
    plt = _matplotlib()
    if plt is None or not group_stats:
        return None
    path = path or REPORT_DIR / "leak_rates.png"
    sources = [g.source for g in group_stats]
    leaks = [g.leak_rate for g in group_stats]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(sources, leaks, color="#c0392b")
    ax.set_ylabel("Leak rate")
    ax.set_title("Over-hinting (answer leakage) rate by source")
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def summary_text(group_stats: Sequence[metrics.GroupStat],
                 ga: metrics.GradingAgreement,
                 la: metrics.LeakAgreement) -> str:
    """Human-readable digest printed at the end of a study run."""
    buf = io.StringIO()
    buf.write("HINT QUALITY BY SOURCE\n")
    buf.write(f"  {'source':<10} {'n':>4} {'help':>6} {'corr':>6} {'leak':>6}\n")
    for g in group_stats:
        buf.write(f"  {g.source:<10} {g.n:>4} {g.helpfulness_mean:>6.2f} "
                  f"{g.correctness_mean:>6.2f} {g.leak_rate:>6.2f}\n")
    buf.write("\nAUTOGRADER vs HUMAN\n")
    buf.write(f"  n={ga.n}  exact={_fmt(ga.exact_bucket)}  "
              f"adjacent={_fmt(ga.adjacent_bucket)}\n")
    buf.write(f"  kappa(unw)={_fmt(ga.kappa_unweighted)}  "
              f"kappa(wt)={_fmt(ga.kappa_weighted)}  "
              f"pearson={_fmt(ga.pearson)}  spearman={_fmt(ga.spearman)}\n")
    buf.write("\nLEAK FLAG vs HUMAN JUDGEMENT\n")
    buf.write(f"  n={la.n}  auto={_fmt(la.auto_leak_rate)}  "
              f"human={_fmt(la.human_reveal_rate)}  "
              f"agreement={_fmt(la.agreement)}  kappa={_fmt(la.kappa)}\n")
    return buf.getvalue()
