"""CoachAI — Auth + session API routes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import Session, User
from app.db.session import get_db
from app.services.storage import presign_get, presign_put

router = APIRouter()


# ─────────────────────────── Auth ───────────────────────────
class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    display_name: str = "Player"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    plan: str


@router.post("/auth/register", response_model=TokenOut)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    exists = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=body.email, hashed_password=hash_password(body.password),
                display_name=body.display_name)
    db.add(user)
    await db.commit()
    return TokenOut(access_token=create_access_token(user.id), plan=user.plan)


@router.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad credentials")
    return TokenOut(access_token=create_access_token(user.id), plan=user.plan)


# ─────────────────────────── Sessions ───────────────────────────
class UploadUrlOut(BaseModel):
    session_id: str
    upload_url: str
    vod_key: str


@router.post("/sessions/upload-url", response_model=UploadUrlOut)
async def get_upload_url(
    hero: str | None = None,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mint a presigned URL so the client uploads the VOD straight to storage.
    Enforces the free-tier monthly session cap.
    """
    if user.plan == "free":
        month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0)
        count = (await db.execute(
            select(func.count()).select_from(Session)
            .where(Session.user_id == user.id, Session.created_at >= month_start)
        )).scalar_one()
        if count >= settings.free_sessions_per_month:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                f"Free plan is limited to {settings.free_sessions_per_month} sessions/month. "
                "Upgrade to Pro (£10/mo) for unlimited.",
            )

    sess = Session(user_id=user.id, hero=hero, status="queued")
    db.add(sess)
    await db.commit()
    vod_key = f"vods/{user.id}/{sess.id}.mp4"
    sess.vod_key = vod_key
    await db.commit()
    return UploadUrlOut(
        session_id=sess.id, upload_url=await presign_put(vod_key), vod_key=vod_key
    )


@router.post("/sessions/{session_id}/analyze")
async def start_analysis(
    session_id: str,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Call after the VOD upload completes. Enqueues the analysis job.

    Cloud mode dispatches to a Celery worker (Redis-backed, scalable). Local
    desktop mode has no Redis/Celery, so it runs the same pipeline inline as a
    FastAPI background task on the user's own machine.
    """
    sess = (await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )).scalar_one_or_none()
    if not sess:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")

    if settings.local_mode:
        from app.workers.local_runner import run_analysis_local
        background.add_task(run_analysis_local, sess.id, sess.vod_key, sess.hero)
    else:
        # Cloud: dispatch to Celery. Imported here so the bundled desktop server
        # boots without celery/redis installed.
        from app.workers.tasks import analyze_session
        analyze_session.delay(sess.id, sess.vod_key, sess.hero)
    return {"status": "queued", "session_id": sess.id}


@router.get("/sessions")
async def list_sessions(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    rows = (await db.execute(
        select(Session).where(Session.user_id == user.id)
        .order_by(Session.created_at.desc())
    )).scalars().all()
    return [
        {"id": s.id, "hero": s.hero, "status": s.status,
         "score": s.composite_score, "created_at": s.created_at,
         "duration_sec": s.duration_sec}
        for s in rows
    ]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    sess = (await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )).scalar_one_or_none()
    if not sess:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return {"id": sess.id, "status": sess.status, "hero": sess.hero,
            "score": sess.composite_score, "error": sess.error}
