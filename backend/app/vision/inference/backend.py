"""
CoachAI — Vision inference.

Defines a single VisionBackend interface with two implementations:

  SelfHostedBackend  — your fine-tuned GameStateNet on a local GPU. This is
                       the target architecture you chose: cheap per-frame,
                       runs at 5fps locally, no per-call API cost.

  ApiBackend         — sends sampled frames to a vision LLM. Slower and costs
                       per frame, but needs zero training data. Use it from
                       day one while you collect the labelled frames required
                       to train the self-hosted model, then flip
                       settings.vision_backend to "self_hosted".

The rest of the system only ever sees `VisionBackend.read_frame()` returning
a FrameState, so swapping backends is a one-line config change.
"""
from __future__ import annotations

import base64
import io
from abc import ABC, abstractmethod

from PIL import Image

from app.core.config import settings
from app.models.schemas import FrameState
from app.vision.labels import ABILITY_SLOTS, HEROES, MAPS, UNKNOWN_HERO, UNKNOWN_MAP


class VisionBackend(ABC):
    @abstractmethod
    async def read_frame(self, image: Image.Image, t: float) -> FrameState: ...

    async def close(self) -> None:  # optional cleanup
        pass


# ─────────────────────── Self-hosted (your GPU) ───────────────────────
class SelfHostedBackend(VisionBackend):
    def __init__(self, model_path: str | None = None):
        import torch
        from torchvision import transforms

        from app.vision.model import GameStateNet

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        path = model_path or settings.vision_model_path
        ckpt = torch.load(path, map_location=self.device)
        self.model = GameStateNet(pretrained=False).to(self.device).eval()
        self.model.load_state_dict(ckpt["model"])
        self.tf = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

    async def read_frame(self, image: Image.Image, t: float) -> FrameState:
        torch = self.torch
        x = self.tf(image.convert("RGB")).unsqueeze(0).to(self.device)
        with torch.no_grad():
            out = self.model(x)

        hero_logits = out["hero"][0]
        hero_idx = int(hero_logits.argmax())
        hero_conf = float(torch.softmax(hero_logits, 0)[hero_idx])
        hero = HEROES[hero_idx] if hero_idx < UNKNOWN_HERO else None

        map_idx = int(out["map"][0].argmax())
        map_name = MAPS[map_idx] if map_idx < UNKNOWN_MAP else None

        cds = out["cooldowns"][0].cpu().tolist()
        cooldowns = {
            ABILITY_SLOTS[i]: round(c * 10)  # 0..1 → approx seconds (scaled)
            for i, c in enumerate(cds) if c > 0.05
        }
        mx, my = out["minimap"][0].cpu().tolist()

        return FrameState(
            t=t, hero=hero,
            health_pct=float(out["health"][0]),
            ult_pct=float(out["ult"][0]),
            pos_x=mx, pos_y=my,
            cooldowns=cooldowns,
            map_name=map_name,
            confidence=hero_conf,
        )


# ─────────────────────── API fallback (no training data) ───────────────────────
class ApiBackend(VisionBackend):
    """Uses a vision LLM. One structured-JSON call per sampled frame."""

    _PROMPT = (
        "You are a vision system reading Overwatch 2 game state from a single "
        "gameplay frame. Return ONLY compact JSON with keys: hero (string|null), "
        "map (string|null), health (0..1), ult (0..1), nearest_ally_m (number|null), "
        "nearest_enemy_m (number|null). Read health from the bottom-left health bar "
        "and ult percentage from the ultimate indicator. No prose."
    )

    def __init__(self):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def read_frame(self, image: Image.Image, t: float) -> FrameState:
        import json

        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=70)
        b64 = base64.b64encode(buf.getvalue()).decode()

        msg = await self.client.messages.create(
            model=settings.llm_model,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": self._PROMPT},
                ],
            }],
        )
        raw = "".join(b.text for b in msg.content if b.type == "text")
        try:
            data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        except json.JSONDecodeError:
            data = {}
        return FrameState(
            t=t,
            hero=data.get("hero"),
            map_name=data.get("map"),
            health_pct=data.get("health"),
            ult_pct=data.get("ult"),
            nearest_ally_m=data.get("nearest_ally_m"),
            nearest_enemy_m=data.get("nearest_enemy_m"),
            confidence=0.8,
        )


def get_vision_backend() -> VisionBackend:
    """Factory honouring settings.vision_backend."""
    if settings.vision_backend == "self_hosted":
        return SelfHostedBackend()
    return ApiBackend()
