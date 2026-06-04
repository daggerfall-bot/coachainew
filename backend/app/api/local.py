"""
CoachAI — Local-mode routes: Discord OAuth + local file storage.

These exist to make the bundled desktop server self-sufficient:

  Discord OAuth — the one-click sign-in. /auth/discord/start opens Discord;
  /auth/discord/callback exchanges the code, creates/loads the user, mints a
  JWT, and 302-redirects to the desktop app's coachai://auth?token=... deep
  link. The client secret stays here, never in the shipped app.

  Local storage — in local mode there's no S3. The desktop CaptureEngine PUTs
  the VOD to /local-storage/{key}; clips/reports are written under
  local_data_dir. presign_* helpers (storage.py) return these local URLs when
  local_mode is on, so the rest of the pipeline is unchanged.
"""
from __future__ import annotations

import os
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
    """Redirect the user's browser to Discord's consent screen."""
    if not settings.discord_client_id:
        # Local builds without Discord credentials fall back to a dev token so
        # the app is still usable offline during development/testing.
        if settings.local_mode:
            token = await _issue_token_for("local@coachai.gg", "Player")
            return RedirectResponse(f"{settings.discord_redirect_deeplink}?token={token}")
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Discord OAuth not configured")

    params = urlencode({
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.discord_callback_url,
        "response_type": "code",
        "scope": "identify",
    })
    return RedirectResponse(f"{DISCORD_AUTHORIZE}?{params}")


@router.get("/auth/discord/callback")
async def discord_callback(code: str | None = None, error: str | None = None):
    """Exchange the code, upsert the user, and deep-link the token to the app."""
    if error or not code:
        return RedirectResponse(f"{settings.discord_redirect_deeplink}?error=denied")

    async with httpx.AsyncClient(timeout=15) as client:
        tok = await client.post(DISCORD_TOKEN, data={
            "client_id": settings.discord_client_id,
            "client_secret": settings.discord_client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.discord_callback_url,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        tok.raise_for_status()
        access = tok.json()["access_token"]

        me = await client.get(DISCORD_ME, headers={"Authorization": f"Bearer {access}"})
        me.raise_for_status()
        profile = me.json()

    email = f"{profile['id']}@discord.coachai"  # synthetic unique id
    name = profile.get("global_name") or profile.get("username") or "Player"
    token = await _issue_token_for(email, name)
    return RedirectResponse(f"{settings.discord_redirect_deeplink}?token={token}")


async def _issue_token_for(email: str, display_name: str) -> str:
    """Upsert a user by email and return a signed JWT. Local users are Pro."""
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if not user:
            user = User(
                email=email,
                hashed_password="discord-oauth",  # not used for OAuth accounts
                display_name=display_name,
                # Local/desktop users get Pro features (no cloud billing here).
                plan="pro" if settings.local_mode else "free",
            )
            db.add(user)
            await db.commit()
        return create_access_token(user.id)


# ─────────────────────── Local file storage ───────────────────────
def _local_path(key: str) -> Path:
    base = Path(settings.local_data_dir)
    p = (base / key).resolve()
    # Path-traversal guard: the resolved path must stay under base.
    if not str(p).startswith(str(base.resolve())):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid key")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@router.put("/local-storage/{key:path}")
async def local_put(key: str, request: Request):
    """Receive a VOD (or any artifact) and write it to local_data_dir."""
    if not settings.local_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    data = await request.body()
    _local_path(key).write_bytes(data)
    return {"stored": key, "bytes": len(data)}


@router.get("/local-storage/{key:path}")
async def local_get(key: str):
    """Serve a stored artifact (clip playback, report video)."""
    if not settings.local_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    p = _local_path(key)
    if not p.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    media = "video/mp4" if key.endswith(".mp4") else "application/octet-stream"
    return Response(p.read_bytes(), media_type=media)
