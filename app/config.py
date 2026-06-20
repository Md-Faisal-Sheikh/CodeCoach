"""Central configuration. All knobs are env-overridable so the same code runs
offline (heuristic AI, degraded sandbox) or fully wired (Anthropic API, root
namespaces) without edits."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    db_url: str = os.getenv("CODECOACH_DB_URL", f"sqlite:///{DATA_DIR / 'codecoach.db'}")
    secret: str = os.getenv("CODECOACH_SECRET", "dev-insecure-secret-change-me")

    # --- AI ---
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    hint_model: str = os.getenv("CODECOACH_HINT_MODEL", "claude-sonnet-4-6")
    judge_model: str = os.getenv("CODECOACH_JUDGE_MODEL", "claude-haiku-4-5-20251001")
    ai_offline: bool = _bool("CODECOACH_AI_OFFLINE", False)

    # --- Sandbox ---
    default_time_limit_ms: int = _int("CODECOACH_TIME_LIMIT_MS", 5000)
    default_mem_limit_mb: int = _int("CODECOACH_MEM_LIMIT_MB", 256)
    max_output_bytes: int = _int("CODECOACH_MAX_OUTPUT_BYTES", 256 * 1024)
    compile_time_limit_ms: int = _int("CODECOACH_COMPILE_LIMIT_MS", 15000)
    max_processes: int = _int("CODECOACH_MAX_PROCESSES", 64)
    sandbox_user: str = os.getenv("CODECOACH_SANDBOX_USER", "nobody")
    disable_network_isolation: bool = _bool("CODECOACH_DISABLE_NET_NS", False)
    disable_privilege_drop: bool = _bool("CODECOACH_DISABLE_PRIV_DROP", False)

    # --- Over-hinting ---
    leakage_threshold: float = float(os.getenv("CODECOACH_LEAKAGE_THRESHOLD", "0.5"))

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key) and not self.ai_offline


settings = Settings()
