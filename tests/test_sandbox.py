"""Sandbox runner: correct execution, resource-limit classification, and
network isolation (when the platform supports it). These assert the engine
actually enforces limits rather than just shelling out."""
import sys

from app.sandbox import runner
from app.constants import OK, TLE, MLE, RE


PY = sys.executable or "python3"


def test_capabilities_shape():
    caps = runner.capabilities()
    assert caps.platform in ("linux", "darwin", "other")
    # describe() is what the UI/system endpoint surfaces
    d = runner.describe()
    assert "resource_limits" in d and "wall_clock_kill" in d


def test_ok_and_stdout(tmp_path):
    res = runner.run([PY, "-c", "print(40 + 2)"], cwd=str(tmp_path),
                     time_limit_ms=3000, mem_limit_mb=256)
    assert res.status == OK
    assert res.stdout.strip() == "42"
    assert res.exit_code == 0


def test_stdin_is_piped(tmp_path):
    res = runner.run([PY, "-c", "import sys; print(sys.stdin.read().strip()[::-1])"],
                     cwd=str(tmp_path), stdin_data=b"abcde",
                     time_limit_ms=3000, mem_limit_mb=256)
    assert res.status == OK
    assert res.stdout.strip() == "edcba"


def test_timeout_is_killed(tmp_path):
    # A busy loop must be stopped and classified TLE. The kill may come from the
    # wall-clock watchdog or the CPU rlimit (integer-second granularity, so the
    # effective floor is ~1s); either way the verdict is TLE and it must not hang.
    res = runner.run([PY, "-c", "while True: pass"], cwd=str(tmp_path),
                     time_limit_ms=400, mem_limit_mb=256)
    assert res.status == TLE
    assert res.runtime_ms < 3000      # bounded: it was actually killed
    assert res.exit_code != 0 or res.signal is not None


def test_runtime_error(tmp_path):
    res = runner.run([PY, "-c", "raise SystemExit(3)"], cwd=str(tmp_path),
                     time_limit_ms=3000, mem_limit_mb=256)
    assert res.status == RE
    assert res.exit_code == 3


def test_memory_limit(tmp_path):
    # allocate well past the cap; the rlimit must stop it (MLE, or RE if the
    # allocator raises MemoryError first — both mean the limit was enforced)
    code = "x = bytearray(400 * 1024 * 1024); print(len(x))"
    res = runner.run([PY, "-c", code], cwd=str(tmp_path),
                     time_limit_ms=4000, mem_limit_mb=64)
    assert res.status in (MLE, RE)
    assert res.stdout.strip() != "419430400"   # never completed the allocation


def test_network_blocked_when_isolated(tmp_path):
    caps = runner.capabilities()
    if "--net" not in caps.unshare_flags:
        import pytest
        pytest.skip("network namespace isolation not available on this host")
    code = ("import socket; s=socket.socket(); "
            "s.settimeout(2); s.connect(('1.1.1.1', 80)); print('CONNECTED')")
    res = runner.run([PY, "-c", code], cwd=str(tmp_path),
                     time_limit_ms=4000, mem_limit_mb=256)
    assert "CONNECTED" not in res.stdout
    assert res.status == RE     # connect() raises inside the empty net namespace
