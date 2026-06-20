"""Instructor dashboard data: roster of submissions, per-problem rollups, and
queues of hints awaiting rating / submissions awaiting human grades.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..auth import require_instructor
from ..db import get_session
from ..models import (Problem, Submission, RunResult, Hint, HintRating,
                      HumanGrade, User)

router = APIRouter(prefix="/api/instructor", tags=["instructor"])


@router.get("/overview")
def overview(session: Session = Depends(get_session),
             _: User = Depends(require_instructor)):
    problems = session.exec(select(Problem).order_by(Problem.id)).all()
    subs = session.exec(select(Submission)).all()
    hints = session.exec(select(Hint)).all()
    ratings = session.exec(select(HintRating)).all()
    grades = session.exec(select(HumanGrade)).all()

    by_problem = {}
    for p in problems:
        ps = [s for s in subs if s.problem_id == p.id]
        passed = [s for s in ps if s.status == "OK"]
        by_problem[p.id] = {
            "id": p.id, "slug": p.slug, "title": p.title,
            "difficulty": p.difficulty, "language": p.language,
            "n_submissions": len(ps),
            "n_passed": len(passed),
            "pass_rate": round(len(passed) / len(ps), 3) if ps else 0.0,
            "mean_score": round(sum(s.score for s in ps) / len(ps), 3) if ps else 0.0,
        }

    rated_ids = {r.hint_id for r in ratings}
    graded_ids = {g.submission_id for g in grades}
    llm_hints = [h for h in hints if h.source in ("llm", "heuristic")]
    leaked = [h for h in llm_hints if h.leaked]

    return {
        "totals": {
            "problems": len(problems),
            "submissions": len(subs),
            "hints": len(hints),
            "llm_or_heuristic_hints": len(llm_hints),
            "hints_rated": len(rated_ids),
            "hints_unrated": len([h for h in hints if h.id not in rated_ids]),
            "submissions_human_graded": len(graded_ids),
            "leaked_hints": len(leaked),
            "leak_rate": round(len(leaked) / len(llm_hints), 3) if llm_hints else 0.0,
        },
        "problems": list(by_problem.values()),
    }


@router.get("/submissions")
def all_submissions(problem_id: int | None = None,
                    session: Session = Depends(get_session),
                    _: User = Depends(require_instructor)):
    q = select(Submission)
    if problem_id is not None:
        q = q.where(Submission.problem_id == problem_id)
    subs = session.exec(q.order_by(Submission.id.desc())).all()
    users = {u.id: u for u in session.exec(select(User)).all()}
    graded = {g.submission_id for g in session.exec(select(HumanGrade)).all()}
    out = []
    for s in subs:
        u = users.get(s.user_id)
        out.append({
            "id": s.id, "problem_id": s.problem_id,
            "user": u.username if u else "?",
            "language": s.language, "status": s.status, "score": s.score,
            "passed_count": s.passed_count, "total_count": s.total_count,
            "human_graded": s.id in graded,
            "created_at": s.created_at.isoformat(),
        })
    return {"submissions": out}


@router.get("/hints/queue")
def hint_queue(only_unrated: bool = True,
               session: Session = Depends(get_session),
               _: User = Depends(require_instructor)):
    """Hints to rate, with their submission + problem context and leak flags."""
    hints = session.exec(select(Hint).order_by(Hint.id.desc())).all()
    rated = {r.hint_id for r in session.exec(select(HintRating)).all()}
    out = []
    for h in hints:
        if only_unrated and h.id in rated:
            continue
        sub = session.get(Submission, h.submission_id)
        prob = session.get(Problem, sub.problem_id) if sub else None
        out.append({
            "hint_id": h.id, "submission_id": h.submission_id,
            "problem": prob.title if prob else "?",
            "source": h.source, "level": h.level, "content": h.content,
            "leaked": h.leaked, "leakage_score": h.leakage_score,
            "submission_status": sub.status if sub else "?",
            "rated": h.id in rated,
        })
    return {"hints": out}


@router.get("/submissions/grade-queue")
def grade_queue(only_ungraded: bool = True,
                session: Session = Depends(get_session),
                _: User = Depends(require_instructor)):
    subs = session.exec(select(Submission).order_by(Submission.id.desc())).all()
    graded = {g.submission_id for g in session.exec(select(HumanGrade)).all()}
    users = {u.id: u for u in session.exec(select(User)).all()}
    out = []
    for s in subs:
        if only_ungraded and s.id in graded:
            continue
        u = users.get(s.user_id)
        out.append({
            "submission_id": s.id, "problem_id": s.problem_id,
            "user": u.username if u else "?", "auto_status": s.status,
            "auto_score": s.score, "passed_count": s.passed_count,
            "total_count": s.total_count, "source_code": s.source_code,
        })
    return {"submissions": out}
