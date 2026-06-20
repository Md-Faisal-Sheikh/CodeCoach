"""Test fixtures. Isolation strategy: point the app at a throwaway SQLite file
via env vars set BEFORE any app import, and force AI offline so every run is
deterministic (no network, heuristic hints). Dynamic tables are wiped between
tests for independence.
"""
import os
import tempfile

# Must be set before importing anything under app.* (engine binds at import).
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="codecoach-test-"), "test.db")
os.environ["CODECOACH_DB_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["CODECOACH_AI_OFFLINE"] = "1"          # heuristic hints, no API calls
os.environ.pop("ANTHROPIC_API_KEY", None)

import pytest
from sqlmodel import Session, delete

from app.db import engine, init_db
from app.models import (User, Problem, TestCase, Submission, RunResult, Hint,
                        HintRating, HumanGrade, SimilarityEdge)
from app.constants import ROLE_STUDENT, ROLE_INSTRUCTOR, CMP_WHITESPACE


@pytest.fixture(scope="session", autouse=True)
def _init():
    init_db()
    yield


@pytest.fixture
def session():
    with Session(engine) as s:
        for model in (SimilarityEdge, HintRating, HumanGrade, RunResult, Hint,
                      Submission, TestCase, Problem, User):
            s.exec(delete(model))
        s.commit()
        yield s


# --------------------------------------------------------------------------- #
# small builders so each test sets up only what it needs (fast: no TLE cases)
# --------------------------------------------------------------------------- #
def make_user(session, username="ada", role=ROLE_STUDENT, token=None):
    u = User(username=username, role=role,
             token=token or f"tok-{username}", display_name=username.title())
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def make_problem(session, slug="sum-two", *, reference=None, tests=None):
    ref = reference or "a, b = map(int, input().split())\nprint(a + b)\n"
    prob = Problem(slug=slug, title=slug, statement="add two ints",
                   language="python", reference_solution=ref,
                   time_limit_ms=5000, memory_limit_mb=256, max_hint_level=3)
    session.add(prob)
    session.commit()
    session.refresh(prob)
    specs = tests or [
        ("a", "2 3", "5", False),
        ("b", "10 20", "30", False),
        ("c", "-5 5", "0", True),
    ]
    for i, (name, stdin, out, hidden) in enumerate(specs):
        session.add(TestCase(problem_id=prob.id, name=name, stdin=stdin,
                             expected_stdout=out, hidden=hidden,
                             comparison=CMP_WHITESPACE, ordering=i))
    session.commit()
    return prob


def make_submission(session, problem, user, source):
    sub = Submission(problem_id=problem.id, user_id=user.id,
                     language=problem.language, source_code=source)
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}
