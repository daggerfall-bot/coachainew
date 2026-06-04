"""
CoachAI — LLM coaching engine.

The deterministic layer (events.py, metrics.py) produces grounded numbers and
structured events. This module hands those to the LLM with deep Overwatch
domain context and asks it to (a) explain what they mean and (b) give specific,
actionable coaching. The LLM never sees raw video and never invents stats — it
reasons over the structured findings, which keeps coaching consistent and cheap.

Two entrypoints:
  generate_insights() — batch, called once when a report is built.
  coach_chat()        — interactive, powers the AI Coach chat with session
                        context loaded.
"""
from __future__ import annotations

import json

from app.core.config import settings
from app.models.schemas import (
    GameEvent, Insight, Severity, SkillScores,
)

OW2_SYSTEM = """You are CoachAI, an elite Overwatch 2 coach. You give specific, \
actionable, encouraging coaching grounded ONLY in the data provided. You never \
invent statistics. You reference concrete numbers from the player's session. \
You understand hero kits, map geometry, cooldown economy, ult tracking, target \
priority, and rank-appropriate fundamentals. Keep advice concrete: tell the \
player exactly what to do differently and why, with the in-game cue to watch for."""


def _events_digest(events: list[GameEvent], limit: int = 40) -> str:
    """Compact, token-efficient serialisation of the most coaching-relevant events."""
    picked = events[:limit]
    rows = []
    for i, e in enumerate(picked):
        rows.append({
            "i": i, "t": round(e.t, 1), "type": e.type.value,
            **{k: v for k, v in e.payload.items() if v is not None},
        })
    return json.dumps(rows, separators=(",", ":"))


def _build_insight_prompt(
    hero: str, maps: list[str], scores: SkillScores,
    stats: dict, events: list[GameEvent],
) -> str:
    return f"""Analyse this Overwatch 2 session and produce coaching insights.

HERO: {hero}
MAPS: {", ".join(maps)}
SKILL SCORES (0-100): {scores.model_dump()}
SESSION STATS: {json.dumps(stats)}
EVENTS (structured, indices for evidence linking): {_events_digest(events)}

Return a JSON array of 4-7 insight objects, ordered most→least important:
{{
  "severity": "critical|improve|info|good",
  "title": "short title",
  "detail": "2-3 sentences. Reference specific numbers. Say exactly what to do.",
  "category": "positioning|ability_timing|ult|target_priority|rotation|resource",
  "evidence_event_indices": [list of event indices supporting this],
  "metric_label": "optional, e.g. 'Deaths before support arrived'",
  "metric_value": "optional, e.g. '7 of 10'",
  "estimated_sr_gain": optional integer
}}
Return ONLY the JSON array, no prose, no markdown fences."""


async def _client():
    import anthropic
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def generate_insights(
    hero: str, maps: list[str], scores: SkillScores,
    stats: dict, events: list[GameEvent],
) -> list[Insight]:
    client = await _client()
    prompt = _build_insight_prompt(hero, maps, scores, stats, events)
    msg = await client.messages.create(
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        system=OW2_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(b.text for b in msg.content if b.type == "text").strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [Insight(
            severity=Severity.INFO, title="Analysis incomplete",
            detail="The coaching model returned an unparseable response. Retry.",
            category="system",
        )]
    out = []
    for d in data:
        try:
            out.append(Insight(**d))
        except Exception:
            continue
    return out


async def generate_recommendations(insights: list[Insight], hero: str) -> list[str]:
    """Distil insights into 3 concrete drills/habits for next session."""
    client = await _client()
    digest = [{"title": i.title, "detail": i.detail, "cat": i.category}
              for i in insights if i.severity in (Severity.CRITICAL, Severity.IMPROVE)]
    msg = await client.messages.create(
        model=settings.llm_model, max_tokens=600, system=OW2_SYSTEM,
        messages=[{"role": "user", "content":
            f"Hero: {hero}. Issues: {json.dumps(digest)}. "
            "Give exactly 3 specific practice habits for the next session. "
            "Each: one sentence, a concrete in-game rule with a cue. "
            "Return a JSON array of 3 strings only."}],
    )
    raw = "".join(b.text for b in msg.content if b.type == "text").strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


async def coach_chat(
    user_message: str, history: list[dict], session_context: str
) -> str:
    """Interactive coaching chat. `session_context` is the loaded report summary."""
    client = await _client()
    system = OW2_SYSTEM + "\n\nLOADED SESSION CONTEXT:\n" + session_context
    msgs = history[-8:] + [{"role": "user", "content": user_message}]
    msg = await client.messages.create(
        model=settings.llm_model, max_tokens=1000, system=system, messages=msgs,
    )
    return "".join(b.text for b in msg.content if b.type == "text")
