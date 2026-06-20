"""Study endpoints: live metric summary + CSV/chart report generation.

The research question -- do LLM hints help without giving the answer away -- is
answered here by three metric families: hint quality by source (treatment vs
control), autograder/human grading agreement, and over-hinting leakage.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ..auth import require_instructor
from ..db import get_session
from ..models import User
from ..research import metrics, reports, collect

router = APIRouter(prefix="/api/research", tags=["research"])


def _compute(session: Session):
    rows = collect.hint_rating_rows(session)
    groups = metrics.group_hint_stats(rows)
    auto, human = collect.grading_pairs(session)
    ga = metrics.grading_agreement(auto, human)
    la = metrics.leak_agreement(rows)
    return rows, groups, ga, la


@router.get("/summary")
def summary(session: Session = Depends(get_session),
            _: User = Depends(require_instructor)):
    rows, groups, ga, la = _compute(session)

    # effect sizes: llm vs baseline on helpfulness/correctness
    def _vals(src, key):
        return [r[key] for r in rows if r["source"] == src and r.get(key)]

    effect = {}
    for key in ("helpfulness", "correctness"):
        llm = _vals("llm", key)
        base = _vals("baseline", key)
        if llm and base:
            effect[key] = {
                "llm_mean": round(metrics.mean(llm), 3),
                "baseline_mean": round(metrics.mean(base), 3),
                "cliffs_delta": round(metrics.cliffs_delta(llm, base), 3),
            }

    return {
        "n_rated_hints": len(rows),
        "hint_quality_by_source": [g.__dict__ for g in groups],
        "grading_agreement": ga.__dict__,
        "leak_agreement": la.__dict__,
        "llm_vs_baseline": effect,
    }


@router.post("/reports")
def generate_reports(session: Session = Depends(get_session),
                     _: User = Depends(require_instructor)):
    rows, groups, ga, la = _compute(session)
    written = []
    written.append(str(reports.write_hint_quality_csv(groups)))
    written.append(str(reports.write_grading_agreement_csv(ga)))
    written.append(str(reports.write_leak_agreement_csv(la)))
    written.append(str(reports.write_per_hint_csv(rows)))

    charts = []
    c1 = reports.chart_hint_quality(groups)
    c2 = reports.chart_leak_rates(groups)
    if c1:
        charts.append(str(c1))
    if c2:
        charts.append(str(c2))

    return {"csv_files": written, "charts": charts,
            "charts_enabled": bool(charts),
            "summary_text": reports.summary_text(groups, ga, la)}
