"""Orchestration layer: ties the sandbox, AI, and over-hinting modules to the
database. Routers and the study scripts both call these so behaviour is
identical between the live API and batch runs.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlmodel import Session, select

from .constants import OK, CE, RE, WA, TLE, MLE, OLE
from .models import Problem, TestCase, Submission, RunResult, Hint
from .sandbox.grader import grade, TestSpec, GradeReport
from .ai import hints as hint_engine
from .ai import overhinting


# --------------------------------------------------------------------------- #
# grading
# --------------------------------------------------------------------------- #
def _specs_for(session: Session, problem_id: int) -> List[TestSpec]:
    rows = session.exec(
        select(TestCase).where(TestCase.problem_id == problem_id)
        .order_by(TestCase.ordering)
    ).all()
    return [
        TestSpec(
            id=t.id or 0, name=t.name, stdin=t.stdin,
            expected_stdout=t.expected_stdout, weight=t.weight, hidden=t.hidden,
            comparison=t.comparison, float_tol=t.float_tol,
            time_limit_ms=t.time_limit_ms,
        )
        for t in rows
    ]


def grade_submission(session: Session, submission: Submission) -> GradeReport:
    """Run a submission through the sandbox, persist per-test results, and update
    the submission row. Returns the in-memory GradeReport."""
    problem = session.get(Problem, submission.problem_id)
    if problem is None:
        raise ValueError("problem not found")
    specs = _specs_for(session, problem.id)

    report = grade(
        submission.source_code, submission.language, specs,
        time_limit_ms=problem.time_limit_ms,
        memory_limit_mb=problem.memory_limit_mb,
    )

    # wipe any previous run rows for idempotent re-grading
    old = session.exec(
        select(RunResult).where(RunResult.submission_id == submission.id)
    ).all()
    for r in old:
        session.delete(r)

    for o in report.outcomes:
        session.add(RunResult(
            submission_id=submission.id, testcase_id=o.testcase_id,
            status=o.status, passed=o.passed, runtime_ms=o.runtime_ms,
            memory_kb=o.memory_kb, exit_code=o.exit_code, signal=o.signal,
            stdout_excerpt=o.stdout_excerpt, stderr_excerpt=o.stderr_excerpt,
        ))

    submission.status = report.status
    submission.score = report.score
    submission.passed_count = report.passed_count
    submission.total_count = report.total_count
    submission.runtime_ms = report.runtime_ms
    submission.memory_kb = report.memory_kb
    submission.compile_log = report.compile_log
    session.add(submission)
    session.commit()
    session.refresh(submission)
    return report


# --------------------------------------------------------------------------- #
# failing-signal extraction (feeds hint generation)
# --------------------------------------------------------------------------- #
def first_failure(session: Session, submission: Submission) -> dict:
    """Find a representative failing test for hint context. Prefers the first
    non-passing visible test; falls back to any failing test."""
    results = session.exec(
        select(RunResult).where(RunResult.submission_id == submission.id)
    ).all()
    res_by_tc = {r.testcase_id: r for r in results}

    specs = session.exec(
        select(TestCase).where(TestCase.problem_id == submission.problem_id)
        .order_by(TestCase.ordering)
    ).all()

    chosen_spec = None
    chosen_res = None
    for tc in specs:
        r = res_by_tc.get(tc.id)
        if r and not r.passed:
            chosen_spec, chosen_res = tc, r
            if not tc.hidden:
                break

    info = {
        "status": submission.status, "stderr": "", "failing_input": "",
        "expected": "", "actual": "",
    }
    if submission.status == CE:
        info["stderr"] = submission.compile_log
        return info
    if chosen_res is None:
        return info

    info["status"] = chosen_res.status
    info["stderr"] = chosen_res.stderr_excerpt
    if chosen_spec is not None and not chosen_spec.hidden:
        info["failing_input"] = chosen_spec.stdin
        info["expected"] = chosen_spec.expected_stdout
        info["actual"] = chosen_res.stdout_excerpt
    else:
        # hidden test: reveal only the category, not the data
        info["expected"] = ""
        info["actual"] = ""
    return info


# --------------------------------------------------------------------------- #
# hint generation + leakage analysis (persisted)
# --------------------------------------------------------------------------- #
def create_hint(session: Session, submission: Submission, level: int,
                *, use_judge: bool = True) -> Hint:
    problem = session.get(Problem, submission.problem_id)
    sig = first_failure(session, submission)

    gen = hint_engine.generate_hint(
        level=level, language=submission.language,
        problem_statement=problem.statement, source_code=submission.source_code,
        status=sig["status"], stderr=sig["stderr"],
        failing_input=sig["failing_input"], expected=sig["expected"],
        actual=sig["actual"],
    )

    leak = overhinting.analyze_hint(
        hint_text=gen.content, language=submission.language, problem=problem,
        student_code=submission.source_code, use_judge=use_judge,
    )

    hint = Hint(
        submission_id=submission.id, level=gen.level, source=gen.source,
        content=gen.content, model=gen.model, prompt_tokens=gen.prompt_tokens,
        completion_tokens=gen.completion_tokens, leakage_score=leak.leakage_score,
        leaked=leak.leaked, leakage_detail=leak.to_json(),
    )
    session.add(hint)
    session.commit()
    session.refresh(hint)
    return hint


def create_baseline(session: Session, submission: Submission) -> Hint:
    """The control-condition 'hint': raw toolchain error, no pedagogy."""
    sig = first_failure(session, submission)
    gen = hint_engine.make_baseline(
        status=sig["status"], compile_log=submission.compile_log,
        stderr=sig["stderr"], failing_input=sig["failing_input"],
        expected=sig["expected"], actual=sig["actual"],
    )
    # baselines are raw errors; leakage is essentially nil but we still record 0s
    hint = Hint(
        submission_id=submission.id, level=0, source=gen.source,
        content=gen.content, model="", leakage_score=0.0, leaked=False,
        leakage_detail="{}",
    )
    session.add(hint)
    session.commit()
    session.refresh(hint)
    return hint
