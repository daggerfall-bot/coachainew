"""
CoachAI — Domain schemas (Pydantic).

These are the in-memory data shapes that flow between the vision layer,
the analysis engine, and the API. They are deliberately game-agnostic at
the top level (GameEvent, FrameState) with Overwatch-specific detail held
in typed payloads, so adding Rainbow Six / CS2 later means adding new
event subtypes, not rewriting the pipeline.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ─────────────────────────── Enums ───────────────────────────
class Game(str, Enum):
    OVERWATCH2 = "overwatch2"
    # future: RAINBOW_SIX = "r6s"; CS2 = "cs2"; LEAGUE = "lol"


class Role(str, Enum):
    TANK = "tank"
    DAMAGE = "damage"
    SUPPORT = "support"


class EventType(str, Enum):
    DEATH = "death"
    KILL = "kill"
    ABILITY_USED = "ability_used"
    ULT_CHARGED = "ult_charged"
    ULT_USED = "ult_used"
    OBJECTIVE = "objective"
    LOW_HEALTH = "low_health"
    POSITION_SAMPLE = "position_sample"


class Severity(str, Enum):
    GOOD = "good"        # a play worth reinforcing
    INFO = "info"        # neutral observation
    IMPROVE = "improve"  # suboptimal, fixable
    CRITICAL = "critical"  # repeated/costly mistake


# ─────────────────────────── Per-frame state ───────────────────────────
class FrameState(BaseModel):
    """Game state extracted from a single sampled frame by the vision model."""
    t: float = Field(..., description="Seconds from session start")
    hero: Optional[str] = None
    health_pct: Optional[float] = Field(None, ge=0, le=1)
    ult_pct: Optional[float] = Field(None, ge=0, le=1)
    # Normalised minimap coords (0..1). None if minimap not parsed this frame.
    pos_x: Optional[float] = Field(None, ge=0, le=1)
    pos_y: Optional[float] = Field(None, ge=0, le=1)
    # Ability cooldowns this frame, e.g. {"blink": 2, "recall": 0}
    cooldowns: dict[str, int] = Field(default_factory=dict)
    # Allies/enemies visible + rough distance bands, parsed from HUD/killfeed.
    nearest_ally_m: Optional[float] = None
    nearest_enemy_m: Optional[float] = None
    map_name: Optional[str] = None
    confidence: float = Field(1.0, ge=0, le=1)


# ─────────────────────────── Events ───────────────────────────
class GameEvent(BaseModel):
    """A discrete, timestamped thing that happened, derived from FrameStates."""
    type: EventType
    t: float
    hero: Optional[str] = None
    map_name: Optional[str] = None
    # Free-form typed detail, e.g. {"ability": "recall", "health_at_use": 0.94}
    payload: dict = Field(default_factory=dict)
    # Link back to the frames that produced this event (for clip extraction).
    frame_start: float
    frame_end: float


# ─────────────────────────── Insights (analysis output) ───────────────────────────
class Insight(BaseModel):
    """A coaching observation produced by the analysis engine."""
    severity: Severity
    title: str
    detail: str
    category: str  # "positioning" | "ability_timing" | "ult" | ...
    # Events that support this insight (used to attach clips).
    evidence_event_indices: list[int] = Field(default_factory=list)
    # Quantified impact where we can compute it.
    metric_label: Optional[str] = None
    metric_value: Optional[str] = None
    estimated_sr_gain: Optional[int] = None


class ClipRef(BaseModel):
    id: str
    title: str
    map_name: str
    hero: str
    t_start: float
    t_end: float
    severity: Severity
    category: str
    s3_key: Optional[str] = None  # populated once FFmpeg has cut + uploaded it
    ai_note: Optional[str] = None


class SkillScores(BaseModel):
    positioning: int = 0
    accuracy: int = 0
    ult_management: int = 0
    ability_usage: int = 0
    team_coordination: int = 0
    rotation_timing: int = 0
    resource_management: int = 0

    @property
    def composite(self) -> int:
        vals = [
            self.positioning, self.accuracy, self.ult_management,
            self.ability_usage, self.team_coordination,
            self.rotation_timing, self.resource_management,
        ]
        return round(sum(vals) / len(vals))


class CoachingReport(BaseModel):
    session_id: str
    game: Game
    hero: str
    maps: list[str]
    duration_sec: float
    generated_at: datetime
    composite_score: int
    skill_scores: SkillScores
    insights: list[Insight]
    clips: list[ClipRef]
    summary_markdown: str
    recommendations: list[str]
    ai_confidence: float
