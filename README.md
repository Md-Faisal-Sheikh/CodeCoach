# CodeCoach

A coding-education platform built to answer one research question: **do LLM-generated hints help students without giving the solution away?** It pairs a real sandboxed autograder with an LLM hint engine, an automated answer-leakage ("over-hinting") detector, multi-signal plagiarism detection, an instructor dashboard, and a self-contained analysis harness that computes the agreement and effect-size statistics a SIGCSE/ICER/AIED submission needs.

Everything runs offline with no API key (heuristic hints, degraded-but-real sandbox). Add an Anthropic key to switch on the LLM treatment condition. No build step, no external services, SQLite for storage.

## The study

Three things are measured, all on the same submissions:

1. **Hint helpfulness vs. a baseline.** Each failing submission gets two kinds of feedback: the **treatment** (a progressive LLM hint) and the **baseline / control** (the raw compiler or runtime error, with no pedagogy). Instructors rate each on helpfulness and correctness (1–5). The contrast between conditions is the primary outcome; effect size is reported as Cliff's delta.

2. **Autograder ↔ human agreement.** Instructors also grade a sample of submissions by hand. The harness compares human scores against the autograder over ordinal buckets (fail / partial / pass) and reports exact-bucket agreement, adjacent agreement, Cohen's kappa (unweighted and linearly weighted), Pearson, Spearman, and MAE. This establishes that the autograder is trustworthy enough to anchor the rest of the study.

3. **Over-hinting (answer leakage).** The headline risk of helpful hints is that they leak the answer. Every hint is scored for leakage automatically (see below), and instructors independently judge whether each hint "reveals the solution." The harness reports the agreement between the automated flag and human judgement, so the leakage metric itself is validated, not assumed.

**Progressive hint levels** are deliberate: level 1 is a nudge (general area, a guiding question, never the exact bug), level 2 names the specific kind of mistake and where to look, level 3 gives the conceptual strategy and may show at most two lines of *generic* illustrative code. This lets the study look at the helpfulness/leakage trade-off *as a function of hint specificity* rather than treating "a hint" as one thing.

**A deliberate design choice for the hint generator:** the reference solution is **never** given to the model that writes hints — only to the leakage *judge* that audits them. Withholding the solution from the author is itself a leakage-reduction mechanism, and keeping it for the auditor lets the judge catch leaks the author didn't intend.

### What is real vs. simulated

The autograder, sandbox, hint generation, leakage detection, plagiarism detection, and **all of the analysis code** are real and run on real submissions. The packaged `scripts/run_study.py` fills in the *human* parts — instructor ratings and hand grades — with a documented, fixed-seed generative model so the entire pipeline is exercisable end-to-end without recruiting a panel. When real instructors rate real hints through the dashboard, the same `collect → metrics → reports` path produces the genuine tables. Nothing about the statistics is mocked; only the human inputs are stand-ins, and they are clearly labelled as such in the script.

## The sandbox

Untrusted student code runs through a standalone privilege-dropping launcher (not an in-process `preexec_fn`, which is unsafe under a threaded server). Isolation is applied strongest-first and degrades gracefully if the host can't support a layer:

- **Namespaces** (`unshare`): a fresh network namespace (no loopback, no egress), plus mount/IPC/UTS isolation.
- **Privilege drop**: re-exec as `nobody` (setgroups/setgid/setuid) so code runs unprivileged even when the server is root.
- **Resource limits** (POSIX rlimits): address space, CPU time, file size, process count, open files.
- **Wall-clock kill**: a watchdog kills the whole process group so a sleeping or blocked process can't outlive its limit.
- **Output caps**: stdout/stderr are bounded to prevent output-flood.

On a host without root or `unshare` (e.g. macOS, or CI), it automatically falls back to rlimits + wall-clock timeout + process-group isolation and reports exactly which layers are active via `/api/system` and on the dashboard's status strip. Verdicts follow judge convention — `OK / WA / TLE / MLE / RE / CE / OLE` — and the overall verdict is the first failing test's status in execution order, so a time-out on a hidden test surfaces as `TLE`, not a generic wrong-answer.

