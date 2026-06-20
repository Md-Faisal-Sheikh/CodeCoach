"""Sandboxed process executor.

Isolation applied, strongest-first with graceful degradation:
  * network namespace (`unshare --net`) so submissions cannot reach the network;
  * mount/ipc/uts namespaces when available;
  * privilege drop to an unprivileged user (when running as root);
  * POSIX resource limits (CPU time, address space, file size, #procs, #fds,
    no core dumps), applied in the forked child via _launch.py;
  * wall-clock timeout enforced by the parent, which kills the whole process
    group; output is capped to defend against output bombs.

Everything is probed once at import and cached. On a non-root laptop or on
macOS the executor still enforces CPU/wall limits, memory caps where the OS
supports RLIMIT_AS, and process-group kill -- it simply reports reduced
isolation via `describe()`.
"""
from __future__ import annotations
import os
import sys
import json
import base64
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ..config import settings
from ..constants import OK, TLE, MLE, RE, OLE, IE

_LAUNCH = str(Path(__file__).with_name("_launch.py"))
_GRACE_S = 0.75  # wall-clock grace added on top of the soft CPU limit


@dataclass
class Capabilities:
    platform: str
    is_root: bool
    nobody_uid: Optional[int]
    nobody_gid: Optional[int]
    can_drop_priv: bool
    has_unshare: bool
    unshare_flags: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def use_unshare(self) -> bool:
        return self.has_unshare and bool(self.unshare_flags)

    def isolation_summary(self) -> dict:
        return {
            "platform": self.platform,
            "running_as_root": self.is_root,
            "network_isolation": "--net" in self.unshare_flags,
            "namespaces": self.unshare_flags,
            "privilege_drop": self.can_drop_priv and not settings.disable_privilege_drop,
            "resource_limits": True,
            "wall_clock_kill": True,
            "notes": self.notes,
        }


