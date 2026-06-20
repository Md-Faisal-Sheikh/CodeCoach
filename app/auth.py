"""Token-based auth. Each user has an opaque bearer token; role gates access.

This is intentionally simple (no password hashing / sessions) because the
platform is a research instrument, not a production multi-tenant service. Tokens
are passed as `Authorization: Bearer <token>` or `?token=` for convenience in
the browser dashboard.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, Query, status
from sqlmodel import Session, select

from .constants import ROLE_INSTRUCTOR, ROLE_ADMIN
from .db import get_session
from .models import User


def _extract_token(authorization: Optional[str], token_q: Optional[str]) -> Optional[str]:
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        return authorization.strip()
    return token_q


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
) -> User:
    tok = _extract_token(authorization, token)
    if not tok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    user = session.exec(select(User).where(User.token == tok)).first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    return user


def require_instructor(user: User = Depends(get_current_user)) -> User:
    if user.role not in (ROLE_INSTRUCTOR, ROLE_ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "instructor role required")
    return user


def optional_user(
    authorization: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
) -> Optional[User]:
    tok = _extract_token(authorization, token)
    if not tok:
        return None
    return session.exec(select(User).where(User.token == tok)).first()
