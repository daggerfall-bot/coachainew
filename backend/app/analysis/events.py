"""
CoachAI — Event detection.

Turns the continuous stream of FrameStates into discrete GameEvents (deaths,
ability uses, ult pops, low-health moments, overextensions). This is pure,
deterministic logic — no LLM — so it's fast, testable, and cheap. The LLM only
gets involved later, reasoning over the structured events rather than raw video.

This separation is what makes the system affordable: the expensive model never
touches 47 minutes of footage, only a few dozen structured events.
"""
from __future__ import annotations

from app.models.schemas import EventType, FrameState, GameEvent


def _transitions(states: list[FrameState], key, drop: float):
    """Yield (i, prev, cur) where value[key] drops by >= `drop` between frames."""
    for i in range(1, len(states)):
        a = getattr(states[i - 1], key)
        b = getattr(states[i], key)
        if a is not None and b is not None and (a - b) >= drop:
            yield i, a, b


def detect_events(states: list[FrameState]) -> list[GameEvent]:
    events: list[GameEvent] = []
    if not states:
        return events

    hero = next((s.hero for s in states if s.hero), None)
    map_name = next((s.map_name for s in states if s.map_name), None)

    # ── Deaths: health goes to (near) zero ──
    for i in range(1, len(states)):
        prev, cur = states[i - 1], states[i]
        if prev.health_pct and prev.health_pct > 0.1 and (cur.health_pct or 1) <= 0.05:
            events.append(GameEvent(
                type=EventType.DEATH, t=cur.t, hero=hero, map_name=map_name,
                payload={
                    "health_before": prev.health_pct,
                    "nearest_ally_m": prev.nearest_ally_m,
                    "nearest_enemy_m": prev.nearest_enemy_m,
                    "pos": [prev.pos_x, prev.pos_y],
                },
                frame_start=max(0.0, cur.t - 5), frame_end=cur.t + 2,
            ))

    # ── Ult pops: ult goes from high to ~0 ──
    for i, a, b in _transitions(states, "ult_pct", drop=0.5):
        if b <= 0.1:
            events.append(GameEvent(
                type=EventType.ULT_USED, t=states[i].t, hero=hero, map_name=map_name,
                payload={"ult_before": a},
                frame_start=max(0.0, states[i].t - 3), frame_end=states[i].t + 3,
            ))

    # ── Ult charged: crosses 1.0 ──
    for i in range(1, len(states)):
        if (states[i - 1].ult_pct or 0) < 1.0 <= (states[i].ult_pct or 0):
            events.append(GameEvent(
                type=EventType.ULT_CHARGED, t=states[i].t, hero=hero, map_name=map_name,
                payload={}, frame_start=states[i].t, frame_end=states[i].t,
            ))

    # ── Ability uses: a tracked cooldown jumps from 0 to >0 ──
    for i in range(1, len(states)):
        prev_cd = states[i - 1].cooldowns or {}
        cur_cd = states[i].cooldowns or {}
        for ability, cd in cur_cd.items():
            if cd > 0 and prev_cd.get(ability, 0) == 0:
                events.append(GameEvent(
                    type=EventType.ABILITY_USED, t=states[i].t, hero=hero,
                    map_name=map_name,
                    payload={
                        "ability": ability,
                        "health_at_use": states[i].health_pct,
                    },
                    frame_start=max(0.0, states[i].t - 2), frame_end=states[i].t + 2,
                ))

    events.sort(key=lambda e: e.t)
    return events


def detect_overextensions(states: list[FrameState]) -> list[GameEvent]:
    """
    Pattern: the player is far from the nearest ally AND close to an enemy,
    shortly before a death. This is the 'pushing without support' habit the
    product is designed to catch. Threshold of 15m matches the in-game healing
    range heuristic referenced in the coaching content.
    """
    out: list[GameEvent] = []
    for i, s in enumerate(states):
        if (
            s.nearest_ally_m is not None and s.nearest_ally_m > 15
            and s.nearest_enemy_m is not None and s.nearest_enemy_m < 10
        ):
            out.append(GameEvent(
                type=EventType.POSITION_SAMPLE, t=s.t, hero=s.hero,
                map_name=s.map_name,
                payload={
                    "ally_distance": s.nearest_ally_m,
                    "enemy_distance": s.nearest_enemy_m,
                    "flag": "overextension",
                },
                frame_start=max(0.0, s.t - 4), frame_end=s.t + 4,
            ))
    return out
