"""
CoachAI — Local-mode routes.

Desktop local mode:
- Discord OAuth, when configured.
- Generic email/Gmail login for the bundled app.
- Local file storage for clips/reports.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.db.models import User
from app.db.session import SessionLocal

router = APIRouter()

DISCORD_AUTHORIZE = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN = "https://discord.com/api/oauth2/token"
DISCORD_ME = "https://discord.com/api/users/@me"


@router.get("/auth/discord/start")
async def discord_start():
    """
    Start Discord sign-in.

    If Discord is not configured, local desktop builds fall back to a local
    token so the app remains usable during testing.
    """
    if not settings.discord_client_id:
        if settings.local_mode:
            token = await _issue_token_for("local@coachai.gg", "Player")
            return RedirectResponse(f"{settings.discord_redirect_deeplink}?token={token}")

        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "Discord OAuth not configured",
        )

    params = urlencode(
        {
            "client_id": settings.discord_client_id,
            "redirect_uri": settings.discord_callback_url,
            "response_type": "code",
            "scope": "identify",
        }
    )

    return RedirectResponse(f"{DISCORD_AUTHORIZE}?{params}")


@router.get("/auth/discord/callback")
async def discord_callback(code: str | None = None, error: str | None = None):
    """
    Exchange Discord code, create/load the user, then deep-link the token back
    into the desktop app.
    """
    if error or not code:
        return RedirectResponse(f"{settings.discord_redirect_deeplink}?error=denied")

    if not settings.discord_client_secret:
        return RedirectResponse(
            f"{settings.discord_redirect_deeplink}?error=discord_secret_missing"
        )

    async with httpx.AsyncClient(timeout=15) as client:
        tok = await client.post(
            DISCORD_TOKEN,
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.discord_callback_url,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        tok.raise_for_status()
        access = tok.json()["access_token"]

        me = await client.get(
            DISCORD_ME,
            headers={"Authorization": f"Bearer {access}"},
        )

        me.raise_for_status()
        profile = me.json()

    email = f"{profile['id']}@discord.coachai"
    name = profile.get("global_name") or profile.get("username") or "Player"

    token = await _issue_token_for(email, name)
    return RedirectResponse(f"{settings.discord_redirect_deeplink}?token={token}")


@router.post("/auth/local")
async def auth_local(payload: dict):
    """
    Direct in-app login for the desktop build. The renderer POSTs
    {"email": "..."} and gets {"token": "..."} straight back — no browser, no
    deep link, no OAuth round trip. This is the reliable path that makes the
    app usable today. (Discord OAuth remains available for when the cloud shim
    exists.) Not password auth — a local-app convenience login.
    """
    if not settings.local_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    email = str(payload.get("email", "")).strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid email")
    name = payload.get("name") or email.split("@")[0] or "Player"
    token = await _issue_token_for(email, name)
    return {"token": token, "plan": "pro"}


@router.get("/auth/email/start")
async def email_start(email: str, name: str | None = None):
    """
    Generic desktop email login (browser + deep-link variant).

    Kept for the OAuth-style flow. The /auth/local POST above is the simpler,
    more reliable path the desktop app uses by default.
    """
    if not settings.local_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    email = email.strip().lower()

    if "@" not in email or "." not in email.split("@")[-1]:
        return RedirectResponse(
            f"{settings.discord_redirect_deeplink}?error=invalid_email"
        )

    display_name = name or email.split("@")[0] or "Player"
    token = await _issue_token_for(email, display_name)

    return RedirectResponse(f"{settings.discord_redirect_deeplink}?token={token}")


async def _issue_token_for(email: str, display_name: str) -> str:
    """
    Upsert a user by email and return a signed JWT.

    Local desktop users get Pro features.
    """
    async with SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

        if not user:
            user = User(
                email=email,
                hashed_password="desktop-local-auth",
                display_name=display_name,
                plan="pro" if settings.local_mode else "free",
            )
            db.add(user)
            await db.commit()

        return create_access_token(user.id)


# ─────────────────────── Local file storage ───────────────────────


def _local_path(key: str) -> Path:
    base = Path(settings.local_data_dir)
    p = (base / key).resolve()

    if not str(p).startswith(str(base.resolve())):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid key")

    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@router.put("/local-storage/{key:path}")
async def local_put(key: str, request: Request):
    """
    Receive a VOD or artifact and write it to local_data_dir.
    """
    if not settings.local_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    data = await request.body()
    _local_path(key).write_bytes(data)

    return {"stored": key, "bytes": len(data)}


@router.get("/local-storage/{key:path}")
async def local_get(key: str):
    """
    Serve a stored artifact.
    """
    if not settings.local_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    p = _local_path(key)

    if not p.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    media = "video/mp4" if key.endswith(".mp4") else "application/octet-stream"
    return Response(p.read_bytes(), media_type=media)
