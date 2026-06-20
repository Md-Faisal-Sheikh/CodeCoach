"""Seed data: users, problems with test cases, and a spread of submissions
(correct, wrong-answer, runtime-error, time-limit, and a plagiarism cluster).

Running this makes every part of the platform demonstrable immediately: the
dashboard has data, the autograder has graded runs, similarity has a real
cluster to find, and there are failing submissions for hints to act on.

    python -m app.seed            # seed if empty
    python -m app.seed --force    # wipe submissions/hints/etc and reseed

Tokens printed at the end are what you paste into the login screen.
"""
from __future__ import annotations

import sys
from typing import List, Tuple

from sqlmodel import Session, select, delete

from .db import engine, init_db
from .constants import (ROLE_STUDENT, ROLE_INSTRUCTOR, CMP_WHITESPACE)
from .models import (User, Problem, TestCase, Submission, RunResult, Hint,
                     HintRating, HumanGrade, SimilarityEdge)
from . import services


# --------------------------------------------------------------------------- #
# users
# --------------------------------------------------------------------------- #
USERS: List[dict] = [
    # students
    dict(username="ada",   role=ROLE_STUDENT,    token="stu-ada-001",   display_name="Ada Lovelace"),
    dict(username="linus", role=ROLE_STUDENT,    token="stu-linus-002", display_name="Linus T."),
    dict(username="margaret", role=ROLE_STUDENT, token="stu-marg-003",  display_name="Margaret Hamilton"),
    dict(username="dennis", role=ROLE_STUDENT,   token="stu-dennis-004", display_name="Dennis R."),
    dict(username="katherine", role=ROLE_STUDENT, token="stu-kath-005", display_name="Katherine Johnson"),
    # instructors / graders / raters
    dict(username="grace", role=ROLE_INSTRUCTOR, token="ins-grace-001", display_name="Grace Hopper"),
    dict(username="edsger", role=ROLE_INSTRUCTOR, token="ins-edsger-002", display_name="Edsger D."),
]


# --------------------------------------------------------------------------- #
# problems + test cases
# --------------------------------------------------------------------------- #
def _tc(name, stdin, out, *, hidden=False, weight=1.0, ordering=0):
    return dict(name=name, stdin=stdin, expected_stdout=out, hidden=hidden,
                weight=weight, comparison=CMP_WHITESPACE, ordering=ordering)


