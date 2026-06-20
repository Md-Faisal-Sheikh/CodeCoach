"""Shared status codes and role/source labels."""
# Per-test and per-submission verdicts (judge-style).
OK = "OK"      # correct output
WA = "WA"      # wrong answer
TLE = "TLE"    # time limit exceeded
MLE = "MLE"    # memory limit exceeded
RE = "RE"      # runtime error (non-zero exit or fatal signal)
CE = "CE"      # compile error
OLE = "OLE"    # output limit exceeded
IE = "IE"      # internal sandbox error

RUN_STATUSES = [OK, WA, TLE, MLE, RE, CE, OLE, IE]
FAIL_STATUSES = [WA, TLE, MLE, RE, CE, OLE, IE]

ROLE_STUDENT = "student"
ROLE_INSTRUCTOR = "instructor"
ROLE_ADMIN = "admin"
ROLES = [ROLE_STUDENT, ROLE_INSTRUCTOR, ROLE_ADMIN]

# Source of a hint / feedback row.
SRC_BASELINE = "baseline"     # raw compiler/runtime error (control condition)
SRC_LLM = "llm"               # LLM-generated pedagogical hint (treatment)
SRC_HEURISTIC = "heuristic"   # offline static-analysis hint (LLM fallback)

# Output comparison modes.
CMP_EXACT = "exact"
CMP_WHITESPACE = "whitespace"   # trim trailing ws per line + strip trailing blank lines
CMP_FLOAT = "float"             # token-wise numeric comparison with tolerance
