"""CoachAI — Shared API dependencies (current user, plan gating)."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.models import User
from app.db.session import get_db


async def current_user(
    authorization: str = Header(...), db: AsyncSession = Depends(get_db)
) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    user_id = decode_token(authorization.removeprefix("Bearer ").strip())
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


def require_pro(user: User = Depends(current_user)) -> User:
    if user.plan != "pro":
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            "This feature requires a Pro subscription (£10/mo).",
        )
    return user
