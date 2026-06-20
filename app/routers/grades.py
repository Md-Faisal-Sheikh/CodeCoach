"""Human grading of submissions (instructor-only), compared to the autograder."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..auth import require_instructor
from ..db import get_session
from ..models import Submission, HumanGrade, User
from ..schemas import HumanGradeRequest

router = APIRouter(prefix="/api/grades", tags=["grades"])


@router.post("")
def submit_grade(body: HumanGradeRequest, session: Session = Depends(get_session),
                 user: User = Depends(require_instructor)):
    sub = session.get(Submission, body.submission_id)
    if sub is None:
        raise HTTPException(404, "submission not found")
    if not (0.0 <= body.score <= 1.0):
        raise HTTPException(400, "score must be in [0,1]")
    g = HumanGrade(submission_id=sub.id, grader_user_id=user.id,
                   score=body.score, label=body.label, comment=body.comment)
    session.add(g)
    session.commit()
    session.refresh(g)
    return {"id": g.id, "submission_id": sub.id,
            "auto_score": sub.score, "human_score": body.score,
            "delta": round(abs(sub.score - body.score), 4)}


@router.get("/submission/{submission_id}")
def grades_for(submission_id: int, session: Session = Depends(get_session),
               _: User = Depends(require_instructor)):
    gs = session.exec(
        select(HumanGrade).where(HumanGrade.submission_id == submission_id)).all()
    return {"grades": [
        {"id": g.id, "score": g.score, "label": g.label, "comment": g.comment,
         "grader_user_id": g.grader_user_id} for g in gs]}
