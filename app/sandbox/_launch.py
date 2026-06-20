"""Standalone sandbox launcher. Run as a child process (optionally wrapped in
`unshare`) by the executor. Pure stdlib, imports nothing from the app, so it
runs fine after dropping to an unprivileged user inside an isolated namespace.

Responsibilities (in a single-threaded freshly-forked process, which is why we
do this here instead of via Popen.preexec_fn, which is unsafe under threads):
  1. setsid()  -> become process-group leader so the parent can kill the tree.
  2. fork()    -> child applies rlimits + drops privileges + execs the target;
                  parent wait4()s and reports rusage on the metrics fd.

Spec is passed as base64(json) in argv[1]:
  {argv, rlimits:[[NAME,soft,hard],...], drop:{uid,gid}|null, metrics_fd:int|null, cwd:str|null}
"""
import os
import sys
import json
import base64
import resource


def _apply_rlimits(rlimits):
    name_map = {
        "CPU": resource.RLIMIT_CPU,
        "AS": resource.RLIMIT_AS,
        "DATA": resource.RLIMIT_DATA,
        "FSIZE": resource.RLIMIT_FSIZE,
        "NPROC": resource.RLIMIT_NPROC,
        "NOFILE": resource.RLIMIT_NOFILE,
        "CORE": resource.RLIMIT_CORE,
        "STACK": resource.RLIMIT_STACK,
    }
    for nm, soft, hard in rlimits:
        rc = name_map.get(nm)
        if rc is None:
            continue
        try:
            resource.setrlimit(rc, (soft, hard))
        except (ValueError, OSError):
            # Some limits (e.g. RLIMIT_AS) are unsupported on macOS; skip rather
            # than abort so the rest of the sandbox still applies.
            pass


def main():
    spec = json.loads(base64.b64decode(sys.argv[1]))
    argv = spec["argv"]
    rlimits = spec.get("rlimits", [])
    drop = spec.get("drop")
    metrics_fd = spec.get("metrics_fd")
    cwd = spec.get("cwd")

    os.setsid()  # new session => we lead a fresh process group

    pid = os.fork()
    if pid == 0:
        # ---------- child: become the target ----------
        try:
            if metrics_fd is not None:
                try:
                    os.close(metrics_fd)  # untrusted target must not hold metrics pipe
                except OSError:
                    pass
            if cwd:
                os.chdir(cwd)
            _apply_rlimits(rlimits)
            if drop:
                # order matters: groups, then gid, then uid (cannot regain after)
                try:
                    os.setgroups([])
                except (OSError, PermissionError):
                    pass
                os.setgid(int(drop["gid"]))
                os.setuid(int(drop["uid"]))
            os.execvp(argv[0], argv)
        except Exception as e:  # pragma: no cover - exec failures
            try:
                os.write(2, ("SANDBOX-EXEC-FAIL: %r\n" % (e,)).encode())
            except OSError:
                pass
            os._exit(127)
    else:
        # ---------- parent: supervise + report rusage ----------
        try:
            _, status, ru = os.wait4(pid, 0)
        except ChildProcessError:
            status, ru = 0, None
        exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else None
        sig = os.WTERMSIG(status) if os.WIFSIGNALED(status) else None
        payload = json.dumps({
            "exit_code": exit_code,
            "signal": sig,
            "maxrss": getattr(ru, "ru_maxrss", 0) if ru else 0,
            "utime": getattr(ru, "ru_utime", 0.0) if ru else 0.0,
            "stime": getattr(ru, "ru_stime", 0.0) if ru else 0.0,
        }).encode()
        if metrics_fd is not None:
            try:
                os.write(metrics_fd, payload)
                os.close(metrics_fd)
            except OSError:
                pass
        os._exit(0)


if __name__ == "__main__":
    main()
