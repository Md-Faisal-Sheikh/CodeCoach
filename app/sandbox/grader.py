"""Compile-and-run grading against I/O test cases.

A submission is compiled once (if the language needs it) and each test case is
executed in a fresh isolated run. Output comparison supports exact, whitespace-
tolerant, and numeric-with-tolerance modes. Returns a structured report the API
layer persists as Submission + RunResult rows."""
from __future__ import annotations
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional

from ..config import settings
from ..constants import OK, WA, CE, IE, CMP_EXACT, CMP_WHITESPACE, CMP_FLOAT
from .languages import get_language, Language
from . import runner


# ----------------------------- output comparison -----------------------------

def _normalize_ws(text: str) -> str:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _floats_equal(a: str, b: str, tol: float) -> bool:
    try:
        fa, fb = float(a), float(b)
    except ValueError:
        return a == b
    if fa == fb:
        return True
    return abs(fa - fb) <= tol + tol * max(abs(fa), abs(fb))


def compare_output(expected: str, actual: str, mode: str, float_tol: float) -> bool:
    if mode == CMP_EXACT:
        return expected == actual
    if mode == CMP_FLOAT:
        et = _normalize_ws(expected).split()
        at = _normalize_ws(actual).split()
        if len(et) != len(at):
            return False
        return all(_floats_equal(e, a, float_tol) for e, a in zip(et, at))
    # default: whitespace-tolerant
    return _normalize_ws(expected) == _normalize_ws(actual)


# ------------------------------- data carriers -------------------------------

@dataclass
class TestSpec:
    id: int
    name: str
    stdin: str
    expected_stdout: str
    weight: float = 1.0
    hidden: bool = False
    comparison: str = CMP_WHITESPACE
    float_tol: float = 1e-6
    time_limit_ms: Optional[int] = None


@dataclass
class TestOutcome:
    testcase_id: int
    name: str
    hidden: bool
    status: str
    passed: bool
    weight: float
    runtime_ms: int
    memory_kb: int
    exit_code: Optional[int]
    signal: Optional[int]
    stdout_excerpt: str
    stderr_excerpt: str


@dataclass
class GradeReport:
    status: str
    score: float                 # weighted fraction in [0, 1]
    passed_count: int
    total_count: int
    runtime_ms: int
    memory_kb: int
    compile_log: str
    outcomes: List[TestOutcome] = field(default_factory=list)


_EXCERPT = 4000


def _excerpt(text: str) -> str:
    if len(text) <= _EXCERPT:
        return text
    return text[:_EXCERPT] + f"\n...[truncated {len(text) - _EXCERPT} chars]"


def _make_workspace() -> str:
    d = tempfile.mkdtemp(prefix="cc_run_")
    # world rwx so the dropped 'nobody' user can read source + write artifacts
    os.chmod(d, 0o777)
    return d


def _write_source(workspace: str, lang: Language, source: str) -> str:
    path = os.path.join(workspace, lang.source_filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    os.chmod(path, 0o644)
    return path


def grade(source: str, language: str, tests: List[TestSpec],
          *, time_limit_ms: int, memory_limit_mb: int) -> GradeReport:
    try:
        lang = get_language(language)
    except KeyError as e:
        return GradeReport(IE, 0.0, 0, len(tests), 0, 0, f"{e}", [])
    if not lang.is_available():
        return GradeReport(IE, 0.0, 0, len(tests), 0, 0,
                           f"language toolchain '{language}' is not installed", [])

    workspace = _make_workspace()
    try:
        _write_source(workspace, lang, source)

        # ---- compile phase ----
        compile_log = ""
        compile_argv = lang.compile_argv()
        if compile_argv is not None:
            cres = runner.run(
                compile_argv, cwd=workspace, stdin_data=b"",
                time_limit_ms=settings.compile_time_limit_ms,
                mem_limit_mb=max(memory_limit_mb, 512),
            )
            compile_log = _excerpt(cres.stderr or cres.stdout)
            if cres.status != OK:
                outcomes = [
                    TestOutcome(t.id, t.name, t.hidden, CE, False, t.weight, 0, 0,
                                cres.exit_code, cres.signal, "", _excerpt(cres.stderr))
                    for t in tests
                ]
                return GradeReport(CE, 0.0, 0, len(tests), 0, 0, compile_log, outcomes)
            # make the compiled artifact executable by the dropped user
            if lang.exe:
                exe_path = os.path.join(workspace, lang.exe)
                if os.path.exists(exe_path):
                    os.chmod(exe_path, 0o755)
            for fn in os.listdir(workspace):
                try:
                    os.chmod(os.path.join(workspace, fn),
                             os.stat(os.path.join(workspace, fn)).st_mode | stat.S_IROTH)
                except OSError:
                    pass

        run_argv = lang.run_argv()

        # ---- run phase ----
        outcomes: List[TestOutcome] = []
        total_weight = sum(max(0.0, t.weight) for t in tests) or 1.0
        earned = 0.0
        max_rt = max_mem = 0

        for t in tests:
            res = runner.run(
                run_argv, cwd=workspace, stdin_data=t.stdin.encode("utf-8"),
                time_limit_ms=t.time_limit_ms or time_limit_ms,
                mem_limit_mb=memory_limit_mb,
            )
            max_rt = max(max_rt, res.runtime_ms)
            max_mem = max(max_mem, res.memory_kb)

            if res.status == OK:
                ok = compare_output(t.expected_stdout, res.stdout, t.comparison, t.float_tol)
                status = OK if ok else WA
                passed = ok
            else:
                status = res.status   # TLE / MLE / RE / OLE / IE
                passed = False

            if passed:
                earned += max(0.0, t.weight)

            outcomes.append(TestOutcome(
                testcase_id=t.id, name=t.name, hidden=t.hidden, status=status,
                passed=passed, weight=t.weight, runtime_ms=res.runtime_ms,
                memory_kb=res.memory_kb, exit_code=res.exit_code, signal=res.signal,
                stdout_excerpt=_excerpt(res.stdout), stderr_excerpt=_excerpt(res.stderr),
            ))

        passed_count = sum(1 for o in outcomes if o.passed)
        score = earned / total_weight
        # Overall verdict (judge convention): OK iff every test passes;
        # otherwise the status of the first failing test in execution order.
        # This surfaces TLE/RE/MLE on hidden tests instead of masking them as WA.
        if outcomes and passed_count == len(outcomes):
            overall = OK
        else:
            overall = next((o.status for o in outcomes if not o.passed), WA)

        return GradeReport(
            status=overall, score=score, passed_count=passed_count,
            total_count=len(tests), runtime_ms=max_rt, memory_kb=max_mem,
            compile_log=compile_log, outcomes=outcomes,
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
