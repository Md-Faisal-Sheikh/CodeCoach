"""End-to-end mock study runner.

Pipeline (identical code path to the live API, via app.services):
  seed -> add extra buggy submissions for sample size -> grade everything ->
  for each failing submission emit a baseline + progressive LLM/heuristic hints ->
  simulate instructor ratings and human grades from a documented generative
  model -> compute agreement/effect-size metrics -> write CSVs (+ charts) ->
  print a summary.

The ratings and human grades here are SIMULATED (clearly, with a fixed RNG seed)
so the full analysis pipeline is exercisable without a human panel. With real
instructors rating real hints through the dashboard, the same collect/metrics/
reports code produces the genuine study tables — nothing about the analysis is
mock. Run offline (heuristic hints, source='heuristic') or set ANTHROPIC_API_KEY
for real LLM hints (source='llm').

    python scripts/run_study.py
"""
from __future__ import annotations

import os
import random
import sys

# allow running as `python scripts/run_study.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select

from app.db import engine, init_db
from app.config import settings, DATA_DIR
from app.constants import OK, SRC_BASELINE
from app.models import (User, Problem, Submission, Hint, HintRating, HumanGrade)
from app import services, seed as seed_mod
from app.research import collect, metrics, reports

RNG = random.Random(20240517)


# --------------------------------------------------------------------------- #
# extra buggy submissions to give the study some sample size
# (slug, username, source) — each is a plausible wrong attempt
# --------------------------------------------------------------------------- #
EXTRA: list[tuple[str, str, str]] = [
    # sum-two: prints difference / concatenates strings
    ("sum-two", "margaret", "a, b = map(int, input().split())\nprint(a - b)\n"),
    ("sum-two", "katherine", "a, b = input().split()\nprint(a + b)\n"),
    # fizzbuzz: off-by-one (range stops at n) / wrong divisor
    ("fizzbuzz", "ada",
     "n = int(input())\nfor i in range(1, n):\n"
     "    if i % 15 == 0:\n        print('FizzBuzz')\n"
     "    elif i % 3 == 0:\n        print('Fizz')\n"
     "    elif i % 5 == 0:\n        print('Buzz')\n    else:\n        print(i)\n"),
    ("fizzbuzz", "dennis",
     "n = int(input())\nfor i in range(1, n + 1):\n"
     "    if i % 2 == 0:\n        print('Fizz')\n    else:\n        print(i)\n"),
    # count-vowels: counts consonants / includes y
    ("count-vowels", "margaret",
     "s = input()\nprint(sum(1 for c in s.lower() if c in 'aeiouy'))\n"),
    ("count-vowels", "linus",
     "s = input()\nprint(len(s))\n"),
    # max-subarray: forgets negatives (starts best at 0) / wrong init
    ("max-subarray", "linus",
     "n = int(input())\nxs = list(map(int, input().split()))\n"
     "best = 0\ncur = 0\nfor x in xs:\n    cur = max(0, cur + x)\n"
     "    best = max(best, cur)\nprint(best)\n"),
    # fib: off-by-one (returns F(n+1)) / wrong base
    ("fib", "margaret",
     "n = int(input())\na, b = 0, 1\nfor _ in range(n):\n    a, b = b, a + b\nprint(b)\n"),
    ("fib", "dennis",
     "n = int(input())\na, b = 1, 1\nfor _ in range(n):\n    a, b = b, a + b\nprint(a)\n"),
]


def _add_extra(session: Session, users, problems) -> int:
    added = 0
    for slug, username, source in EXTRA:
        prob = problems[slug]
        user = users[username]
        sub = Submission(problem_id=prob.id, user_id=user.id,
                         language=prob.language, source_code=source)
        session.add(sub)
        session.commit()
        session.refresh(sub)
        services.grade_submission(session, sub)
        added += 1
    return added


# --------------------------------------------------------------------------- #
# simulated human judgements (documented generative model, fixed seed)
# --------------------------------------------------------------------------- #
def _clamp_int(x: float, lo=1, hi=5) -> int:
    return max(lo, min(hi, int(round(x))))


def _simulate_rating(hint: Hint) -> dict:
    """Helpfulness/correctness/reveals for one hint.

    Treatment (llm/heuristic) hints are modelled as more helpful than the raw
    baseline error; correctness is high for both (the baseline error is true,
    just unhelpful). Human 'reveals_solution' tracks the automated leak flag
    with ~12% disagreement so leak-agreement kappa is high but < 1.
    """
    if hint.source == SRC_BASELINE:
        helpfulness = _clamp_int(RNG.gauss(2.3, 0.8))
        correctness = _clamp_int(RNG.gauss(3.6, 0.8))
        reveals = RNG.random() < 0.03            # raw errors rarely reveal
    else:
        # higher levels are more helpful but also leak more
        base_help = 3.6 + 0.25 * hint.level
        helpfulness = _clamp_int(RNG.gauss(base_help, 0.7))
        correctness = _clamp_int(RNG.gauss(4.2, 0.6))
        # human agrees with the automated leak flag most of the time
        flip = RNG.random() < 0.12
        reveals = (not hint.leaked) if flip else bool(hint.leaked)
    return {"helpfulness": helpfulness, "correctness": correctness,
            "reveals_solution": reveals}


