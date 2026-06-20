"""Deterministic static-analysis hints. Used when the LLM is unavailable, and
also reused as a structured signal the LLM prompt can build on."""
from __future__ import annotations
import re
from typing import List, Optional

from ..constants import OK, WA, TLE, MLE, RE, CE, OLE

_PY_ERRORS = {
    "SyntaxError": "There's a syntax error. Re-read the flagged line: a colon, bracket, or quote is likely missing or mismatched.",
    "IndentationError": "Python is strict about indentation. Make sure every block under a colon is consistently indented (don't mix tabs and spaces).",
    "NameError": "A name is used before it's defined. Check spelling and that every variable is assigned before it's read.",
    "TypeError": "An operation got the wrong type. Are you mixing strings and numbers, or calling something that isn't a function?",
    "ValueError": "A value has the right type but an invalid content -- often int() on non-numeric input, or unpacking the wrong number of items.",
    "IndexError": "You're indexing past the end of a sequence. Re-check your loop bounds and off-by-one cases.",
    "KeyError": "You're reading a dict key that doesn't exist. Guard with .get() or check membership first.",
    "ZeroDivisionError": "You're dividing by zero. Handle the case where the denominator can be 0.",
    "RecursionError": "Infinite or too-deep recursion. Make sure your base case is reached.",
    "ModuleNotFoundError": "A module isn't available in the sandbox. Solve it with the standard library only.",
    "EOFError": "You read more input than was provided. Re-check how many lines/tokens you consume.",
}


def _extract_python_error(stderr: str) -> Optional[str]:
    for name in _PY_ERRORS:
        if re.search(rf"\b{name}\b", stderr):
            return name
    return None


def _diff_summary(expected: str, actual: str) -> str:
    e_lines = expected.rstrip().split("\n")
    a_lines = actual.rstrip().split("\n")
    if len(e_lines) != len(a_lines):
        return (f"Your output has {len(a_lines)} line(s) but {len(e_lines)} were expected -- "
                "you're printing too much or too little.")
    e_tok = expected.split()
    a_tok = actual.split()
    if len(e_tok) != len(a_tok):
        return (f"You produced {len(a_tok)} value(s) but {len(e_tok)} were expected. "
                "Check whether you print every required value (and nothing extra).")
    for i, (e, a) in enumerate(zip(e_tok, a_tok)):
        if e != a:
            try:
                fe, fa = float(e), float(a)
                if fa != 0 and abs(fe / fa - round(fe / fa)) < 1e-9 and fe != fa:
                    return (f"The first difference is at value #{i + 1}: you printed {a}, expected {e}. "
                            "These differ by a constant factor -- re-check a multiply/divide.")
                return (f"The first difference is at value #{i + 1}: you printed {a}, expected {e}. "
                        "Trace your arithmetic for that case.")
            except ValueError:
                return (f"The first difference is at token #{i + 1}: you printed '{a}', expected '{e}'.")
    if expected.split() == actual.split():
        return "Your values are right but the whitespace/line formatting differs from what's expected."
    return "Your output differs from the expected output on this test."


def heuristic_hint(level: int, *, status: str, stderr: str = "",
                   failing_input: str = "", expected: str = "", actual: str = "") -> str:
    level = max(1, min(3, level))
    if status == CE:
        err = _extract_python_error(stderr)
        base = _PY_ERRORS.get(err, "Your code didn't compile. Read the first compiler error and fix that line first.")
        if level == 1:
            return "Your code doesn't compile yet. Start from the very first error message -- later errors are often caused by it."
        if level == 2:
            return base
        return base + " Fix that single line, then recompile; cascading errors usually disappear."
    if status == RE:
        err = _extract_python_error(stderr)
        cat = _PY_ERRORS.get(err) if err else None
        if level == 1:
            return "Your program crashes at runtime on at least one test. Reproduce it locally with that input and read the traceback."
        if level == 2:
            return cat or "Your program raised an unhandled exception. The traceback's last line names the error type -- start there."
        if cat:
            return cat + " Add a guard or fix the assumption that triggers it on the failing input."
        return "Walk through the failing input by hand and find the exact statement that throws."
    if status == TLE:
        msgs = {
            1: "Your solution is correct on small inputs but too slow on the largest. Think about its time complexity.",
            2: "An O(n^2) (or worse) loop usually causes this. Identify the nested work that grows with input size.",
            3: "Replace the slow step with something faster -- sorting, a hash set/map, prefix sums, or two pointers -- depending on what you're searching or aggregating.",
        }
        return msgs[level]
    if status == MLE:
        msgs = {
            1: "You're using too much memory. Are you storing the entire input when you could process it as you read?",
            2: "Avoid building large intermediate lists. Stream the input or keep only the running state you need.",
            3: "Swap the bulky structure for a compact one (a counter, a few accumulators, or in-place updates).",
        }
        return msgs[level]
    if status == OLE:
        return "You're printing far more output than expected -- likely a stray print inside a loop or a debug line."
    if status == WA:
        diff = _diff_summary(expected, actual)
        if level == 1:
            return "Your code runs but gives the wrong answer on at least one test. Compare your output to the expected, paying attention to edge cases."
        if level == 2:
            return diff
        return (diff + " Construct the smallest input that reproduces this and trace your logic step by step; "
                "common culprits are boundary conditions (empty input, n=0/1) and integer vs. float handling.")
    return "Re-run your solution against the sample tests and compare outputs carefully."
