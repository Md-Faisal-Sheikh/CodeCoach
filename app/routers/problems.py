"""Problem CRUD (create is instructor-only) and listing."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..auth import get_current_user, require_instructor
from ..db import get_session
from ..models import Problem, TestCase, User
from ..schemas import ProblemIn
from ..sandbox.languages import available_languages

router = APIRouter(prefix="/api/problems", tags=["problems"])


@router.get("")
def list_problems(session: Session = Depends(get_session),
                  user: User = Depends(get_current_user)):
    probs = session.exec(select(Problem).order_by(Problem.id)).all()
    out = []
    for p in probs:
        n_tests = len(session.exec(
            select(TestCase).where(TestCase.problem_id == p.id)).all())
        out.append({
            "id": p.id, "slug": p.slug, "title": p.title,
            "language": p.language, "difficulty": p.difficulty,
            "tags": p.tags, "n_tests": n_tests,
            "max_hint_level": p.max_hint_level,
        })
    return {"problems": out, "languages": available_languages()}


@router.get("/{problem_id}")
def get_problem(problem_id: int, session: Session = Depends(get_session),
                user: User = Depends(get_current_user)):
    p = session.get(Problem, problem_id)
    if p is None:
        raise HTTPException(404, "problem not found")
    tests = session.exec(
        select(TestCase).where(TestCase.problem_id == p.id)
        .order_by(TestCase.ordering)).all()
    # students see only non-hidden sample tests; instructors see everything
    is_instructor = user.role in ("instructor", "admin")
    visible = [t for t in tests if (not t.hidden) or is_instructor]
    return {
        "id": p.id, "slug": p.slug, "title": p.title, "statement": p.statement,
        "language": p.language, "difficulty": p.difficulty, "tags": p.tags,
        "time_limit_ms": p.time_limit_ms, "memory_limit_mb": p.memory_limit_mb,
        "max_hint_level": p.max_hint_level,
        "reference_solution": p.reference_solution if is_instructor else "",
        "tests": [
            {"id": t.id, "name": t.name, "stdin": t.stdin,
             "expected_stdout": t.expected_stdout, "hidden": t.hidden,
             "weight": t.weight} for t in visible
        ],
    }


@router.post("")
def create_problem(body: ProblemIn, session: Session = Depends(get_session),
                   _: User = Depends(require_instructor)):
    if session.exec(select(Problem).where(Problem.slug == body.slug)).first():
        raise HTTPException(409, f"slug '{body.slug}' already exists")
    p = Problem(
        slug=body.slug, title=body.title, statement=body.statement,
        language=body.language, reference_solution=body.reference_solution,
        difficulty=body.difficulty, tags=body.tags,
        time_limit_ms=body.time_limit_ms, memory_limit_mb=body.memory_limit_mb,
        max_hint_level=body.max_hint_level,
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    for i, t in enumerate(body.tests):
        session.add(TestCase(
            problem_id=p.id, name=t.name or f"test{i+1}", stdin=t.stdin,
            expected_stdout=t.expected_stdout, weight=t.weight, hidden=t.hidden,
            comparison=t.comparison, float_tol=t.float_tol,
            time_limit_ms=t.time_limit_ms, ordering=t.ordering or i,
        ))
    session.commit()
    return {"id": p.id, "slug": p.slug}
