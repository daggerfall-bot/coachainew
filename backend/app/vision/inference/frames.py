"""
CoachAI — Frame sampling + killfeed OCR.

The vision model reads continuous state (health, ult, position). The killfeed
is text, so OCR handles it better than a regression head. Together they give
the analysis engine a per-second picture of the match plus discrete kill/death
events with timestamps.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.core.config import settings
from app.models.schemas import FrameState
from app.vision.inference.backend import VisionBackend


def sample_frames(vod_path: str, fps: float | None = None) -> list[tuple[float, Path]]:
    """
    Use ffmpeg to extract frames at `fps` into a temp dir, returning
    (timestamp_seconds, frame_path) tuples. Sampling at 5fps keeps inference
    cost sane while still catching fast Tracer movements.
    """
    fps = fps or settings.vision_sample_fps
    out_dir = Path(vod_path).with_suffix("") / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "f_%06d.jpg")
    subprocess.run(
        [settings.ffmpeg_path, "-i", vod_path, "-vf", f"fps={fps}",
         "-q:v", "3", pattern, "-y"],
        check=True, capture_output=True,
    )
    frames = sorted(out_dir.glob("f_*.jpg"))
    return [(i / fps, p) for i, p in enumerate(frames)]


async def extract_states(
    vod_path: str, backend: VisionBackend, fps: float | None = None
) -> list[FrameState]:
    """Run the vision backend over all sampled frames, in bounded parallelism."""
    frames = sample_frames(vod_path, fps)
    sem = asyncio.Semaphore(8)  # cap concurrent GPU/API calls

    async def one(t: float, path: Path) -> FrameState:
        async with sem:
            img = Image.open(path)
            return await backend.read_frame(img, t)

    return await asyncio.gather(*(one(t, p) for t, p in frames))


# ───────────────────────── Killfeed OCR ─────────────────────────
@dataclass
class KillfeedEntry:
    t: float
    actor: str          # who got the kill (or "" if unknown)
    victim: str
    is_self_death: bool  # did the tracked player die?
    is_self_kill: bool


_KILL_RE = re.compile(r"(?P<actor>.+?)\s+(?:eliminated|killed)\s+(?P<victim>.+)", re.I)


def read_killfeed(frame_path: Path, self_name: str) -> list[KillfeedEntry]:
    """
    OCR the top-right killfeed region. We crop to that region first (cheaper +
    more accurate than OCR-ing the whole frame). Uses tesseract via pytesseract.

    NOTE: the crop box is resolution-dependent. These ratios target 1920x1080;
    capture.py records at a fixed resolution so the box is stable.
    """
    import pytesseract

    img = Image.open(frame_path)
    w, h = img.size
    killfeed = img.crop((int(w * 0.70), int(h * 0.08), w, int(h * 0.35)))
    text = pytesseract.image_to_string(killfeed)

    entries: list[KillfeedEntry] = []
    for line in text.splitlines():
        m = _KILL_RE.search(line)
        if not m:
            continue
        actor = m.group("actor").strip()
        victim = m.group("victim").strip()
        entries.append(KillfeedEntry(
            t=0.0,  # filled by caller (it knows the frame timestamp)
            actor=actor, victim=victim,
            is_self_death=self_name.lower() in victim.lower(),
            is_self_kill=self_name.lower() in actor.lower(),
        ))
    return entries