Note on timing: CPU rlimits have integer-second granularity, so sub-second time limits are effectively floored at ~1s. Problem time limits are in milliseconds but should be set at 1000 ms or above for predictable behaviour.

Supported languages: Python, C, C++, JavaScript (Node), Java — each compiled once (if applicable) and then run per-test. Availability is probed at runtime; the UI only offers toolchains that are actually installed.

## Over-hinting detector

Leakage is estimated from up to three components, combined as `max(structural, 0.85 × lexical)` and then nudged upward (never down) by an optional LLM judge:

- **Structural** — extract any code from the hint (fenced blocks, then indented blocks) and actually run it against the problem's tests in the sandbox. The fraction of tests it passes is how much of a *working* solution the hint handed over. This is the strongest signal: a hint that contains runnable, correct code is caught regardless of wording.
- **Lexical** — k-gram (shingle) overlap between the hint and the reference solution, **discounting** shingles the student already had from the problem statement or their own code. Only *new* solution content counts as leakage.
- **Judge** (optional, LLM) — a 0–4 rating of how much of the solution the hint reveals, used only when an API key is present.

A hint is flagged when the combined score crosses `CODECOACH_LEAKAGE_THRESHOLD` (default 0.5). Offline heuristic hints essentially never leak (they contain no solution code) — a legitimate finding, and the reason the leakage signal is most informative under the LLM condition.

## Plagiarism detection

Pairwise similarity from three signals, robust to the usual evasions:

- **Token winnowing** — fingerprints over a normalised token stream (identifiers, numbers, and strings are canonicalised), so variable renaming and reformatting don't reduce the score.
- **AST node-type overlap** (Python) — fingerprints over the sequence of AST node types, catching structural copies.
- **TF-IDF cosine** — bag-of-shingles similarity as a third, independent view.

For Python the combined score is `0.45·winnow + 0.35·ast + 0.20·tfidf`; for other languages `0.60·winnow + 0.40·tfidf`. Connected components over the thresholded pair graph (union-find) produce clusters. The tool **surfaces candidates and ranks them; it does not accuse** — an instructor reviews the flagged pairs and clusters. (In the seed data, three renamed/reformatted copies of one Kadane solution cluster at 1.00 while an independent brute-force solution sits at 0.49, below the cluster threshold.)

## Architecture

```
app/
  sandbox/    launcher, language registry, runner (isolation), grader (verdicts)
  ai/         LLM client, heuristic fallback, hint generation, over-hinting detector
  similarity/ tokenizer, winnowing, AST normaliser, TF-IDF, detector (clusters)
  research/   metrics (pure-Python stats), report writers (CSV + charts), DB collectors
  routers/    problems, submissions, hints, similarity, instructor, grades, research
  services.py orchestration shared by the API and the study scripts
  models.py   SQLModel tables;  schemas.py  request bodies;  auth.py  token auth
  seed.py     users, problems, and a spread of submissions (incl. a plagiarism cluster)
web/          no-build frontend: Jinja2 templates + vanilla JS/CSS (instrument console)
scripts/      demo.py (quick tour), run_study.py (end-to-end mock study)
tests/        sandbox, grader, similarity, over-hinting, and full API tests
```

The statistics module is pure Python (no numpy/scipy) and validated against known values, so the analysis has no heavy dependencies and runs anywhere.

## Running it

```bash
make install            # pip install -r requirements.txt
make run                # seeds if empty, starts the server on :8000
```

Open http://127.0.0.1:8000 and log in by pasting a token. Seeded tokens:

