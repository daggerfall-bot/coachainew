"""
CoachAI — FastAPI application entrypoint.

    uvicorn app.main:app --reload          # dev
    gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4   # prod
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import live, reports, sessions
from app.core.config import settings
from app.db.session import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()  # dev convenience; use Alembic migrations in prod
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.coachai.gg", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

p = settings.api_prefix
app.include_router(sessions.router, prefix=p, tags=["sessions"])
app.include_router(reports.router, prefix=p, tags=["reports"])
app.include_router(live.router, prefix=p, tags=["live"])

if settings.local_mode:
    # Desktop build: Discord OAuth + local disk storage, no Stripe.
    from app.api import local
    app.include_router(local.router, prefix=p, tags=["local"])
else:
    # Cloud build: Stripe billing. Imported here (not at module top) so the
    # bundled desktop server boots without the `stripe` package installed.
    from app.api import billing
    app.include_router(billing.router, prefix=p, tags=["billing"])


@app.get("/health")
async def health():
    return {"status": "ok", "vision_backend": settings.vision_backend}
