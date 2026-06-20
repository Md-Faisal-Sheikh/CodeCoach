"""Over-hinting (answer-leakage) detection.

The research question -- "do hints help WITHOUT giving the solution away" --
needs a measurable definition of "giving it away". We estimate leakage three
ways and combine them:

  STRUCTURAL leak  : pull any fenced code out of the hint and actually run it
                     against the problem's test cases in the sandbox. If that
                     extracted snippet passes a large fraction of tests, the hint
                     effectively contained the solution. This is the strongest
                     signal and is grounded in execution, not heuristics.

  LEXICAL leak     : shingle-overlap between the hint and the *reference
                     solution*, after subtracting shingles that already appear in
                     the problem statement or the student's own code. This
                     catches near-verbatim solution text even when it isn't in a
                     runnable code block. Subtracting the statement/student code
                     avoids penalising a hint for using vocabulary the student
                     already had.

  JUDGE leak (opt) : if the LLM is available, a separate judge model rates how
                     much of the solution the hint reveals on a 0-4 scale. This
                     is blended in but never required.

combined = max(structural, 0.85 * lexical) then nudged by the judge. A hint is
flagged `leaked` when combined >= settings.leakage_threshold. Component scores
are stored so instructors can audit why something tripped.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from typing import List, Optional

from ..config import settings
from . import client


_FENCE_RE = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.DOTALL)
_INDENT_BLOCK_RE = re.compile(r"(?:^(?: {4}|\t).*(?:\n|$))+", re.MULTILINE)
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


def _word_shingles(text: str, k: int = 4) -> set:
    """k-gram set over lowercased word tokens. Uniform across prose and code so
    hint / reference / statement / student-code overlaps are comparable."""
    toks = [t.lower() for t in _WORD_RE.findall(text)]
    if len(toks) < k:
        return {"\x1f".join(toks)} if toks else set()
    return {"\x1f".join(toks[i:i + k]) for i in range(len(toks) - k + 1)}


@dataclass
class LeakageReport:
    leakage_score: float
    leaked: bool
    structural: float
    lexical: float
    judge: Optional[float]
    extracted_code: str = ""
    structural_passed: int = 0
    structural_total: int = 0
    note: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def extract_code(hint_text: str) -> str:
    """Pull candidate code out of a hint: fenced blocks first, then indented
    blocks as a fallback. Returns concatenated snippets (may be empty)."""
    blocks = _FENCE_RE.findall(hint_text)
    if blocks:
        return "\n".join(b.strip() for b in blocks).strip()
    indented = _INDENT_BLOCK_RE.findall(hint_text)
    cleaned = []
    for blk in indented:
        lines = [re.sub(r"^(?: {4}|\t)", "", ln) for ln in blk.splitlines()]
        cleaned.append("\n".join(lines))
    joined = "\n".join(cleaned).strip()
    # Require at least a couple of code-ish lines to avoid treating prose as code.
    if joined.count("\n") >= 1 and any(
        sym in joined for sym in ("=", "(", "return", "for ", "while ", "def ", "if ")
    ):
        return joined
    return ""


def _structural_leak(extracted: str, language: str, problem) -> tuple:
    """Run extracted code against the problem's tests. Returns
    (fraction_passed, passed, total). Best-effort: any failure to run → 0."""
    if not extracted.strip():
        return 0.0, 0, 0
    try:
        from ..sandbox.grader import grade, TestSpec
        from ..db import get_session
        from ..models import TestCase
        from sqlmodel import select

        with next(get_session()) as session:
            rows = session.exec(
                select(TestCase).where(TestCase.problem_id == problem.id)
            ).all()
        if not rows:
            return 0.0, 0, 0
        specs = [
            TestSpec(
                id=t.id or 0, name=t.name, stdin=t.stdin,
                expected_stdout=t.expected_stdout, weight=t.weight,
                hidden=t.hidden, comparison=t.comparison, float_tol=t.float_tol,
                time_limit_ms=t.time_limit_ms,
            )
            for t in rows
        ]
        report = grade(extracted, language, specs,
                       time_limit_ms=problem.time_limit_ms,
                       memory_limit_mb=problem.memory_limit_mb)
        total = report.total_count or len(specs)
        if total == 0:
            return 0.0, 0, 0
        return report.passed_count / total, report.passed_count, total
    except Exception:
        return 0.0, 0, 0


def _lexical_leak(hint_text: str, reference_solution: str,
                  problem_statement: str, student_code: str, k: int = 4) -> float:
    """Shingle overlap of hint with reference solution, discounting shingles the
    student already had access to (statement + their own code)."""
    if not reference_solution.strip():
        return 0.0
    ref = _word_shingles(reference_solution, k)
    if not ref:
        return 0.0
    hint = _word_shingles(hint_text, k)
    if not hint:
        return 0.0
    prior = _word_shingles(problem_statement, k) | _word_shingles(student_code, k)
    # reference shingles that are "new" (not already available to the student)
    novel_ref = ref - prior
    if not novel_ref:
        return 0.0
    leaked = hint & novel_ref
    return len(leaked) / len(novel_ref)


_JUDGE_SYSTEM = """You audit teaching hints for answer leakage. Given a programming problem, its reference solution, and a hint shown to a student, rate how much of the solution the hint gives away.

