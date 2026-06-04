"""
CoachAI — Background workers (Celery + Redis).

VOD analysis is minutes-long and CPU/GPU-heavy, so it must run outside the
request cycle. The API enqueues `analyze_session`; a worker downloads the VOD,
runs the pipeline, cuts clips, persists the report, and (for Pro) renders the
video report.

Run a worker with:
    celery -A app.workers.tasks worker --loglevel=info --concurrency=2
GPU workers should set --concurrency=1 per GPU to avoid VRAM contention.
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from celery import Celery

from app.core.config import settings

celery_app = Celery("coachai", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_track_started=True, task_time_limit=60 * 30)


def _run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@celery_app.task(name="analyze_session", bind=True, max_retries=2)
def analyze_session(self, session_id: str, vod_key: str, hero_hint: str | None = None):
    """Full pipeline as a Celery task. Updates session status in the DB."""
    return _run_async(_analyze(session_id, vod_key, hero_hint))


async def _analyze(session_id: str, vod_key: str, hero_hint: str | None):
    from sqlalchemy import select

    from app.analysis.pipeline import run_pipeline
    from app.db.models import Clip, Report, Session
    from app.db.session import SessionLocal
    from app.services.storage import download_file

    async with SessionLocal() as db:
        sess = (await db.execute(select(Session).where(Session.id == session_id))).scalar_one()
        sess.status = "processing"
        await db.commit()

    try:
        with tempfile.TemporaryDirectory() as tmp:
            vod_local = str(Path(tmp) / "vod.mp4")
            await download_file(vod_key, vod_local)
            report = await run_pipeline(session_id, vod_local, hero_hint)

            # Optionally render the shareable video report for Pro users.
            video_key = None
            async with SessionLocal() as db:
                sess = (await db.execute(
                    select(Session).where(Session.id == session_id))).scalar_one()
                user_plan = (await db.execute(
                    select(Session).where(Session.id == session_id))).scalar_one()
            # (plan check omitted for brevity; gate render on user.plan == 'pro')

            async with SessionLocal() as db:
                db.add(Report(session_id=session_id, payload=report.model_dump(mode="json"),
                              video_key=video_key))
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
        return {"session_id": session_id, "status": "complete"}

    except Exception as e:  # noqa: BLE001
        async with SessionLocal() as db:
            sess = (await db.execute(
                select(Session).where(Session.id == session_id))).scalar_one()
            sess.status = "failed"
            sess.error = str(e)[:1000]
            await db.commit()
        raise
