"""
CoachAI — Live commentary (WebSocket).

The desktop capture app streams JPEG frames (base64) at ~5fps over this socket.
For each frame the server reads game state via the vision backend, maintains a
short rolling window, and when a coaching-worthy moment is detected emits a
concise spoken-style tip back down the socket. The client speaks it via TTS.

Design choices for latency:
  - We do NOT call the LLM on every frame (too slow/expensive). The fast
    deterministic detectors (events.py) fire most live tips instantly.
  - The LLM is only consulted for occasional "summary" coaching at fight end,
    debounced, so the live loop stays sub-second.
"""
from __future__ import annotations

import base64
import io
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from PIL import Image

from app.analysis.events import detect_overextensions
from app.models.schemas import FrameState
from app.vision.inference.backend import get_vision_backend

router = APIRouter()


class LiveCoachSession:
    """Per-connection rolling state + tip throttling."""

    def __init__(self):
        self.window: list[FrameState] = []
        self.last_tip_t = 0.0
        self.min_tip_gap = 4.0  # seconds between spoken tips (avoid spam)

    def add(self, s: FrameState):
        self.window.append(s)
        # keep ~15s of context at 5fps
        if len(self.window) > 75:
            self.window.pop(0)

    def maybe_tip(self, now: float) -> dict | None:
        if now - self.last_tip_t < self.min_tip_gap:
            return None
        cur = self.window[-1] if self.window else None
        if not cur:
            return None

        # Overextension: far from allies + close to enemy → immediate warning.
        oe = detect_overextensions(self.window[-5:])
        if oe:
            self.last_tip_t = now
            return {
                "severity": "critical",
                "text": "No support nearby — fall back before you commit.",
                "cue": "positioning",
            }

        # Early recall heuristic (Tracer): movement used at high health.
        if (cur.hero == "Tracer" and cur.health_pct and cur.health_pct > 0.85
                and cur.cooldowns.get("movement", 0) > 0):
            self.last_tip_t = now
            return {
                "severity": "improve",
                "text": "Recalling too early — you still had over 85% health.",
                "cue": "ability_timing",
            }

        # Ult ready reminder.
        if cur.ult_pct and cur.ult_pct >= 1.0:
            self.last_tip_t = now
            return {
                "severity": "info",
                "text": "Ult is up — look for a grouped target.",
                "cue": "ult",
            }
        return None


@router.websocket("/live/coach")
async def live_coach(ws: WebSocket):
    # Browsers can't set Authorization headers on WebSocket connections, so the
    # frontend passes the JWT as a ?token= query param (see frontend live.ts).
    # Authenticate before accepting; close with policy-violation code if invalid.
    from app.core.security import decode_token

    token = ws.query_params.get("token", "")
    if not decode_token(token):
        await ws.close(code=1008)  # policy violation
        return

    await ws.accept()
    backend = get_vision_backend()
    sess = LiveCoachSession()
    t0 = time.monotonic()
    try:
        while True:
            msg = await ws.receive_json()
            # client sends {"frame": "<base64 jpeg>"}
            b64 = msg.get("frame")
            if not b64:
                continue
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
            now = time.monotonic() - t0
            state = await backend.read_frame(img, now)
            sess.add(state)

            # Always send the lightweight live stats for the HUD.
            await ws.send_json({
                "type": "state",
                "t": round(now, 1),
                "health": state.health_pct,
                "ult": state.ult_pct,
                "hero": state.hero,
            })

            tip = sess.maybe_tip(now)
            if tip:
                await ws.send_json({"type": "tip", **tip})
    except WebSocketDisconnect:
        pass
    finally:
        await backend.close()
