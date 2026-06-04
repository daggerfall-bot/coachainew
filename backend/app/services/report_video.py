"""
CoachAI — Annotated video report generator (build priority #3).

Produces the shareable MP4 coaching report: an intro card, each flagged clip
with a burned-in coaching caption, optional positional arrow overlays, and a
TTS voiceover track narrating the lesson for each clip.

Pipeline per clip:
  1. cut clip (services.clips.cut_clip) with caption
  2. synth voiceover from the insight detail (TTS)
  3. mux voiceover over the clip audio (ducked)
Then concat all clips + intro/outro cards into one MP4.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import settings
from app.models.schemas import ClipRef, CoachingReport
from app.services.storage import download_file, upload_file
from app.services.tts import synth_voiceover


async def _run(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode()[-500:]}")


async def _title_card(text: str, out: str, seconds: float = 3.0) -> str:
    safe = text.replace(":", r"\:").replace("'", "")
    await _run([
        settings.ffmpeg_path, "-f", "lavfi",
        "-i", f"color=c=0x0D1117:s=1920x1080:d={seconds}",
        "-vf",
        f"drawtext=text='{safe}':x=(w-text_w)/2:y=(h-text_h)/2:"
        f"fontsize=64:fontcolor=0xF99E1A",
        "-c:v", "libx264", "-preset", "veryfast", "-t", f"{seconds}",
        "-pix_fmt", "yuv420p", out, "-y",
    ])
    return out


async def _voiceover_clip(clip_local: str, narration: str, out: str) -> str:
    """Synthesise narration and mix it over the clip (ducking original audio)."""
    vo_path = clip_local.replace(".mp4", "_vo.mp3")
    await synth_voiceover(narration, vo_path)
    await _run([
        settings.ffmpeg_path, "-i", clip_local, "-i", vo_path,
        "-filter_complex",
        "[0:a]volume=0.25[bg];[bg][1:a]amix=inputs=2:duration=longest[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", out, "-y",
    ])
    return out


async def build_video_report(report: CoachingReport, work_dir: str) -> str:
    """Returns the S3 key of the finished MP4 report."""
    wd = Path(work_dir)
    wd.mkdir(parents=True, exist_ok=True)
    segments: list[str] = []

    intro = await _title_card(
        f"{report.hero} Coaching Report  -  Score {report.composite_score}",
        str(wd / "intro.mp4"),
    )
    segments.append(intro)

    # Narrate the top insights over their evidence clips.
    insight_by_clip = _map_insights_to_clips(report)
    for i, clip in enumerate(report.clips):
        if not clip.s3_key:
            continue
        local = str(wd / f"src_{i:03d}.mp4")
        await download_file(clip.s3_key, local)
        narration = insight_by_clip.get(clip.id) or clip.title
        narrated = await _voiceover_clip(local, narration, str(wd / f"seg_{i:03d}.mp4"))
        segments.append(narrated)

    outro = await _title_card("Keep grinding. - CoachAI", str(wd / "outro.mp4"))
    segments.append(outro)

    # Concat (re-encode for safety since sources may differ).
    concat_file = wd / "concat.txt"
    concat_file.write_text("".join(f"file '{Path(s).resolve()}'\n" for s in segments))
    final_local = str(wd / "report.mp4")
    await _run([
        settings.ffmpeg_path, "-f", "concat", "-safe", "0",
        "-i", str(concat_file), "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "21", "-c:a", "aac", final_local, "-y",
    ])

    key = f"reports/{report.session_id}/report.mp4"
    await upload_file(final_local, key)
    return key


def _map_insights_to_clips(report: CoachingReport) -> dict[str, str]:
    """Best-effort: attach an insight's narration to clips of the same category."""
    out: dict[str, str] = {}
    for clip in report.clips:
        match = next(
            (ins for ins in report.insights if ins.category == clip.category), None
        )
        if match:
            out[clip.id] = f"{match.title}. {match.detail}"
    return out
