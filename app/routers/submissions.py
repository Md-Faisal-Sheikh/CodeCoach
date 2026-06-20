"""Submit code, grade it in the sandbox, and read results back."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..auth import get_current_user
from ..db import get_session
from ..models import Problem, Submission, RunResult, TestCase, User
from ..schemas import SubmitRequest
from ..services import grade_submission

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


@router.post("")
def submit(body: SubmitRequest, session: Session = Depends(get_session),
           user: User = Depends(get_current_user)):
    problem = session.get(Problem, body.problem_id)
    if problem is None:
        raise HTTPException(404, "problem not found")
    if not body.source_code.strip():
        raise HTTPException(400, "empty submission")

    sub = Submission(
        problem_id=problem.id, user_id=user.id,
        language=body.language or problem.language,
        source_code=body.source_code, status="PENDING",
        total_count=0,
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)

    report = grade_submission(session, sub)
    return _submission_payload(session, sub, user)


@router.get("/{submission_id}")
def get_submission(submission_id: int, session: Session = Depends(get_session),
                   user: User = Depends(get_current_user)):
    sub = session.get(Submission, submission_id)
    if sub is None:
        raise HTTPException(404, "submission not found")
    if sub.user_id != user.id and user.role not in ("instructor", "admin"):
        raise HTTPException(403, "not your submission")
    return _submission_payload(session, sub, user)


@router.get("")
def my_submissions(problem_id: int | None = None,
                   session: Session = Depends(get_session),
                   user: User = Depends(get_current_user)):
    q = select(Submission).where(Submission.user_id == user.id)
    if problem_id is not None:
        q = q.where(Submission.problem_id == problem_id)
    subs = session.exec(q.order_by(Submission.id.desc())).all()
    return {"submissions": [
        {"id": s.id, "problem_id": s.problem_id, "status": s.status,
         "score": s.score, "passed_count": s.passed_count,
         "total_count": s.total_count, "created_at": s.created_at.isoformat()}
        for s in subs
    ]}


def _submission_payload(session: Session, sub: Submission, user: User) -> dict:
    is_instructor = user.role in ("instructor", "admin")
    results = session.exec(
        select(RunResult).where(RunResult.submission_id == sub.id)).all()
    tcs = {t.id: t for t in session.exec(
        select(TestCase).where(TestCase.problem_id == sub.problem_id)).all()}
    outcomes = []
    for r in results:
        tc = tcs.get(r.testcase_id)
        hidden = tc.hidden if tc else False
        outcomes.append({
            "testcase_id": r.testcase_id,
            "name": tc.name if tc else "?",
            "hidden": hidden,
            "status": r.status,
            "passed": r.passed,
            "runtime_ms": r.runtime_ms,
            "memory_kb": r.memory_kb,
            # never leak hidden test I/O to students
            "stdout_excerpt": (r.stdout_excerpt if (not hidden or is_instructor) else ""),
            "stderr_excerpt": (r.stderr_excerpt if (not hidden or is_instructor) else ""),
        })
    outcomes.sort(key=lambda o: (o["hidden"], o["name"]))
    return {
        "id": sub.id, "problem_id": sub.problem_id, "language": sub.language,
        "status": sub.status, "score": sub.score,
        "passed_count": sub.passed_count, "total_count": sub.total_count,
        "runtime_ms": sub.runtime_ms, "memory_kb": sub.memory_kb,
        "compile_log": sub.compile_log, "outcomes": outcomes,
    }
