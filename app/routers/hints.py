"""Request hints / feedback / baselines for a submission, and rate them."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..auth import get_current_user, require_instructor
from ..db import get_session
from ..models import Submission, Hint, HintRating, Problem, User
from ..schemas import HintRequest, FeedbackRequest, RateHintRequest
from ..services import create_hint, create_baseline
from ..ai import hints as hint_engine
from ..ai import overhinting
from ..constants import OK

router = APIRouter(prefix="/api/hints", tags=["hints"])


def _load_submission(session: Session, submission_id: int, user: User) -> Submission:
    sub = session.get(Submission, submission_id)
    if sub is None:
        raise HTTPException(404, "submission not found")
    if sub.user_id != user.id and user.role not in ("instructor", "admin"):
        raise HTTPException(403, "not your submission")
    return sub


def _hint_out(h: Hint, *, include_leakage: bool) -> dict:
    out = {
        "id": h.id, "submission_id": h.submission_id, "level": h.level,
        "source": h.source, "content": h.content, "model": h.model,
        "created_at": h.created_at.isoformat(),
    }
    if include_leakage:
        out["leakage_score"] = h.leakage_score
        out["leaked"] = h.leaked
        try:
            out["leakage_detail"] = json.loads(h.leakage_detail or "{}")
        except Exception:
            out["leakage_detail"] = {}
    return out


@router.post("")
def request_hint(body: HintRequest, session: Session = Depends(get_session),
                 user: User = Depends(get_current_user)):
    sub = _load_submission(session, body.submission_id, user)
    if sub.status == OK:
        raise HTTPException(400, "submission already passes all tests")
    problem = session.get(Problem, sub.problem_id)
    level = max(1, min(body.level, problem.max_hint_level))
    # students don't run the (slower, solution-aware) LLM judge on every call
    use_judge = user.role in ("instructor", "admin")
    hint = create_hint(session, sub, level, use_judge=use_judge)
    # students never see leakage diagnostics; instructors do
    return _hint_out(hint, include_leakage=user.role in ("instructor", "admin"))


@router.post("/baseline")
def request_baseline(body: HintRequest, session: Session = Depends(get_session),
                     user: User = Depends(get_current_user)):
    """Control condition: the raw compiler/runtime error."""
    sub = _load_submission(session, body.submission_id, user)
    hint = create_baseline(session, sub)
    return _hint_out(hint, include_leakage=False)


@router.post("/feedback")
def request_feedback(body: FeedbackRequest, session: Session = Depends(get_session),
                     user: User = Depends(get_current_user)):
    sub = _load_submission(session, body.submission_id, user)
    problem = session.get(Problem, sub.problem_id)
    gen = hint_engine.generate_feedback(
        language=sub.language, problem_statement=problem.statement,
        source_code=sub.source_code, status=sub.status,
        passed_count=sub.passed_count, total_count=sub.total_count,
        stderr=sub.compile_log,
    )
    hint = Hint(submission_id=sub.id, level=0, source=gen.source,
                content=gen.content, model=gen.model,
                prompt_tokens=gen.prompt_tokens,
                completion_tokens=gen.completion_tokens)
    session.add(hint)
    session.commit()
    session.refresh(hint)
    return _hint_out(hint, include_leakage=False)


@router.get("/submission/{submission_id}")
def list_hints(submission_id: int, session: Session = Depends(get_session),
               user: User = Depends(get_current_user)):
    sub = _load_submission(session, submission_id, user)
    hs = session.exec(
        select(Hint).where(Hint.submission_id == sub.id).order_by(Hint.id)).all()
    inc = user.role in ("instructor", "admin")
    return {"hints": [_hint_out(h, include_leakage=inc) for h in hs]}


@router.post("/rate")
def rate_hint(body: RateHintRequest, session: Session = Depends(get_session),
              user: User = Depends(require_instructor)):
    """Instructor rates a hint for the study (helpfulness + correctness + leak)."""
    hint = session.get(Hint, body.hint_id)
    if hint is None:
        raise HTTPException(404, "hint not found")
    if not (1 <= body.helpfulness <= 5 and 1 <= body.correctness <= 5):
        raise HTTPException(400, "helpfulness and correctness must be 1..5")
    rating = HintRating(
        hint_id=hint.id, rater_user_id=user.id, helpfulness=body.helpfulness,
        correctness=body.correctness, reveals_solution=body.reveals_solution,
        comment=body.comment,
    )
    session.add(rating)
    session.commit()
    session.refresh(rating)
    return {"id": rating.id, "hint_id": hint.id}
