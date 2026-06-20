"""SQLModel ORM tables. Foreign keys are plain int fields; we query explicitly
rather than lean on lazy relationships (keeps session handling predictable)."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field

from .constants import CMP_WHITESPACE, ROLE_STUDENT


def _now() -> datetime:
    return datetime.utcnow()


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    role: str = Field(default=ROLE_STUDENT, index=True)
    token: str = Field(index=True, unique=True)
    display_name: str = ""
    created_at: datetime = Field(default_factory=_now)


class Problem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    title: str
    statement: str = ""                      # markdown problem text shown to students
    language: str = "python"                 # canonical language for this problem
    reference_solution: str = ""             # used for over-hinting leakage + grading sanity
    difficulty: str = "easy"                 # easy / medium / hard
    tags: str = ""                           # comma-separated
    time_limit_ms: int = 5000
    memory_limit_mb: int = 256
    max_hint_level: int = 3                   # progressive-hint ceiling
    created_at: datetime = Field(default_factory=_now)


class TestCase(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    problem_id: int = Field(index=True, foreign_key="problem.id")
    name: str = ""
    stdin: str = ""
    expected_stdout: str = ""
    weight: float = 1.0
    hidden: bool = False                      # hidden tests are not revealed to students
    comparison: str = CMP_WHITESPACE
    float_tol: float = 1e-6
    time_limit_ms: Optional[int] = None       # overrides problem default if set
    ordering: int = 0


class Submission(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    problem_id: int = Field(index=True, foreign_key="problem.id")
    user_id: int = Field(index=True, foreign_key="user.id")
    language: str = "python"
    source_code: str = ""
    status: str = "PENDING"                   # overall verdict (OK if all tests pass)
    score: float = 0.0                        # weighted fraction in [0,1]
    passed_count: int = 0
    total_count: int = 0
    runtime_ms: int = 0                       # max across tests
    memory_kb: int = 0                        # max across tests
    compile_log: str = ""
    created_at: datetime = Field(default_factory=_now)


class RunResult(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    submission_id: int = Field(index=True, foreign_key="submission.id")
    testcase_id: int = Field(foreign_key="testcase.id")
    status: str = "IE"
    passed: bool = False
    runtime_ms: int = 0
    memory_kb: int = 0
    exit_code: Optional[int] = None
    signal: Optional[int] = None
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""


class Hint(SQLModel, table=True):
    """A hint or feedback message attached to a submission. Baseline (raw error),
    LLM, and heuristic hints all live here so they can be rated head-to-head."""
    id: Optional[int] = Field(default=None, primary_key=True)
    submission_id: int = Field(index=True, foreign_key="submission.id")
    level: int = 1                            # progressive level (1=nudge .. N=near-explicit)
    source: str = "llm"                       # baseline / llm / heuristic
    content: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    leakage_score: float = 0.0                # [0,1] estimated solution leakage
    leaked: bool = False                      # leakage_score >= threshold
    leakage_detail: str = ""                  # json blob with component scores
    created_at: datetime = Field(default_factory=_now)


class HintRating(SQLModel, table=True):
    """Instructor (or rater) judgement used for the helpfulness/correctness study."""
    id: Optional[int] = Field(default=None, primary_key=True)
    hint_id: int = Field(index=True, foreign_key="hint.id")
    rater_user_id: int = Field(foreign_key="user.id")
    helpfulness: int = 0                      # 1..5
    correctness: int = 0                      # 1..5
    reveals_solution: Optional[bool] = None   # human judgement of leakage
    comment: str = ""
    created_at: datetime = Field(default_factory=_now)


class HumanGrade(SQLModel, table=True):
    """Human grade for a submission, compared against the autograder."""
    id: Optional[int] = Field(default=None, primary_key=True)
    submission_id: int = Field(index=True, foreign_key="submission.id")
    grader_user_id: int = Field(foreign_key="user.id")
    score: float = 0.0                        # human score in [0,1]
    label: str = ""                           # optional bucket: fail/partial/pass
    comment: str = ""
    created_at: datetime = Field(default_factory=_now)


class SimilarityEdge(SQLModel, table=True):
    """Pairwise similarity between two submissions to the same problem."""
    id: Optional[int] = Field(default=None, primary_key=True)
    problem_id: int = Field(index=True, foreign_key="problem.id")
    submission_a_id: int = Field(foreign_key="submission.id")
    submission_b_id: int = Field(foreign_key="submission.id")
    combined_score: float = 0.0
    winnow_score: float = 0.0
    ast_score: float = 0.0
    tfidf_score: float = 0.0
    created_at: datetime = Field(default_factory=_now)