PROBLEMS: List[dict] = [
    dict(
        slug="sum-two",
        title="Sum of Two Integers",
        difficulty="easy",
        tags="io,arithmetic",
        statement=(
            "Read two integers `a` and `b` from a single line separated by a "
            "space. Print their sum.\n\n"
            "**Input**: one line, two space-separated integers.\n"
            "**Output**: a single integer, `a + b`."
        ),
        reference_solution=(
            "a, b = map(int, input().split())\n"
            "print(a + b)\n"
        ),
        tests=[
            _tc("small",      "2 3",                "5",       ordering=0),
            _tc("two-digit",  "10 20",              "30",      ordering=1),
            _tc("negatives",  "-5 5",               "0",       hidden=True, ordering=2),
            _tc("large",      "1000000 2000000",    "3000000", hidden=True, ordering=3),
        ],
    ),
    dict(
        slug="fizzbuzz",
        title="FizzBuzz",
        difficulty="easy",
        tags="loops,conditionals",
        statement=(
            "Read an integer `n`. For each `i` from 1 to `n` (inclusive) print, "
            "one per line:\n\n"
            "- `FizzBuzz` if `i` is divisible by both 3 and 5,\n"
            "- `Fizz` if divisible by 3,\n"
            "- `Buzz` if divisible by 5,\n"
            "- otherwise the number `i` itself."
        ),
        reference_solution=(
            "n = int(input())\n"
            "for i in range(1, n + 1):\n"
            "    if i % 15 == 0:\n"
            "        print('FizzBuzz')\n"
            "    elif i % 3 == 0:\n"
            "        print('Fizz')\n"
            "    elif i % 5 == 0:\n"
            "        print('Buzz')\n"
            "    else:\n"
            "        print(i)\n"
        ),
        tests=[
            _tc("n5",  "5",  "1\n2\nFizz\n4\nBuzz", ordering=0),
            _tc("n3",  "3",  "1\n2\nFizz",          ordering=1),
            _tc("n15", "15",
                "1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz",
                hidden=True, ordering=2),
            _tc("n1",  "1",  "1",                   hidden=True, ordering=3),
        ],
    ),
    dict(
        slug="count-vowels",
        title="Count Vowels",
        difficulty="easy",
        tags="strings",
        statement=(
            "Read one line of text. Print the number of vowels it contains. "
            "Vowels are `a e i o u`, counted case-insensitively.\n\n"
            "**Output**: a single integer."
        ),
        reference_solution=(
            "s = input()\n"
            "print(sum(1 for c in s.lower() if c in 'aeiou'))\n"
        ),
        tests=[
            _tc("phrase", "hello world", "3", ordering=0),
            _tc("upper",  "AEIOU",       "5", ordering=1),
            _tc("none",   "rhythm xyz",  "0", hidden=True, ordering=2),
            _tc("mixed",  "Programming", "3", hidden=True, ordering=3),
        ],
    ),
    dict(
        slug="max-subarray",
        title="Maximum Subarray Sum",
        difficulty="medium",
        tags="arrays,dynamic-programming",
        statement=(
            "First line: an integer `n`. Second line: `n` space-separated "
            "integers. Print the maximum sum obtainable from a contiguous, "
            "non-empty subarray.\n\n"
            "The array may contain negative numbers; a single element is a "
            "valid subarray."
        ),
        reference_solution=(
            "n = int(input())\n"
            "xs = list(map(int, input().split()))\n"
            "best = cur = xs[0]\n"
            "for x in xs[1:]:\n"
            "    cur = max(x, cur + x)\n"
            "    best = max(best, cur)\n"
            "print(best)\n"
        ),
        tests=[
            _tc("classic", "9\n-2 1 -3 4 -1 2 1 -5 4", "6", ordering=0),
            _tc("single-neg", "1\n-5", "-5", ordering=1),
            _tc("all-pos", "5\n1 2 3 4 5", "15", hidden=True, ordering=2),
            _tc("all-neg", "4\n-1 -2 -3 -4", "-1", hidden=True, ordering=3),
        ],
    ),
    dict(
        slug="fib",
        title="Nth Fibonacci",
        difficulty="medium",
        tags="recursion,dynamic-programming",
        statement=(
            "Read an integer `n` (0-indexed: F(0)=0, F(1)=1). Print F(n).\n\n"
            "`n` can be as large as 90, so an exponential-time solution will "
            "time out — use an iterative or memoised approach."
        ),
        reference_solution=(
            "n = int(input())\n"
            "a, b = 0, 1\n"
            "for _ in range(n):\n"
            "    a, b = b, a + b\n"
            "print(a)\n"
        ),
        tests=[
            _tc("f10", "10", "55", ordering=0),
            _tc("f0",  "0",  "0",  ordering=1),
            _tc("f1",  "1",  "1",  hidden=True, ordering=2),
            _tc("f50", "50", "12586269025", hidden=True, ordering=3),
            _tc("f90", "90", "2880067194370816120", hidden=True, ordering=4),
        ],
    ),
]