| Role       | Name              | Token           |
|------------|-------------------|-----------------|
| student    | Ada Lovelace      | `stu-ada-001`   |
| student    | Linus T.          | `stu-linus-002` |
| student    | Margaret Hamilton | `stu-marg-003`  |
| student    | Dennis R.         | `stu-dennis-004`|
| student    | Katherine Johnson | `stu-kath-005`  |
| instructor | Grace Hopper      | `ins-grace-001` |
| instructor | Edsger D.         | `ins-edsger-002`|

Students submit code, see per-test verdicts, and request progressive hints (or the raw-error baseline). Instructors get the dashboard: an overview with per-problem leak rates, a hint-rating queue, a hand-grading queue (the autograder score is hidden until they grade), the plagiarism scanner, and the full research summary.

Other tasks:

```bash
make test               # full test suite (sandbox isolation, grading, similarity, leakage, API)
make demo               # fast capability tour printed to the terminal
make study              # end-to-end mock study -> CSV reports (+ PNG charts if matplotlib present)
make reseed             # wipe and regenerate demo data
make clean              # remove the DB, reports, and caches
```

`make study` writes to `data/reports/`: `hint_quality_by_source.csv`, `grading_agreement.csv`, `leak_agreement.csv`, and `hint_ratings_long.csv` (one row per rating, for re-analysis in R/pandas).

### Enabling the LLM condition

```bash
export ANTHROPIC_API_KEY=sk-ant-...
make run        # or make study
```

With a key, hints come from the configured model (`claude-sonnet-4-6` by default) and the leakage judge from `claude-haiku-4-5-20251001`; the source label switches from `heuristic` to `llm`. Without a key, the heuristic fallback runs — which is also the study's documented offline mode.

## API surface

All endpoints are under `/api`. Auth is a bearer token (`Authorization: Bearer <token>`) or `?token=`.

- `GET /api/system` — sandbox isolation summary, available languages, AI mode, leakage threshold.
- `GET/POST /api/problems`, `GET /api/problems/{id}` — students never receive hidden tests or the reference solution.
- `POST /api/submissions` — submit and grade; `GET /api/submissions/{id}` and `GET /api/submissions`.
- `POST /api/hints` (progressive), `POST /api/hints/baseline` (control), `POST /api/hints/feedback`, `POST /api/hints/rate`, `GET /api/hints/submission/{id}` — students never see leakage diagnostics; instructors do.
- `POST /api/similarity/problem/{id}` — run the plagiarism scan (instructor only).
- `GET /api/instructor/...` — overview, submissions, hint queue, grade queue.
- `POST /api/grades`, `GET /api/grades/submission/{id}` — human grading; the response includes the auto-vs-human delta.
- `GET /api/research/summary`, `POST /api/research/reports` — live study tables and CSV/chart export.

## Configuration

Every knob is environment-overridable with a safe default; see `.env.example`. The notable ones: `ANTHROPIC_API_KEY` and `CODECOACH_AI_OFFLINE` (AI mode), `CODECOACH_DB_URL` (storage), `CODECOACH_TIME_LIMIT_MS` / `CODECOACH_MEM_LIMIT_MB` (sandbox limits), `CODECOACH_DISABLE_NET_NS` / `CODECOACH_DISABLE_PRIV_DROP` (force-disable isolation layers on hosts that don't support them), and `CODECOACH_LEAKAGE_THRESHOLD` (the over-hinting flag cutoff).

## Limitations and honest notes

- The shipped study's human ratings/grades are simulated (fixed seed, documented model). Replace them with real instructor input via the dashboard for a publishable result; the analysis code is unchanged either way.
- Cohen's kappa is reported as chance-level (0.0) when a rater shows no variance — e.g. when no offline heuristic hint leaks, the automated flag is constant. This is expected; the leakage metric becomes discriminating under the LLM condition where some hints do leak.
- Sub-second sandbox time limits are floored at ~1s by CPU-rlimit granularity (above).
- The sandbox is a serious, layered effort, not a claim of perfect isolation. On non-root/macOS hosts some layers are unavailable and the active set is reported transparently; for adversarial or production use, run it inside a container or VM as an additional boundary.