def _probe_unshare(flags: List[str]) -> bool:
    try:
        p = subprocess.run(
            ["unshare", *flags, "--", "true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
        return p.returncode == 0
    except Exception:
        return False


def _detect() -> Capabilities:
    platform = sys.platform
    is_root = (os.geteuid() == 0) if hasattr(os, "geteuid") else False
    nobody_uid = nobody_gid = None
    can_drop = False
    notes: List[str] = []

    if is_root and not settings.disable_privilege_drop:
        try:
            import pwd
            rec = pwd.getpwnam(settings.sandbox_user)
            nobody_uid, nobody_gid = rec.pw_uid, rec.pw_gid
            can_drop = True
        except Exception:
            notes.append(f"user '{settings.sandbox_user}' not found; not dropping privileges")

    has_unshare = shutil.which("unshare") is not None and platform.startswith("linux")
    flags: List[str] = []
    if has_unshare and not settings.disable_network_isolation:
        if is_root:
            # Prefer the full set; fall back to network-only if the combo fails.
            for candidate in (["--mount", "--uts", "--ipc", "--net"], ["--net"]):
                if _probe_unshare(candidate):
                    flags = candidate
                    break
        else:
            # Unprivileged Linux: user namespaces can grant net isolation.
            for candidate in (
                ["--user", "--map-root-user", "--mount", "--uts", "--ipc", "--net"],
                ["--user", "--map-root-user", "--net"],
            ):
                if _probe_unshare(candidate):
                    flags = candidate
                    break
    if has_unshare and not flags and not settings.disable_network_isolation:
        notes.append("unshare present but no namespace combination succeeded")
    if not platform.startswith("linux"):
        notes.append("non-Linux host: namespace isolation unavailable; rlimits + timeout only")

    return Capabilities(
        platform=platform, is_root=is_root, nobody_uid=nobody_uid, nobody_gid=nobody_gid,
        can_drop_priv=can_drop, has_unshare=has_unshare, unshare_flags=flags, notes=notes,
    )


_CAPS: Optional[Capabilities] = None


def capabilities() -> Capabilities:
    global _CAPS
    if _CAPS is None:
        _CAPS = _detect()
    return _CAPS


def describe() -> dict:
    return capabilities().isolation_summary()


@dataclass
class ExecResult:
    status: str                 # OK / TLE / MLE / RE / OLE / IE
    exit_code: Optional[int]
    signal: Optional[int]
    stdout: str
    stderr: str
    runtime_ms: int
    memory_kb: int
    timed_out: bool
    output_truncated: bool


def _rlimits(time_limit_ms: int, mem_limit_mb: int) -> List[list]:
    cpu_s = max(1, int(round(time_limit_ms / 1000)) + 1)  # SIGXCPU then SIGKILL
    as_bytes = mem_limit_mb * 1024 * 1024
    fsize = max(8 * 1024 * 1024, settings.max_output_bytes * 4)
    return [
        ["CPU", cpu_s, cpu_s + 1],
        ["AS", as_bytes, as_bytes],
        ["DATA", as_bytes, as_bytes],
        ["FSIZE", fsize, fsize],
        ["NPROC", settings.max_processes, settings.max_processes],
        ["NOFILE", 256, 256],
        ["CORE", 0, 0],
    ]


def _minimal_env() -> dict:
    return {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        # cap thread pools so library imports don't fork dozens of helpers
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
    }


def _kill_tree(pid: int) -> None:
    for fn in (
        lambda: os.killpg(os.getpgid(pid), signal.SIGKILL),
        lambda: os.kill(pid, signal.SIGKILL),
    ):
        try:
            fn()
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _read_all(fd: int) -> bytes:
    chunks = []
    try:
        while True:
            b = os.read(fd, 65536)
            if not b:
                break
            chunks.append(b)
    except OSError:
        pass
    return b"".join(chunks)


def run(
    argv: List[str],
    *,
    cwd: str,
    stdin_data: bytes = b"",
    time_limit_ms: Optional[int] = None,
    mem_limit_mb: Optional[int] = None,
) -> ExecResult:
    """Execute argv inside the sandbox and return a structured result."""
    caps = capabilities()
    time_limit_ms = time_limit_ms or settings.default_time_limit_ms
    mem_limit_mb = mem_limit_mb or settings.default_mem_limit_mb
    max_out = settings.max_output_bytes

    wrapper: List[str] = []
    if caps.use_unshare:
        wrapper = ["unshare", *caps.unshare_flags, "--"]

    drop = None
    if caps.can_drop_priv and not settings.disable_privilege_drop:
        drop = {"uid": caps.nobody_uid, "gid": caps.nobody_gid}

    r_fd, w_fd = os.pipe()
    spec = {
        "argv": argv,
        "rlimits": _rlimits(time_limit_ms, mem_limit_mb),
        "drop": drop,
        "metrics_fd": w_fd,
        "cwd": cwd,
    }
    spec_b64 = base64.b64encode(json.dumps(spec).encode()).decode()
    launch_cmd = [*wrapper, sys.executable, _LAUNCH, spec_b64]

    wall_timeout = time_limit_ms / 1000.0 + _GRACE_S
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            launch_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=_minimal_env(),
            pass_fds=(w_fd,),
            close_fds=True,
        )
    except Exception as e:
        os.close(r_fd)
        os.close(w_fd)
        return ExecResult(IE, None, None, "", f"spawn failed: {e!r}", 0, 0, False, False)

    os.close(w_fd)  # parent retains only the read end

    timed_out = False
    try:
        out, err = proc.communicate(input=stdin_data, timeout=wall_timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc.pid)
        try:
            out, err = proc.communicate(timeout=5)
        except Exception:
            out, err = b"", b""
    elapsed_ms = int((time.monotonic() - started) * 1000)

    metrics_raw = _read_all(r_fd)
    os.close(r_fd)
    metrics = {}
    if metrics_raw:
        try:
            metrics = json.loads(metrics_raw.decode())
        except Exception:
            metrics = {}

    truncated = False
    if len(out) > max_out:
        out = out[:max_out]
        truncated = True
    if len(err) > max_out:
        err = err[:max_out]
        truncated = True

    stdout = out.decode("utf-8", errors="replace")
    stderr = err.decode("utf-8", errors="replace")

    exit_code = metrics.get("exit_code")
    sig = metrics.get("signal")
    maxrss = int(metrics.get("maxrss", 0) or 0)
    # ru_maxrss is KB on Linux, bytes on macOS -> normalize to KB.
    memory_kb = maxrss // 1024 if sys.platform == "darwin" else maxrss
    utime = float(metrics.get("utime", 0.0) or 0.0)
    stime = float(metrics.get("stime", 0.0) or 0.0)
    cpu_ms = int((utime + stime) * 1000)
    runtime_ms = cpu_ms if cpu_ms > 0 else elapsed_ms

    status = _classify(
        time_limit_ms, mem_limit_mb, timed_out, exit_code, sig,
        memory_kb, stderr, truncated,
    )
    return ExecResult(
        status=status, exit_code=exit_code, signal=sig,
        stdout=stdout, stderr=stderr, runtime_ms=runtime_ms, memory_kb=memory_kb,
        timed_out=timed_out, output_truncated=truncated,
    )


def _classify(time_limit_ms, mem_limit_mb, timed_out, exit_code, sig,
              memory_kb, stderr, truncated) -> str:
    mem_limit_kb = mem_limit_mb * 1024
    oom_markers = ("MemoryError", "bad_alloc", "OutOfMemoryError",
                   "Cannot allocate memory", "std::bad_alloc")
    looks_oom = any(m in stderr for m in oom_markers) or memory_kb >= int(0.9 * mem_limit_kb)

    if timed_out:
        return TLE
    if sig in (signal.SIGXCPU, signal.SIGKILL) and not looks_oom:
        # SIGKILL with no OOM signal almost always means the CPU limit fired.
        return TLE
    if looks_oom and (exit_code not in (0, None) or sig is not None):
        return MLE
    if truncated and exit_code in (0, None) and sig is None:
        return OLE
    if sig is not None:
        return RE
    if exit_code not in (0, None):
        return RE
    return OK
