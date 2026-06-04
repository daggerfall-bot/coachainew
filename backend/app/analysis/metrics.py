"""
CoachAI — Metrics & skill scoring.

Computes the deterministic, explainable numbers behind the report:
positioning score, ult efficiency, ability timing quality, etc. These feed
both the UI gauges and the LLM prompt (the LLM explains the numbers; it
doesn't invent them — which keeps the coaching grounded and consistent).
"""
from __future__ import annotations

from statistics import mean

from app.models.schemas import EventType, FrameState, GameEvent, SkillScores

# Per-hero reference benchmarks (expand over time from your own aggregate data).
# These are the "what good looks like" anchors used to score a session.
HERO_BENCHMARKS = {
    "Tracer": {
        "recall_health_ideal": 0.5,   # recall around 50% hp, not 90%+
        "min_blinks_on_engage": 2,
        "ult_min_targets": 2,
        "gm_accuracy": 0.48,
    },
    # default fallback used for any hero without a specific entry
    "_default": {
        "recall_health_ideal": 0.5,
        "min_blinks_on_engage": 1,
        "ult_min_targets": 1,
        "gm_accuracy": 0.45,
    },
}


def _bench(hero: str | None) -> dict:
    return HERO_BENCHMARKS.get(hero or "", HERO_BENCHMARKS["_default"])


def positioning_score(states: list[FrameState], deaths: list[GameEvent]) -> int:
    """
    Lower when deaths happen far from allies / close to enemies. Scaled 0..100.
    """
    if not deaths:
        return 75  # no deaths sampled → assume cautious
    bad = 0
    for d in deaths:
        ally = d.payload.get("nearest_ally_m")
        if ally is not None and ally > 15:
            bad += 1
    ratio = bad / len(deaths)
    return max(0, round(100 - ratio * 80))


def ult_efficiency(events: list[GameEvent], hero: str | None) -> int:
    ult_uses = [e for e in events if e.type == EventType.ULT_USED]
    if not ult_uses:
        return 50
    # Reward popping ult near full charge (not wasting overcharge).
    charges = [e.payload.get("ult_before", 1.0) for e in ult_uses]
    avg = mean(charges)
    return max(0, min(100, round(avg * 100)))


def ability_usage_score(events: list[GameEvent], hero: str | None) -> int:
    """For Tracer: penalise recall used at high health (too early)."""
    b = _bench(hero)
    recalls = [
        e for e in events
        if e.type == EventType.ABILITY_USED
        and e.payload.get("ability") in ("movement", "recall")
        and e.payload.get("health_at_use") is not None
    ]
    if not recalls:
        return 60
    early = sum(
        1 for e in recalls
        if e.payload["health_at_use"] > b["recall_health_ideal"] + 0.25
    )
    ratio = early / len(recalls)
    return max(0, round(100 - ratio * 60))


def compute_skill_scores(
    states: list[FrameState], events: list[GameEvent], hero: str | None
) -> SkillScores:
    deaths = [e for e in events if e.type == EventType.DEATH]
    return SkillScores(
        positioning=positioning_score(states, deaths),
        accuracy=_accuracy_estimate(states, hero),
        ult_management=ult_efficiency(events, hero),
        ability_usage=ability_usage_score(events, hero),
        team_coordination=_coordination_estimate(states),
        rotation_timing=_rotation_estimate(states),
        resource_management=_resource_estimate(states, events),
    )


def _accuracy_estimate(states: list[FrameState], hero: str | None) -> int:
    # Real accuracy comes from the post-match scoreboard OCR; placeholder uses
    # benchmark-relative until that pass runs. Kept explicit so it's swappable.
    return 50


def _coordination_estimate(states: list[FrameState]) -> int:
    near = [s.nearest_ally_m for s in states if s.nearest_ally_m is not None]
    if not near:
        return 60
    grouped = sum(1 for d in near if d < 15) / len(near)
    return round(grouped * 100)


def _rotation_estimate(states: list[FrameState]) -> int:
    return 55  # derived from objective-event timing once map logic is added


def _resource_estimate(states: list[FrameState], events: list[GameEvent]) -> int:
    low_blink = sum(
        1 for s in states
        if s.cooldowns and s.cooldowns.get("movement", 0) > 0
        and (s.nearest_enemy_m or 99) < 10
    )
    penalty = min(40, low_blink)
    return max(0, 80 - penalty)


def session_summary_stats(events: list[GameEvent]) -> dict:
    deaths = [e for e in events if e.type == EventType.DEATH]
    kills = [e for e in events if e.type == EventType.KILL]
    return {
        "deaths": len(deaths),
        "kills": len(kills),
        "kd": round(len(kills) / max(len(deaths), 1), 2),
        "ult_uses": len([e for e in events if e.type == EventType.ULT_USED]),
        "overextensions": len([
            e for e in events if e.payload.get("flag") == "overextension"
        ]),
    }
