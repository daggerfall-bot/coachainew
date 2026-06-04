"""
CoachAI — Clip service (FFmpeg).

Cuts short clips around flagged events, optionally burns in annotations
(arrows/labels), and uploads to object storage. This is ranked #3 in the build
(video reports) but the cutting half is needed by the pipeline immediately to
populate the clip library, so it lives here from the start.

Annotation note: true positional arrows ("your support was here") require the
minimap coords from the vision model projected onto the frame. The drawbox/
drawtext filters below are the mechanism; the coordinates come from the event
payload. A full annotated video report (stitched, with voiceover) is built in
report_video.py.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import settings
from app.models.schemas import GameEvent
from app.services.storage import upload_file


async def _run(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode()[-500:]}")


async def cut_clip(
    vod_path: str, t_start: float, t_end: float, out_path: str,
    label: str | None = None,
) -> str:
    """Cut [t_start, t_end] (+ padding) from the VOD. Optionally burn a label."""
    pad = settings.clip_padding_sec
    start = max(0.0, t_start - pad)
    dur = (t_end + pad) - start

    vf = []
    if label:
        safe = label.replace(":", r"\:").replace("'", "")
        vf.append(
            f"drawtext=text='{safe}':x=20:y=20:fontsize=28:fontcolor=white:"
            f"box=1:boxcolor=black@0.5:boxborderw=8"
        )
    cmd = [
        settings.ffmpeg_path, "-ss", f"{start:.2f}", "-i", vod_path,
        "-t", f"{dur:.2f}",
    ]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", out_path, "-y"]
    await _run(cmd)
    return out_path


async def cut_clips_for_events(
    session_id: str, vod_path: str, events: list[GameEvent]
) -> list[str | None]:
    """Cut + upload a clip per event. Returns S3 keys (None on failure)."""
    out_dir = Path(vod_path).with_suffix("") / "clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    keys: list[str | None] = []

    sem = asyncio.Semaphore(3)  # FFmpeg is CPU-heavy; cap parallelism

    async def one(idx: int, e: GameEvent) -> str | None:
        async with sem:
            local = str(out_dir / f"clip_{idx:03d}.mp4")
            try:
                await cut_clip(vod_path, e.frame_start, e.frame_end, local)
                key = f"clips/{session_id}/clip_{idx:03d}.mp4"
                await upload_file(local, key)
                return key
            except Exception:
                return None

    keys = await asyncio.gather(*(one(i, e) for i, e in enumerate(events)))
    return list(keys)
