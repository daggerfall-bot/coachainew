"""
CoachAI — Local inline analysis runner.

The cloud path runs analysis on a Celery worker. On a player's own machine we
don't want to make them run Redis + a worker process, so this runs the exact
same pipeline inline as a FastAPI background task. The persistence logic is
shared shape with workers/tasks.py; kept separate so the desktop build doesn't
import Celery at all.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import select

from app.analysis.pipeline import run_pipeline
from app.db.models import Clip, Report, Session
from app.db.session import SessionLocal
from app.services.storage import download_file


async def run_analysis_local(session_id: str, vod_key: str, hero_hint: str | None):
    async with SessionLocal() as db:
        sess = (await db.execute(
            select(Session).where(Session.id == session_id))).scalar_one()
        sess.status = "processing"
        await db.commit()

    try:
        with tempfile.TemporaryDirectory() as tmp:
            vod_local = str(Path(tmp) / "vod.webm")
            await download_file(vod_key, vod_local)
            report = await run_pipeline(session_id, vod_local, hero_hint)

        async with SessionLocal() as db:
            db.add(Report(
                session_id=session_id,
                payload=report.model_dump(mode="json"),
                video_key=None,
            ))
            for c in report.clips:
                db.add(Clip(
                    id=c.id, session_id=session_id, title=c.title,
                    map_name=c.map_name, hero=c.hero, t_start=c.t_start,
                    t_end=c.t_end, severity=c.severity.value,
                    category=c.category, s3_key=c.s3_key, ai_note=c.ai_note,
                ))
            sess = (await db.execute(
                select(Session).where(Session.id == session_id))).scalar_one()
            sess.status = "complete"
            sess.hero = report.hero
            sess.duration_sec = report.duration_sec
            sess.composite_score = report.composite_score
            await db.commit()

    except Exception as e:  # noqa: BLE001
        async with SessionLocal() as db:
            sess = (await db.execute(
                select(Session).where(Session.id == session_id))).scalar_one()
            sess.status = "failed"
            sess.error = str(e)[:1000]
            await db.commit()
        raise
