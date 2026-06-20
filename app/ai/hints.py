"""Pedagogical hint generation.

Design contract for the study: a *hint* must help a student locate and
understand their mistake WITHOUT handing them the solution. Two levers enforce
that:

  1. The reference solution is deliberately NOT passed to the hint generator.
     The model reasons only from the problem statement, the student's own code,
     and the failing test signal -- it cannot copy an answer it never sees.
  2. The system prompt forbids full/near-full solutions and caps illustrative
     code at a couple of lines of generic concept (not problem-specific).

Hints are progressive: level 1 is a nudge, level 2 names the specific mistake,
level 3 gives a high-level strategy. If the LLM is unavailable (no key / offline
/ API error) we fall back to deterministic heuristics so the platform always
returns *something* and the study can run a pure-offline arm.

`make_baseline()` produces the control condition: the raw compiler / runtime
error a student would see from a bare toolchain, lightly cleaned. Comparing LLM
and heuristic hints against this baseline is the core of the research question.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..constants import SRC_BASELINE, SRC_HEURISTIC, SRC_LLM, CE, RE, TLE, MLE, OLE, WA, OK
from . import client
from .heuristics import heuristic_hint


@dataclass
class GeneratedHint:
    content: str
    source: str            # llm / heuristic / baseline
    level: int
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


_LEVEL_GUIDANCE = {
    1: ("NUDGE", "Point the student toward the general area or category of the "
                 "problem. Ask a guiding question. Do NOT name the exact bug."),
    2: ("SPECIFIC", "Name the specific kind of mistake and where to look "
                    "(which case, which operation). Still do not write the fix."),
    3: ("STRATEGY", "Give a high-level strategy or the conceptual approach the "
                    "student is missing. You may show at most two lines of "
                    "GENERIC illustrative code (not the actual solution)."),
}

_SYSTEM = """You are a programming teaching assistant embedded in an automated grader.
A student's submission failed one or more tests. Your job is to write ONE short hint that helps them learn to find and fix their own mistake.

HARD RULES -- these are non-negotiable:
- NEVER provide the full or near-full solution.
- NEVER write the specific line(s) of code that would make the failing test pass.
- Any illustrative code is limited to at most two lines of GENERIC syntax (e.g. how a dict comprehension looks in the abstract), never the problem's actual logic.
- Do not restate the student's whole program back to them.
- Be concrete about the symptom, not the cure. Prefer a guiding question over a directive.
- Keep it under 90 words. No preamble, no sign-off. Plain text, no markdown headers.

You are given the problem statement, the student's code, the language, and the failing test signal (status plus, for wrong-answer cases, the input and the expected-vs-actual output). You are deliberately NOT given the official solution; reason from the student's code only."""


def _failing_signal(status: str, stderr: str, failing_input: str,
                    expected: str, actual: str) -> str:
    lines = [f"Failing status: {status}"]
    if status in (CE, RE) and stderr:
        lines.append(f"Error output:\n{stderr.strip()[:1500]}")
    if status == WA:
        if failing_input:
            lines.append(f"On input:\n{failing_input.strip()[:800]}")
        if expected:
            lines.append(f"Expected output:\n{expected.strip()[:800]}")
        if actual:
            lines.append(f"Student's output:\n{actual.strip()[:800]}")
    if status == TLE:
        lines.append("The program exceeded the time limit -- likely a too-slow "
                     "algorithm or an infinite loop.")
    if status == MLE:
        lines.append("The program exceeded the memory limit.")
    if status == OLE:
        lines.append("The program printed far more output than expected.")
    return "\n".join(lines)


def generate_hint(*, level: int, language: str, problem_statement: str,
                  source_code: str, status: str, stderr: str = "",
                  failing_input: str = "", expected: str = "",
                  actual: str = "") -> GeneratedHint:
    """Produce a single progressive hint. Tries the LLM; falls back to heuristics."""
    level = max(1, min(3, level))

    if client.available():
        label, guidance = _LEVEL_GUIDANCE[level]
        user = f"""LANGUAGE: {language}

PROBLEM STATEMENT:
{problem_statement.strip()[:2500]}

