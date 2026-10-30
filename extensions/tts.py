from __future__ import annotations
import asyncio
from pathlib import Path
import shutil
import subprocess
from .media import duration, run_process, check_cancel


VOICES = {"Gadis — Indonesia": "id-ID-GadisNeural", "Ardi — Indonesia": "id-ID-ArdiNeural"}


def synthesize(lines: list[str], folder: Path, voice="id-ID-GadisNeural", rate="+0%", fallback=False, cancel=None) -> list[dict]:
    """One audio file per subtitle line gives subtitles aligned to actual TTS durations."""
    import edge_tts
    folder.mkdir(parents=True, exist_ok=True)
    segments = []
    async def make(text, target):
        await asyncio.wait_for(edge_tts.Communicate(text, voice=voice, rate=rate).save(str(target)), timeout=90)
    for i, line in enumerate(lines):
        check_cancel(cancel)
        target = folder / f"voice-{i:02d}.mp3"
        try:
            asyncio.run(make(line, target))
            if not target.exists() or not target.stat().st_size:
                raise RuntimeError("TTS kosong")
        except Exception as exc:
            target.unlink(missing_ok=True)
            if not fallback:
                raise RuntimeError("Edge TTS gagal. Coba lagi atau aktifkan fallback espeak-ng (kualitas robot, bukan suara neural).") from exc
            exe = shutil.which("espeak-ng")
            if not exe:
                raise RuntimeError("Fallback memerlukan paket espeak-ng.")
            target = folder / f"voice-{i:02d}.wav"
            run_process([exe, "-v", "id", "-s", "155", "-w", str(target), line], timeout=60, cancel=cancel)
        d = duration(target)
        if d <= 0:
            raise RuntimeError("Durasi audio TTS tidak valid.")
        segments.append({"text": line, "path": str(target), "duration": d})
    return segments