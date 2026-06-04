"""
CoachAI — Database models (SQLAlchemy 2.0, async).

Tables: users, sessions, clips, reports, subscriptions. Reports/insights are
stored as JSONB (they're read whole and rarely queried by inner field), while
sessions and clips are relational so we can list/filter them efficiently.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, DateTime, Float, ForeignKey, Integer, String, Text, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String, default="Player")
    battle_tag: Mapped[str | None] = mapped_column(String, nullable=True)
    current_rank: Mapped[str | None] = mapped_column(String, nullable=True)
    target_rank: Mapped[str | None] = mapped_column(String, nullable=True)
    plan: Mapped[str] = mapped_column(String, default="free")  # free | pro
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    sessions: Mapped[list["Session"]] = relationship(back_populates="user")


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    game: Mapped[str] = mapped_column(String, default="overwatch2")
    hero: Mapped[str | None] = mapped_column(String, nullable=True)
    vod_key: Mapped[str | None] = mapped_column(String, nullable=True)  # S3 key
    # queued | processing | complete | failed
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    composite_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User"] = relationship(back_populates="sessions")
    clips: Mapped[list["Clip"]] = relationship(back_populates="session")
    report: Mapped["Report | None"] = relationship(back_populates="session", uselist=False)


class Clip(Base):
    __tablename__ = "clips"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    title: Mapped[str] = mapped_column(String)
    map_name: Mapped[str] = mapped_column(String, default="")
    hero: Mapped[str] = mapped_column(String, default="")
    t_start: Mapped[float] = mapped_column(Float)
    t_end: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String, default="info")
    category: Mapped[str] = mapped_column(String, default="general")
    s3_key: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["Session"] = relationship(back_populates="clips")


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)  # serialised CoachingReport
    video_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped["Session"] = relationship(back_populates="report")
