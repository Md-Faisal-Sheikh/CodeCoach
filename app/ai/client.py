"""Thin Anthropic wrapper with a hard offline boundary.

If ANTHROPIC_API_KEY is set and the SDK imports, `complete()` calls the Messages
API. Otherwise callers fall back to deterministic heuristics, so the whole
platform runs end-to-end with no key (useful for CI, demos, and as a baseline
condition in the study)."""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..config import settings


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    ok: bool
    error: str = ""


_CLIENT = None
_IMPORT_OK = None


def _get_client():
    global _CLIENT, _IMPORT_OK
    if _CLIENT is not None:
        return _CLIENT
    try:
        import anthropic
        _IMPORT_OK = True
        _CLIENT = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return _CLIENT
    except Exception:
        _IMPORT_OK = False
        return None


def available() -> bool:
    if not settings.ai_enabled:
        return False
    return _get_client() is not None


def complete(system: str, user: str, *, model: Optional[str] = None,
             max_tokens: int = 600, temperature: float = 0.2) -> LLMResponse:
    model = model or settings.hint_model
    if not settings.ai_enabled:
        return LLMResponse("", 0, 0, model, False, "AI disabled (no API key / offline mode)")
    client = _get_client()
    if client is None:
        return LLMResponse("", 0, 0, model, False, "anthropic SDK unavailable")
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"
        ).strip()
        u = resp.usage
        return LLMResponse(text, u.input_tokens, u.output_tokens, model, True)
    except Exception as e:  # network / auth / rate-limit
        return LLMResponse("", 0, 0, model, False, f"{type(e).__name__}: {e}")