def _simulate_human_score(auto_score: float) -> float:
    """Human grade vs autograder. Mostly agrees within noise; ~20% of the time
    a grader awards partial credit the binary tests don't (right approach,
    wrong output), creating realistic disagreement."""
    if RNG.random() < 0.8:
        return min(1.0, max(0.0, auto_score + RNG.gauss(0, 0.04)))
    # generous partial credit on a near-miss
    if auto_score < 0.999:
        return min(1.0, max(0.0, auto_score + RNG.uniform(0.1, 0.35)))
    return auto_score


def main() -> None:
    init_db()
    with Session(engine) as session:
        print("== seeding ==")
        if seed_mod.is_seeded(session):
            seed_mod._wipe_dynamic(session)
        base = seed_mod.seed_all(session, grade=True)
        users, problems = base["users"], base["problems"]
        extra = _add_extra(session, users, problems)
        print(f"   +{extra} extra buggy submissions\n")

        raters = [u for u in users.values() if u.role in ("instructor", "admin")]
        graders = raters

        all_subs = session.exec(select(Submission)).all()
        failing = [s for s in all_subs if s.status != OK]
        print(f"== generating hints for {len(failing)} failing submissions "
              f"(AI mode: {'llm' if settings.ai_enabled else 'offline/heuristic'}) ==")

        n_hints = n_baselines = 0
        for sub in failing:
            prob = problems_by_id(problems, sub.problem_id)
            # control condition
            bl = services.create_baseline(session, sub)
            n_baselines += 1
            session.add(HintRating(hint_id=bl.id,
                                   rater_user_id=RNG.choice(raters).id,
                                   **_simulate_rating(bl)))
            # progressive treatment hints
            for level in range(1, (prob.max_hint_level if prob else 3) + 1):
                h = services.create_hint(session, sub, level, use_judge=True)
                n_hints += 1
                session.add(HintRating(hint_id=h.id,
                                       rater_user_id=RNG.choice(raters).id,
                                       **_simulate_rating(h)))
        session.commit()
        print(f"   {n_hints} treatment hints + {n_baselines} baselines, all rated\n")

        # human grades on a sample of submissions (mix of pass/fail)
        sample = RNG.sample(all_subs, k=min(len(all_subs), 24))
        for sub in sample:
            session.add(HumanGrade(submission_id=sub.id,
                                   grader_user_id=RNG.choice(graders).id,
                                   score=_simulate_human_score(sub.score)))
        session.commit()
        print(f"== {len(sample)} submissions human-graded ==\n")

        # ---- analysis ----
        rows = collect.hint_rating_rows(session)
        groups = metrics.group_hint_stats(rows)
        auto, human = collect.grading_pairs(session)
        ga = metrics.grading_agreement(auto, human)
        la = metrics.leak_agreement(rows)

        out_dir = DATA_DIR / "reports"
        p1 = reports.write_hint_quality_csv(groups)
        p2 = reports.write_grading_agreement_csv(ga)
        p3 = reports.write_leak_agreement_csv(la)
        p4 = reports.write_per_hint_csv(rows)
        charts = []
        charts += [reports.chart_hint_quality(groups)] if hasattr(reports, "chart_hint_quality") else []
        charts += [reports.chart_leak_rates(groups)] if hasattr(reports, "chart_leak_rates") else []

        print(reports.summary_text(groups, ga, la))

        # effect size: treatment source vs baseline on helpfulness
        def vals(src, key):
            return [r[key] for r in rows if r["source"] == src and r.get(key)]
        treat_src = "llm" if settings.ai_enabled else "heuristic"
        for key in ("helpfulness", "correctness"):
            t, b = vals(treat_src, key), vals("baseline", key)
            if t and b:
                d = metrics.cliffs_delta(t, b)
                print(f"EFFECT {key:<12} {treat_src} mean={metrics.mean(t):.2f} "
                      f"vs baseline mean={metrics.mean(b):.2f}  Cliff's d={d:+.3f}")

        print("\nCSV reports written to:", out_dir)
        for p in (p1, p2, p3, p4):
            print("  -", p)
        if charts and all(charts):
            print("Charts:")
            for c in charts:
                if c:
                    print("  -", c)
        else:
            print("(charts skipped — matplotlib not installed)")


def problems_by_id(problems: dict, pid: int):
    for p in problems.values():
        if p.id == pid:
            return p
    return None


if __name__ == "__main__":
    main()