# --------------------------------------------------------------------------- #
# submissions  (problem_slug, username, label, source)
# label is just a human tag for the seed log; the verdict is computed.
# --------------------------------------------------------------------------- #
SUBMISSIONS: List[Tuple[str, str, str, str]] = [
    # ---- sum-two ----
    ("sum-two", "ada", "correct",
     "a, b = map(int, input().split())\nprint(a + b)\n"),
    ("sum-two", "linus", "correct-alt-style",
     "parts = input().split()\nx = int(parts[0])\ny = int(parts[1])\nprint(x + y)\n"),
    ("sum-two", "dennis", "runtime-error",
     "nums = input().split()\nprint(int(nums[0]) + int(nums[2]))\n"),

    # ---- fizzbuzz ----  (wrong condition order -> WA on multiples of 15)
    ("fizzbuzz", "margaret", "wrong-answer",
     "n = int(input())\nfor i in range(1, n + 1):\n"
     "    if i % 3 == 0:\n        print('Fizz')\n"
     "    elif i % 5 == 0:\n        print('Buzz')\n"
     "    elif i % 15 == 0:\n        print('FizzBuzz')\n"
     "    else:\n        print(i)\n"),
    ("fizzbuzz", "katherine", "correct",
     "n = int(input())\nfor i in range(1, n + 1):\n"
     "    if i % 15 == 0:\n        print('FizzBuzz')\n"
     "    elif i % 3 == 0:\n        print('Fizz')\n"
     "    elif i % 5 == 0:\n        print('Buzz')\n"
     "    else:\n        print(i)\n"),

    # ---- count-vowels ----  (case bug -> WA on uppercase test)
    ("count-vowels", "ada", "wrong-answer",
     "s = input()\nprint(sum(1 for c in s if c in 'aeiou'))\n"),

    # ---- fib ----  (naive recursion -> TLE on large n)
    ("fib", "linus", "time-limit",
     "def f(n):\n    if n < 2:\n        return n\n    return f(n - 1) + f(n - 2)\n"
     "print(f(int(input())))\n"),
    ("fib", "katherine", "correct",
     "n = int(input())\na, b = 0, 1\nfor _ in range(n):\n    a, b = b, a + b\nprint(a)\n"),

    # ---- max-subarray : PLAGIARISM CLUSTER (A original, B renamed, C reformatted) + D independent ----
    ("max-subarray", "ada", "kadane-original",
     "n = int(input())\nxs = list(map(int, input().split()))\n"
     "best = cur = xs[0]\nfor x in xs[1:]:\n"
     "    cur = max(x, cur + x)\n    best = max(best, cur)\nprint(best)\n"),
    ("max-subarray", "dennis", "kadane-renamed",
     "m = int(input())\narr = list(map(int, input().split()))\n"
     "hi = run = arr[0]\nfor v in arr[1:]:\n"
     "    run = max(v, run + v)\n    hi = max(hi, run)\nprint(hi)\n"),
    ("max-subarray", "margaret", "kadane-reformatted",
     "n = int(input())\nnums = list(map(int, input().split()))\n\n"
     "# kadane's algorithm\nbest = cur = nums[0]\nfor x in nums[1:]:\n"
     "    cur = max(x, cur + x)   # extend or restart\n"
     "    best = max(best, cur)\n\nprint(best)\n"),
    ("max-subarray", "katherine", "brute-force-independent",
     "n = int(input())\na = list(map(int, input().split()))\n"
     "ans = a[0]\nfor i in range(n):\n    s = 0\n    for j in range(i, n):\n"
     "        s += a[j]\n        if s > ans:\n            ans = s\nprint(ans)\n"),
]


# --------------------------------------------------------------------------- #
# seeding
# --------------------------------------------------------------------------- #
def _wipe_dynamic(session: Session) -> None:
    """Remove everything except nothing — full reset of all tables."""
    for model in (SimilarityEdge, HintRating, HumanGrade, RunResult, Hint,
                  Submission, TestCase, Problem, User):
        session.exec(delete(model))
    session.commit()


def seed_all(session: Session, *, grade: bool = True) -> dict:
    users = {}
    for u in USERS:
        row = User(**u)
        session.add(row)
        users[u["username"]] = row
    session.commit()
    for row in users.values():
        session.refresh(row)

    problems = {}
    for p in PROBLEMS:
        tests = p.pop("tests")
        prob = Problem(**p)
        session.add(prob)
        session.commit()
        session.refresh(prob)
        for t in tests:
            session.add(TestCase(problem_id=prob.id, **t))
        session.commit()
        problems[prob.slug] = prob
        p["tests"] = tests  # restore for idempotency if called twice in-process

    graded = 0
    sub_ids: List[int] = []
    for slug, username, label, source in SUBMISSIONS:
        prob = problems[slug]
        user = users[username]
        sub = Submission(
            problem_id=prob.id, user_id=user.id, language=prob.language,
            source_code=source,
        )
        session.add(sub)
        session.commit()
        session.refresh(sub)
        sub_ids.append(sub.id)
        if grade:
            report = services.grade_submission(session, sub)
            graded += 1
            print(f"  graded {slug:<13} {username:<10} {label:<24} "
                  f"-> {report.status} ({report.passed_count}/{report.total_count})")

    return {"users": users, "problems": problems, "submission_ids": sub_ids,
            "graded": graded}


def is_seeded(session: Session) -> bool:
    return session.exec(select(User)).first() is not None


def main() -> None:
    force = "--force" in sys.argv
    no_grade = "--no-grade" in sys.argv
    init_db()
    with Session(engine) as session:
        if is_seeded(session):
            if not force:
                print("Already seeded. Use --force to wipe and reseed.")
                return
            print("Wiping existing data ...")
            _wipe_dynamic(session)
        print("Seeding users, problems, and submissions ...")
        result = seed_all(session, grade=not no_grade)
        print(f"\nDone: {len(result['users'])} users, "
              f"{len(result['problems'])} problems, "
              f"{len(result['submission_ids'])} submissions, "
              f"{result['graded']} graded.\n")
        print("Login tokens:")
        for u in USERS:
            print(f"  {u['role']:<11} {u['display_name']:<20} {u['token']}")


if __name__ == "__main__":
    main()
