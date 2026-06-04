"""
CoachAI — Analysis pipeline orchestrator.

Wires the stages together into one call:

  VOD ─▶ sample frames ─▶ vision backend ─▶ FrameStates
      ─▶ detect events + overextensions
      ─▶ compute skill scores + stats
      ─▶ LLM insights + recommendations
      ─▶ cut clips for flagged events (FFmpeg)
      ─▶ assemble CoachingReport

Runs as a background job (see workers/tasks.py) because a 47-minute VOD takes
minutes to process — never block an HTTP request on it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.analysis import coach, metrics
from app.analysis.events import detect_events, detect_overextensions
from app.models.schemas import (
    ClipRef, CoachingReport, Game, GameEvent, Severity,
)
from app.services.clips import cut_clips_for_events
from app.vision.inference.backend import get_vision_backend
from app.vision.inference.frames import extract_states


def _severity_for_event(e: GameEvent) -> Severity:
    if e.payload.get("flag") == "overextension":
        return Severity.CRITICAL
    if e.type.value == "death":
        return Severity.IMPROVE
    if e.type.value == "ult_used" and e.payload.get("ult_before", 1) >= 0.95:
        return Severity.GOOD
    return Severity.INFO


async def run_pipeline(session_id: str, vod_path: str, hero_hint: str | None = None) -> CoachingReport:
    backend = get_vision_backend()
    try:
        states = await extract_states(vod_path, backend)
    finally:
        await backend.close()

    hero = hero_hint or next((s.hero for s in states if s.hero), "Unknown")
    maps = sorted({s.map_name for s in states if s.map_name})
    duration = states[-1].t if states else 0.0

    events = detect_events(states) + detect_overextensions(states)
    events.sort(key=lambda e: e.t)

    scores = metrics.compute_skill_scores(states, events, hero)
    stats = metrics.session_summary_stats(events)

    insights = await coach.generate_insights(hero, maps, scores, stats, events)
    recommendations = await coach.generate_recommendations(insights, hero)

    # Cut clips for the most coaching-relevant events (caps cost: top N).
    clip_events = [
        e for e in events
        if e.payload.get("flag") == "overextension"
        or e.type.value in ("death", "ult_used")
    ][:14]
    cut = await cut_clips_for_events(session_id, vod_path, clip_events)
    clips = [
        ClipRef(
            id=str(uuid.uuid4()), title=_clip_title(e), map_name=e.map_name or "",
            hero=e.hero or hero, t_start=e.frame_start, t_end=e.frame_end,
            severity=_severity_for_event(e), category=_clip_category(e),
            s3_key=key,
        )
        for e, key in zip(clip_events, cut)
    ]

    summary = _summary_markdown(hero, maps, scores, stats)

    return CoachingReport(
        session_id=session_id, game=Game.OVERWATCH2, hero=hero, maps=maps,
        duration_sec=duration, generated_at=datetime.now(timezone.utc),
        composite_score=scores.composite, skill_scores=scores,
        insights=insights, clips=clips, summary_markdown=summary,
        recommendations=recommendations,
        ai_confidence=round(
            sum(s.confidence for s in states) / max(len(states), 1), 2
        ) if states else 0.0,
    )


def _clip_title(e: GameEvent) -> str:
    if e.payload.get("flag") == "overextension":
        return "Overextension — pushed without support"
    if e.type.value == "death":
        return "Death — review positioning"
    if e.type.value == "ult_used":
        return "Ultimate used — efficiency check"
    return e.type.value


def _clip_category(e: GameEvent) -> str:
    if e.payload.get("flag") == "overextension":
        return "positioning"
    if e.type.value == "ult_used":
        return "ult"
    return "general"


def _summary_markdown(hero, maps, scores, stats) -> str:
    return (
        f"## {hero} session summary\n"
        f"- Maps: {', '.join(maps) or 'n/a'}\n"
        f"- K/D: {stats['kd']} ({stats['kills']}/{stats['deaths']})\n"
        f"- Composite score: **{scores.composite}/100**\n"
        f"- Overextensions flagged: {stats['overextensions']}\n"
    )
