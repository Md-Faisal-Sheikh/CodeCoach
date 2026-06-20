"""Pydantic request/response bodies for the API."""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


# ---- submissions ----
class SubmitRequest(BaseModel):
    problem_id: int
    source_code: str
    language: Optional[str] = None      # defaults to the problem's language


class HintRequest(BaseModel):
    submission_id: int
    level: int = 1


class FeedbackRequest(BaseModel):
    submission_id: int


# ---- ratings / grades (instructor study) ----
class RateHintRequest(BaseModel):
    hint_id: int
    helpfulness: int                    # 1..5
    correctness: int                    # 1..5
    reveals_solution: Optional[bool] = None
    comment: str = ""


class HumanGradeRequest(BaseModel):
    submission_id: int
    score: float                        # 0..1
    label: str = ""
    comment: str = ""


# ---- problems ----
class TestCaseIn(BaseModel):
    name: str = ""
    stdin: str = ""
    expected_stdout: str = ""
    weight: float = 1.0
    hidden: bool = False
    comparison: str = "whitespace"
    float_tol: float = 1e-6
    time_limit_ms: Optional[int] = None
    ordering: int = 0


class ProblemIn(BaseModel):
    slug: str
    title: str
    statement: str = ""
    language: str = "python"
    reference_solution: str = ""
    difficulty: str = "easy"
    tags: str = ""
    time_limit_ms: int = 5000
    memory_limit_mb: int = 256
    max_hint_level: int = 3
    tests: List[TestCaseIn] = []