STUDENT'S CODE:
```{language}
{source_code.strip()[:3000]}
```

{_failing_signal(status, stderr, failing_input, expected, actual)}

HINT LEVEL: {level} ({label})
LEVEL INSTRUCTION: {guidance}

Write the hint now."""
        resp = client.complete(_SYSTEM, user, max_tokens=300, temperature=0.3)
        if resp.ok and resp.text:
            return GeneratedHint(resp.text, SRC_LLM, level, resp.model,
                                 resp.input_tokens, resp.output_tokens)

    # Fallback: deterministic static-analysis hint.
    content = heuristic_hint(level, status=status, stderr=stderr,
                             failing_input=failing_input, expected=expected,
                             actual=actual)
    return GeneratedHint(content, SRC_HEURISTIC, level)


_FEEDBACK_SYSTEM = """You are a programming teaching assistant. Write brief, encouraging, formative feedback on a student's submission after grading.
Summarize what works and what to focus on next in 2-4 sentences. If some tests failed, describe the category of issue at a high level. Do NOT write the corrected code or reveal a full solution. Under 110 words, plain text."""


def generate_feedback(*, language: str, problem_statement: str, source_code: str,
                      status: str, passed_count: int, total_count: int,
                      stderr: str = "") -> GeneratedHint:
    """Holistic end-of-attempt feedback (not tied to a single failing test)."""
    if client.available():
        user = f"""LANGUAGE: {language}

PROBLEM:
{problem_statement.strip()[:2000]}

STUDENT CODE:
```{language}
{source_code.strip()[:3000]}
```

RESULT: status={status}, passed {passed_count}/{total_count} tests.
{('Error output:\\n' + stderr.strip()[:1200]) if stderr.strip() else ''}

Write the feedback now."""
        resp = client.complete(_FEEDBACK_SYSTEM, user, max_tokens=320, temperature=0.4)
        if resp.ok and resp.text:
            return GeneratedHint(resp.text, SRC_LLM, 0, resp.model,
                                 resp.input_tokens, resp.output_tokens)

    if status == OK:
        msg = (f"All {total_count} tests pass. Nice work. Before moving on, "
               "re-read your solution and check whether it would still hold up "
               "on larger inputs or unusual edge cases.")
    else:
        msg = (f"You're passing {passed_count} of {total_count} tests, so the "
               "overall structure is partly there. Focus on the failing "
               f"category ({status}) next: reproduce one failing case by hand "
               "and trace your logic line by line.")
    return GeneratedHint(msg, SRC_HEURISTIC, 0)


def make_baseline(*, status: str, compile_log: str = "", stderr: str = "",
                  failing_input: str = "", expected: str = "",
                  actual: str = "") -> GeneratedHint:
    """Control condition: the raw toolchain error, lightly cleaned.

    This is what a student gets from a bare compiler/interpreter with no
    pedagogical layer -- the comparison point for the study.
    """
    if status == CE:
        body = compile_log.strip() or "Compilation failed."
        return GeneratedHint(_trim(body), SRC_BASELINE, 0)
    if status == RE:
        body = stderr.strip() or "Program terminated with a runtime error."
        return GeneratedHint(_trim(body), SRC_BASELINE, 0)
    if status == TLE:
        return GeneratedHint("Time limit exceeded.", SRC_BASELINE, 0)
    if status == MLE:
        return GeneratedHint("Memory limit exceeded.", SRC_BASELINE, 0)
    if status == OLE:
        return GeneratedHint("Output limit exceeded.", SRC_BASELINE, 0)
    if status == WA:
        parts = ["Wrong answer."]
        if failing_input:
            parts.append(f"Input:\n{failing_input.strip()[:500]}")
        if expected:
            parts.append(f"Expected:\n{expected.strip()[:500]}")
        if actual:
            parts.append(f"Got:\n{actual.strip()[:500]}")
        return GeneratedHint("\n".join(parts), SRC_BASELINE, 0)
    return GeneratedHint("Submission did not pass all tests.", SRC_BASELINE, 0)


def _trim(text: str, limit: int = 2000) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"
