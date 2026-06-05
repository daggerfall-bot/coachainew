"""CoachAI — Auth: password hashing + JWT."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

# The password context is created lazily. Local desktop mode signs in via
# Discord/email OAuth and never hashes a password, so we avoid importing passlib
# /bcrypt at startup — that keeps a passlib<->bcrypt version mismatch from being
# able to crash the bundled server before it ever serves /health.
_pwd = None


def _ctx():
    global _pwd
    if _pwd is None:
        from passlib.context import CryptContext
        _pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return _pwd


def hash_password(p: str) -> str:
    return _ctx().hash(p)


def verify_password(p: str, hashed: str) -> bool:
    return _ctx().verify(p, hashed)


def create_access_token(sub: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_ttl_min)
    return jwt.encode({"sub": sub, "exp": expire}, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
