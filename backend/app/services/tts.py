"""
CoachAI — Text-to-speech for voiceover narration.

Thin wrapper so the TTS provider is swappable. Default targets ElevenLabs
(natural coaching voice); a stub local path is provided for dev without keys.
"""
from __future__ import annotations

import os

import httpx

ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


async def synth_voiceover(text: str, out_path: str, voice_id: str = "Rachel") -> str:
    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    if not api_key:
        # Dev fallback: silent track of roughly the right length so the
        # FFmpeg mux step still works without a TTS provider configured.
        import subprocess
        secs = max(2.0, len(text) / 14)
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i",
             f"anullsrc=r=44100:cl=stereo:d={secs:.1f}", out_path, "-y"],
            check=True, capture_output=True,
        )
        return out_path

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            ELEVEN_URL.format(voice_id=voice_id),
            headers={"xi-api-key": api_key},
            json={"text": text, "model_id": "eleven_turbo_v2",
                  "voice_settings": {"stability": 0.5, "similarity_boost": 0.7}},
        )
        r.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(r.content)
    return out_path
