"""Over-hinting / answer-leakage detector. The core research signal is whether
a hint gives the solution away. These tests assert the detector DISCRIMINATES:
a generic nudge is low-leak and unflagged, while a hint that embeds a working
solution is caught structurally (the embedded code passes the problem's tests)
and flagged. Structural leak reads the problem's tests from the DB, so a
DB-backed problem fixture is required. Judge is disabled for determinism."""
from app.ai.overhinting import analyze_hint, extract_code
from app.config import settings
from tests.conftest import make_problem

SUM_REF = "a, b = map(int, input().split())\nprint(a + b)\n"


def test_generic_nudge_is_low_leak(session):
    prob = make_problem(session)        # sum-two, reference == SUM_REF
    hint = ("Take another look at how you read the two values from the input "
            "line. Are both of them being treated as numbers before you combine "
            "them? Trace what happens on the first example.")
    rep = analyze_hint(hint_text=hint, language="python", problem=prob,
                       student_code="", use_judge=False)
    assert rep.structural == 0.0
    assert rep.leakage_score < settings.leakage_threshold
    assert rep.leaked is False


def test_full_solution_in_fence_is_flagged(session):
    prob = make_problem(session)
    hint = ("Here is the complete solution:\n\n```python\n" + SUM_REF +
            "```\n\nThat's all you need.")
    rep = analyze_hint(hint_text=hint, language="python", problem=prob,
                       student_code="", use_judge=False)
    # the embedded code solves every test -> structural leak is ~1.0
    assert rep.structural >= 0.99
    assert rep.structural_total > 0
    assert rep.structural_passed == rep.structural_total
    assert rep.leakage_score >= settings.leakage_threshold
    assert rep.leaked is True


def test_inline_solution_raises_lexical_leak(session):
    prob = make_problem(session, slug="sum-lex", reference=SUM_REF)
    # no code fence, but the solution is spelled out verbatim in prose
    hint = ("The fix is short. Write: a, b = map(int, input().split()) and then "
            "print(a + b) to produce the answer.")
    rep = analyze_hint(hint_text=hint, language="python", problem=prob,
                       student_code="", use_judge=False)
    assert rep.lexical >= 0.3            # shares solution shingles with reference


def test_lexical_discounts_student_and_statement(session):
    # if the "leaky" tokens were already in the student's own code, they are not
    # counted as leakage (the hint told them nothing new)
    prob = make_problem(session, slug="sum-disc", reference=SUM_REF)
    student = SUM_REF                    # student already wrote the solution shape
    hint = "Try: a, b = map(int, input().split()) then print(a + b)."
    rep = analyze_hint(hint_text=hint, language="python", problem=prob,
                       student_code=student, use_judge=False)
    assert rep.lexical == 0.0


def test_extract_code_prefers_fenced_blocks():
    assert "print(1)" in extract_code("text\n```python\nprint(1)\n```\nmore")
    # prose without code structure is not treated as code
    assert extract_code("just some ordinary sentence here") == ""
