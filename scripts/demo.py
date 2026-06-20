"""Quick capability smoke test (fast — no rating simulation). Seeds if needed,
then walks one submission through grading, hint + baseline generation with
leakage analysis, runs plagiarism detection on the seeded cluster, and prints
the sandbox isolation summary.

    python scripts/demo.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import Session, select

from app.db import engine, init_db
from app.config import settings
from app.constants import OK
from app.models import Problem, Submission, User
from app.sandbox import runner
from app.similarity.detector import analyze
from app import services, seed as seed_mod


def line(c="-"):
    print(c * 64)


def main() -> None:
    init_db()
    with Session(engine) as session:
        if not seed_mod.is_seeded(session):
            print("seeding ...")
            seed_mod.seed_all(session, grade=True)
            print()

        line("=")
        print("SANDBOX ISOLATION")
        line()
        for k, v in runner.describe().items():
            print(f"  {k:<20} {v}")
        print(f"  AI mode             {'llm' if settings.ai_enabled else 'offline/heuristic'}")

        # a failing submission to demonstrate hints
        failing = session.exec(
            select(Submission).where(Submission.status != OK)).first()
        if failing:
            prob = session.get(Problem, failing.problem_id)
            user = session.get(User, failing.user_id)
            line("=")
            print(f"SUBMISSION  {user.display_name} -> {prob.title}")
            line()
            print(f"  verdict: {failing.status}  "
                  f"({failing.passed_count}/{failing.total_count} tests, "
                  f"score {failing.score:.2f})")
            print("\n  --- baseline (control: raw error) ---")
            bl = services.create_baseline(session, failing)
            print("  " + bl.content.strip().replace("\n", "\n  ")[:400])

            print("\n  --- LLM/heuristic hint (level 1) ---")
            h1 = services.create_hint(session, failing, 1, use_judge=False)
            print(f"  [source={h1.source} leak={h1.leakage_score:.2f} "
                  f"flagged={h1.leaked}]")
            print("  " + h1.content.strip().replace("\n", "\n  ")[:400])

            print("\n  --- hint (level 3, most explicit) ---")
            h3 = services.create_hint(session, failing, 3, use_judge=False)
            print(f"  [source={h3.source} leak={h3.leakage_score:.2f} "
                  f"flagged={h3.leaked}]")
            print("  " + h3.content.strip().replace("\n", "\n  ")[:400])

        # plagiarism cluster on max-subarray
        prob = session.exec(
            select(Problem).where(Problem.slug == "max-subarray")).first()
        if prob:
            subs = session.exec(
                select(Submission).where(Submission.problem_id == prob.id)).all()
            uname = {u.id: u.display_name for u in session.exec(select(User)).all()}
            report = analyze([(s.id, s.source_code) for s in subs], "python")
            who = {s.id: uname[s.user_id] for s in subs}
            line("=")
            print(f"PLAGIARISM SCAN  ({prob.title})")
            line()
            for p in sorted(report.pairs, key=lambda x: -x.combined)[:6]:
                print(f"  {who[p.a_id]:<18} ~ {who[p.b_id]:<18} "
                      f"combined={p.combined:.2f} (w={p.winnow:.2f} "
                      f"a={p.ast if p.ast is None else round(p.ast,2)} t={p.tfidf:.2f})")
            for c in report.clusters:
                names = sorted(who[m] for m in c.members)
                print(f"  CLUSTER: {names}  max={c.max_score:.2f}")
        line("=")
        print("ok — start the server with ./run.sh and log in with a seeded token "
              "(e.g. ins-grace-001).")


if __name__ == "__main__":
    main()
