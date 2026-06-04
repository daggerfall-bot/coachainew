"""
CoachAI — Core configuration.

All settings load from environment variables (see .env.example).
Pydantic validates types at startup so a misconfigured deploy fails fast
instead of breaking at request time.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore",
        populate_by_name=True,
    )

    # ── App ──
    app_name: str = "CoachAI"
    env: Literal["dev", "staging", "prod"] = "dev"
    debug: bool = True
    api_prefix: str = "/api/v1"
    secret_key: str = Field(
        default="local-dev-insecure-key-change-in-cloud-deploy",
        description="JWT signing key. MUST be overridden in cloud/prod via env.",
    )
    access_token_ttl_min: int = 60 * 24  # 24h

    # ── Local mode (bundled desktop server) ──
    # When set by the desktop app, the backend runs single-user on the player's
    # machine: SQLite, local-disk storage, no Stripe. See app/standalone.py.
    local_mode: bool = Field(default=False, alias="COACHAI_LOCAL_MODE")
    local_data_dir: str = "./coachai_data"  # VODs, clips, reports on disk

    # ── Discord OAuth (desktop one-click sign-in) ──
    discord_client_id: str = ""
    discord_client_secret: str = ""
    # The desktop app registers this scheme; backend 302s the token here.
    discord_redirect_deeplink: str = "coachai://auth"
    # Backend's own callback URL Discord redirects to (loopback in local mode).
    discord_callback_url: str = "http://127.0.0.1:8745/api/v1/auth/discord/callback"

    # ── Database ──
    database_url: str = "postgresql+asyncpg://coachai:coachai@localhost:5432/coachai"
    db_pool_size: int = 20
    db_max_overflow: int = 10

    # ── Redis (queue + cache) ──
    redis_url: str = "redis://localhost:6379/0"

    # ── Object storage (clips, VODs) ──
    s3_endpoint: str = "https://s3.amazonaws.com"
    s3_bucket: str = "coachai-clips"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "eu-west-2"

    # ── Vision layer ──
    # 'self_hosted' = your fine-tuned model on GPU; 'api' = vision LLM fallback.
    vision_backend: Literal["self_hosted", "api"] = "api"
    vision_model_path: str = "models/ow2_state_detector.pt"
    vision_inference_url: str = "http://localhost:8001/infer"  # triton/torchserve
    vision_sample_fps: float = 5.0  # frames/sec sampled for analysis
    vision_confidence_threshold: float = 0.55

    # ── LLM (coaching brain) ──
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-20250514"
    llm_max_tokens: int = 1500

    # ── Video processing ──
    ffmpeg_path: str = "/usr/bin/ffmpeg"
    ffprobe_path: str = "/usr/bin/ffprobe"
    clip_padding_sec: float = 4.0  # seconds before/after a flagged event

    # ── Billing ──
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id_pro: str = ""  # £10/mo price object
    pro_price_gbp: int = 10

    # ── Limits ──
    free_sessions_per_month: int = 3
    max_vod_size_gb: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Convenience methods bound after class def to keep the model clean.
def _local_port(self) -> int:
    import os
    return int(os.environ.get("COACHAI_PORT", "8745"))


Settings.local_port = _local_port  # type: ignore[attr-defined]


settings = get_settings()