Scale:
0 = reveals nothing concrete; only a direction or question
1 = points at the relevant concept but the student still must do the work
2 = describes the specific fix in words but no usable code
3 = contains code that does most of the core logic
4 = essentially hands over the solution

Respond with ONLY a single integer 0-4."""


def _judge_leak(hint_text: str, reference_solution: str,
                problem_statement: str) -> Optional[float]:
    if not client.available() or not reference_solution.strip():
        return None
    user = (f"PROBLEM:\n{problem_statement.strip()[:1500]}\n\n"
            f"REFERENCE SOLUTION:\n{reference_solution.strip()[:1500]}\n\n"
            f"HINT:\n{hint_text.strip()[:1500]}\n\n"
            "Rate leakage 0-4. Output only the integer.")
    resp = client.complete(_JUDGE_SYSTEM, user,
                           model=settings.judge_model, max_tokens=8, temperature=0.0)
    if not resp.ok:
        return None
    m = re.search(r"[0-4]", resp.text)
    if not m:
        return None
    return int(m.group()) / 4.0


def analyze_hint(*, hint_text: str, language: str, problem,
                 student_code: str = "", use_judge: bool = True) -> LeakageReport:
    """Full leakage analysis for a single hint against its problem."""
    extracted = extract_code(hint_text)
    structural, s_pass, s_total = _structural_leak(extracted, language, problem)
    lexical = _lexical_leak(hint_text, problem.reference_solution,
                            problem.statement, student_code)
    judge = _judge_leak(hint_text, problem.reference_solution, problem.statement) \
        if use_judge else None

    combined = max(structural, 0.85 * lexical)
    if judge is not None:
        # Judge can only push the score up toward its own estimate, gently.
        combined = max(combined, 0.5 * combined + 0.5 * judge)
    combined = min(1.0, combined)

    note = ""
    if structural >= settings.leakage_threshold:
        note = f"extracted code passed {s_pass}/{s_total} tests"
    elif lexical >= settings.leakage_threshold:
        note = "hint text closely mirrors the reference solution"
    elif judge is not None and judge >= settings.leakage_threshold:
        note = "LLM judge flagged high reveal"

    return LeakageReport(
        leakage_score=round(combined, 4),
        leaked=combined >= settings.leakage_threshold,
        structural=round(structural, 4),
        lexical=round(lexical, 4),
        judge=None if judge is None else round(judge, 4),
        extracted_code=extracted[:2000],
        structural_passed=s_pass,
        structural_total=s_total,
        note=note,
    )
