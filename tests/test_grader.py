"""Grader: output-comparison semantics and end-to-end grading of a submission
through the real sandbox (compile-once for compiled langs, per-test verdicts,
weighted score, first-failing overall status)."""
from app.sandbox.grader import grade, compare_output, TestSpec
from app.constants import OK, WA, RE, CE, TLE, CMP_EXACT, CMP_WHITESPACE, CMP_FLOAT


def _spec(name, stdin, out, *, weight=1.0, hidden=False, cmp=CMP_WHITESPACE, tol=1e-6):
    return TestSpec(id=hash(name) & 0xffff, name=name, stdin=stdin,
                    expected_stdout=out, weight=weight, hidden=hidden,
                    comparison=cmp, float_tol=tol, time_limit_ms=4000)


# ---- comparison semantics ----
def test_whitespace_tolerant():
    assert compare_output("5\n", "5", CMP_WHITESPACE, 1e-6)          # trailing newline
    assert compare_output("a b ", "a b", CMP_WHITESPACE, 1e-6)       # trailing space
    assert compare_output("1\n2\n", "1\n2\n\n", CMP_WHITESPACE, 1e-6)  # trailing blank line
    assert not compare_output("5", "6", CMP_WHITESPACE, 1e-6)
    # internal spacing is significant (only trailing ws/blank lines are trimmed)
    assert not compare_output("a b", "a   b", CMP_WHITESPACE, 1e-6)


def test_exact_is_strict():
    assert compare_output("5\n", "5\n", CMP_EXACT, 1e-6)
    assert not compare_output("5\n", "5", CMP_EXACT, 1e-6)


def test_float_tolerance():
    assert compare_output("3.14159", "3.14159265", CMP_FLOAT, 1e-3)
    assert not compare_output("3.14", "3.20", CMP_FLOAT, 1e-3)
    assert compare_output("1.0 2.0", "1.0001 1.9999", CMP_FLOAT, 1e-2)


# ---- end-to-end grading ----
REF = "a, b = map(int, input().split())\nprint(a + b)\n"
TESTS = [_spec("t1", "2 3", "5"), _spec("t2", "10 20", "30"),
         _spec("t3", "-1 1", "0", hidden=True)]


def test_all_pass():
    rep = grade(REF, "python", TESTS, time_limit_ms=4000, memory_limit_mb=256)
    assert rep.status == OK
    assert rep.passed_count == 3 and rep.total_count == 3
    assert rep.score == 1.0


def test_wrong_answer():
    src = "a, b = map(int, input().split())\nprint(a * b)\n"   # wrong op
    rep = grade(src, "python", TESTS, time_limit_ms=4000, memory_limit_mb=256)
    assert rep.status == WA
    assert rep.passed_count < 3


def test_runtime_error():
    src = "a, b = map(int, input().split())\nprint(a + undefined_name)\n"
    rep = grade(src, "python", TESTS, time_limit_ms=4000, memory_limit_mb=256)
    assert rep.status == RE
    assert rep.passed_count == 0


def test_weighted_partial_score():
    tests = [_spec("t1", "2 3", "5", weight=3.0),
             _spec("t2", "1 1", "99", weight=1.0)]   # second is unsatisfiable
    rep = grade(REF, "python", tests, time_limit_ms=4000, memory_limit_mb=256)
    assert rep.status == WA
    assert abs(rep.score - 0.75) < 1e-9    # 3 of 4 weight earned


def test_first_failing_status_wins():
    # passes the visible tests, times out on the hidden one -> overall TLE
    slow = _spec("slow", "1 1", "2", hidden=True)
    tests = [_spec("t1", "2 3", "5"), slow]
    src = ("a, b = map(int, input().split())\n"
           "if a == 1:\n    while True: pass\n"
           "print(a + b)\n")
    rep = grade(src, "python", tests, time_limit_ms=400, memory_limit_mb=256)
    assert rep.status == TLE
    assert rep.passed_count == 1


def test_compile_error_for_c():
    from app.sandbox.languages import get_language
    if not get_language("c").is_available():
        import pytest
        pytest.skip("no C toolchain")
    bad = "int main(){ this is not valid c )"
    rep = grade(bad, "c", [_spec("t", "", "x")],
                time_limit_ms=4000, memory_limit_mb=256)
    assert rep.status == CE
    assert rep.compile_log.strip() != ""
