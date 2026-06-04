# Deployment Guide

## Topology

Three deployable units:

1. **API** (`backend`, CPU) — stateless FastAPI behind a load balancer. Scale
   horizontally. Handles auth, uploads (presigned), report reads, chat, billing
   webhooks, and the live-coach WebSocket.
2. **Worker** (`backend`, GPU) — Celery worker running the analysis pipeline.
   This is where vision inference + FFmpeg run. GPU host, `--concurrency=1` per
   GPU. Scale by adding GPU workers; Redis distributes jobs.
3. **Capture app** — distributed to users (code-signed installers via
   `electron-builder`). Not hosted by you.

Managed dependencies: **Postgres** (RDS/Supabase/Neon), **Redis**
(ElastiCache/Upstash), **object storage** (S3/R2).

## Steps

### 1. Provision
- Postgres 16, Redis 7, an S3/R2 bucket (`coachai-clips`).
- One CPU box/containers for the API, one GPU box for the worker.

### 2. Configure
Fill `backend/.env` from `.env.example`. In prod set `ENV=prod`, a strong
`SECRET_KEY`, and `DEBUG=false` (via env). Lock CORS in `main.py` to your domain.

### 3. Migrate
Dev auto-creates tables on startup. **In prod use Alembic**, don't rely on
`init_db()`:
```bash
alembic revision --autogenerate -m "init"
alembic upgrade head
```

### 4. Deploy API
```bash
docker build -t coachai-api ./backend
# run with your orchestrator; expose 8000 behind TLS
```
Point `api.coachai.gg` at it. WebSockets must be allowed through the LB.

### 5. Deploy GPU worker
Use a CUDA base image (not the slim CPU Dockerfile). Install the CUDA build of
torch, mount the trained model, set `VISION_BACKEND=self_hosted`, then:
```bash
celery -A app.workers.tasks worker --loglevel=info --concurrency=1
```

### 6. Stripe
- Create a £10/mo recurring Price; put its id in `STRIPE_PRICE_ID_PRO`.
- Add a webhook endpoint → `https://api.coachai.gg/api/v1/billing/webhook`,
  subscribe to `customer.subscription.*`. Put the signing secret in
  `STRIPE_WEBHOOK_SECRET`. The webhook is the source of truth for plan state.

### 7. Capture app distribution
```bash
cd capture-app && npm run build   # builds signed installers per-OS
```
Host the installers; code-sign (Win: EV cert, Mac: notarisation) or users hit
SmartScreen/Gatekeeper warnings.

## Cost control levers
- `VISION_SAMPLE_FPS` — lower = cheaper analysis, coarser detection.
- Clip cap in `pipeline.run_pipeline` (`[:14]`) — bounds FFmpeg + storage.
- Video report render is the most expensive step; gate it behind Pro and
  consider rendering lazily (on first view) rather than for every session.

## Security notes
- API keys live only on the server; the capture app never sees them. It only
  ever holds the user's JWT.
- VOD uploads go **direct to storage** via presigned PUT — large video bytes
  never transit your API.
- Clip playback uses short-lived presigned GET URLs.
- Rate-limit `auth/*` and the live socket; validate VOD size against
  `MAX_VOD_SIZE_GB` before issuing an upload URL in production.
