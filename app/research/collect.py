"""Pull study-relevant rows out of the database into plain dicts that the
metrics module can consume. Keeps metrics/reports free of any ORM coupling.
"""
from __future__ import annotations

from typing import List, Tuple

from sqlmodel import Session, select

from ..models import Submission, Hint, HintRating, HumanGrade


def hint_rating_rows(session: Session) -> List[dict]:
    """One row per (rating) joined to its hint. If a hint has multiple ratings
    they each appear; downstream aggregation handles that."""
    ratings = session.exec(select(HintRating)).all()
    rows = []
    for r in ratings:
        h = session.get(Hint, r.hint_id)
        if h is None:
            continue
        rows.append({
            "hint_id": h.id,
            "submission_id": h.submission_id,
            "source": h.source,
            "level": h.level,
            "helpfulness": r.helpfulness,
            "correctness": r.correctness,
            "reveals_solution": r.reveals_solution,
            "leaked": h.leaked,
            "leakage_score": h.leakage_score,
        })
    return rows


def grading_pairs(session: Session) -> Tuple[List[float], List[float]]:
    """Aligned (auto_score, human_score) for every submission that has at least
    one human grade. Multiple human grades on a submission are averaged."""
    grades = session.exec(select(HumanGrade)).all()
    by_sub: dict = {}
    for g in grades:
        by_sub.setdefault(g.submission_id, []).append(g.score)

    auto, human = [], []
    for sub_id, hscores in by_sub.items():
        sub = session.get(Submission, sub_id)
        if sub is None:
            continue
        auto.append(sub.score)
        human.append(sum(hscores) / len(hscores))
    return auto, human
