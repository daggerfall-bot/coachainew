"""CoachAI — Reports, clips, and AI coach chat routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, require_pro
from app.analysis.coach import coach_chat
from app.db.models import Clip, Report, Session, User
from app.db.session import get_db
from app.services.storage import presign_get

router = APIRouter()


@router.get("/reports/{session_id}")
async def get_report(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    sess = (await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )).scalar_one_or_none()
    if not sess:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if sess.status != "complete":
        return {"status": sess.status}
    report = (await db.execute(
        select(Report).where(Report.session_id == session_id)
    )).scalar_one_or_none()
    if not report:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not ready")
    payload = report.payload
    if report.video_key:
        payload["video_url"] = await presign_get(report.video_key)
    return {"status": "complete", "report": payload}


@router.get("/sessions/{session_id}/clips")
async def list_clips(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    sess = (await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )).scalar_one_or_none()
    if not sess:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    clips = (await db.execute(
        select(Clip).where(Clip.session_id == session_id)
    )).scalars().all()
    out = []
    for c in clips:
        url = await presign_get(c.s3_key) if c.s3_key else None
        out.append({
            "id": c.id, "title": c.title, "map": c.map_name, "hero": c.hero,
            "t_start": c.t_start, "t_end": c.t_end, "severity": c.severity,
            "category": c.category, "url": url, "ai_note": c.ai_note,
        })
    return out


# ─────────────────────────── Coach chat ───────────────────────────
class ChatIn(BaseModel):
    session_id: str
    message: str
    history: list[dict] = []


@router.post("/coach/chat")
async def chat(
    body: ChatIn,
    user: User = Depends(require_pro),  # chat is a Pro feature
    db: AsyncSession = Depends(get_db),
):
    report = (await db.execute(
        select(Report).join(Session).where(
            Session.id == body.session_id, Session.user_id == user.id
        )
    )).scalar_one_or_none()
    context = ""
    if report:
        p = report.payload
        context = (
            f"Hero: {p.get('hero')}\nMaps: {p.get('maps')}\n"
            f"Composite score: {p.get('composite_score')}\n"
            f"Skill scores: {p.get('skill_scores')}\n"
            f"Top insights: {[i.get('title') for i in p.get('insights', [])][:5]}\n"
            f"Player rank: {user.current_rank} → target {user.target_rank}"
        )
    reply = await coach_chat(body.message, body.history, context)
    return {"reply": reply}
