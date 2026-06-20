"""Plagiarism-style similarity analysis over submissions to a problem.

Instructor-only. Recomputes pairwise scores on demand and persists the edges so
the dashboard can render a ranked table and clusters.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ..auth import require_instructor
from ..db import get_session
from ..models import Problem, Submission, SimilarityEdge, User
from ..similarity.detector import analyze

router = APIRouter(prefix="/api/similarity", tags=["similarity"])


@router.post("/problem/{problem_id}")
def run_similarity(problem_id: int,
                   pair_threshold: float = Query(0.35, ge=0.0, le=1.0),
                   cluster_threshold: float = Query(0.55, ge=0.0, le=1.0),
                   latest_per_user: bool = Query(True),
                   session: Session = Depends(get_session),
                   _: User = Depends(require_instructor)):
    problem = session.get(Problem, problem_id)
    if problem is None:
        raise HTTPException(404, "problem not found")

    subs = session.exec(
        select(Submission).where(Submission.problem_id == problem_id)
        .order_by(Submission.id)).all()

    if latest_per_user:
        latest: dict = {}
        for s in subs:
            latest[s.user_id] = s          # later id overwrites → keeps newest
        subs = list(latest.values())

    pairs_input = [(s.id, s.source_code) for s in subs if s.source_code.strip()]
    if len(pairs_input) < 2:
        return {"pairs": [], "clusters": [], "n_submissions": len(pairs_input)}

    report = analyze(pairs_input, problem.language,
                     pair_threshold=pair_threshold,
                     cluster_threshold=cluster_threshold)

    # persist edges (replace previous)
    old = session.exec(
        select(SimilarityEdge).where(SimilarityEdge.problem_id == problem_id)).all()
    for e in old:
        session.delete(e)
    for p in report.pairs:
        session.add(SimilarityEdge(
            problem_id=problem_id, submission_a_id=p.a_id,
            submission_b_id=p.b_id, combined_score=p.combined,
            winnow_score=p.winnow, ast_score=p.ast or 0.0, tfidf_score=p.tfidf))
    session.commit()

    owner = {s.id: s.user_id for s in subs}
    return {
        "n_submissions": len(pairs_input),
        "pairs": [
            {"a_submission": p.a_id, "b_submission": p.b_id,
             "a_user": owner.get(p.a_id), "b_user": owner.get(p.b_id),
             "combined": round(p.combined, 4), "winnow": round(p.winnow, 4),
             "ast": None if p.ast is None else round(p.ast, 4),
             "tfidf": round(p.tfidf, 4)}
            for p in report.pairs
        ],
        "clusters": [
            {"members": c.members, "size": c.size,
             "max_score": round(c.max_score, 4),
             "member_users": [owner.get(m) for m in c.members]}
            for c in report.clusters
        ],
    }
