"""FFmpeg adapters: argument arrays (never shell), bounded logs, real cancellation."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
from .config import VIDEO_EXT, AUDIO_EXT, IMAGE_EXT
from .security import redact


class Cancelled(Exception):
    pass


def check_cancel(cancel) -> None:
    if cancel and cancel():
        raise Cancelled("Dibatalkan pengguna.")


def run_process(args: list[str], *, timeout=1800, cancel=None, progress=None, duration=0,
                log=None, cwd=None, env=None) -> str:
    """Run a media/network CLI; terminate its whole process group on cancel."""
    check_cancel(cancel)
    popen_env = os.environ.copy()
    if env:
        popen_env.update(env)
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace", cwd=cwd, env=popen_env,
                            start_new_session=True)
    lines: list[str] = []
    last = 0.0

    def read():
        for line in proc.stdout:
            clean = redact(line.rstrip())
            lines.append(clean)
            del lines[:-500]
            if log and any(x in clean.lower() for x in ("error", "warning", "deprecated", "download", "fragment")):
                log(clean[:1200])
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    start = time.monotonic()
    try:
        while proc.poll() is None:
            check_cancel(cancel)
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"Proses melewati batas {timeout} detik.")
            if progress and duration and time.monotonic() - last > .5:
                text = "\n".join(lines[-40:])
                matches = re.findall(r"out_time_us=(\d+)", text)
                if matches:
                    progress(min(.98, int(matches[-1]) / max(1, duration * 1e6)))
                last = time.monotonic()
            time.sleep(.15)
        reader.join(timeout=3)
        check_cancel(cancel)
        if proc.returncode:
            raise RuntimeError(f"Perintah media gagal ({proc.returncode}): " + "\n".join(lines[-16:]))
        return "\n".join(lines)
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=4)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if proc.stdout:
            proc.stdout.close()


def ffmpeg(args: list[str], **kwargs) -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("FFmpeg belum terpasang. Periksa packages.txt / instal ffmpeg.")
    return run_process([exe, "-hide_banner", "-nostdin", "-y", *args], **kwargs)


def probe(path: str | Path) -> dict:
    exe = shutil.which("ffprobe")
    if not exe:
        p = Path(path)
        if p.suffix.lower() in IMAGE_EXT or not p.suffix:
            from PIL import Image
            with Image.open(p) as im:
                return {"streams": [{"codec_type": "image", "width": im.width, "height": im.height}], "format": {}}
        raise RuntimeError("ffprobe belum terpasang.")
    r = subprocess.run([exe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=45)
    if r.returncode:
        raise RuntimeError("ffprobe: berkas rusak / format tidak dikenali.")
    return json.loads(r.stdout)


def duration(path: str | Path) -> float:
    info = probe(path)
    return float(info.get("format", {}).get("duration") or next((s.get("duration", 0) for s in info["streams"] if s.get("duration")), 0) or 0)


def has_audio(path: str | Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path)["streams"])


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def video_filter(width=1080, height=1920, fps=30, crop=True) -> str:
    if crop:
        return (f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p")
    return (f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x101820,setsar=1,fps={fps},format=yuv420p")


def output_args(fps=30, crf=21) -> list[str]:
    return ["-c:v", "libx264", "-preset", "veryfast", "-threads", "2", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "160k",
            "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]


def loudnorm_measure(path: str | Path, target=-16, cancel=None) -> dict:
    text = ffmpeg(["-i", str(path), "-vn", "-af",
                   f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                  timeout=1800, cancel=cancel)
    matches = re.findall(r'\{\s*"input_i".*?\}', text, re.S)
    if not matches:
        raise RuntimeError("Pengukuran loudness gagal; pastikan berkas memiliki audio.")
    return json.loads(matches[-1])


def normalize_audio(path: str | Path, output: str | Path, target=-16, cancel=None, progress=None):
    m = loudnorm_measure(path, target, cancel)
    af = (f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={m['input_i']}:"
          f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
          f"offset={m['target_offset']}:linear=true:print_format=summary,aresample=48000")
    ffmpeg(["-i", str(path), "-vn", "-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-ac", "2", "-movflags", "+faststart", str(output)], cancel=cancel, progress=progress,
           duration=duration(path), timeout=1800)


def normalize_video(path, output, width=1280, height=720, target=-16, cancel=None, progress=None):
    d = duration(path)
    m = loudnorm_measure(path, target, cancel) if has_audio(path) else None
    args = ["-i", str(path), "-map", "0:v:0", "-map", "0:a:0?", "-vf", video_filter(width, height, 30, False)]
    if m:
        args += ["-af", f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true"]
    args += output_args(crf=21) + [str(output)]
    ffmpeg(args, cancel=cancel, progress=progress, duration=d, timeout=3600)


def pcm_bytes(path, seconds=None, cancel=None) -> bytes:
    args = ["-i", str(path)]
    if seconds:
        args += ["-t", str(seconds)]
    args += ["-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"]
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("FFmpeg tidak tersedia")
    p = subprocess.Popen([exe, "-v", "error", "-nostdin", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    chunks = []
    try:
        while p.poll() is None:
            check_cancel(cancel)
            chunks.append(p.stdout.read(32000))
        chunks.append(p.stdout.read())
        if p.returncode:
            raise RuntimeError(redact(p.stderr.read().decode(errors="replace")))
        return b"".join(chunks)
    finally:
        if p.poll() is None:
            p.kill()
        p.wait(timeout=5)
        p.stdout.close()
        p.stderr.close()


def analyze_audio(paths: list[str], output_dir: Path, cancel=None) -> dict:
    """Actual PCM/spectral descriptors; NOT a claimed music recognition service."""
    import numpy as np
    from PIL import Image, ImageDraw
    output_dir.mkdir(parents=True, exist_ok=True)
    tracks = []
    for idx, path in enumerate(paths[:4]):
        check_cancel(cancel)
        raw = pcm_bytes(path, 30, cancel)
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
        if len(x) < 1024:
            continue
        x = x[:min(len(x), 16000 * 20)]
        hop, nfft = 512, 1024
        frames = np.lib.stride_tricks.sliding_window_view(x, nfft)[::hop]
        spec = np.abs(np.fft.rfft(frames * np.hanning(nfft), axis=1)).T
        power = spec ** 2
        freqs = np.fft.rfftfreq(nfft, 1 / 16000)
        total = np.sum(power, axis=0) + 1e-10
        centroid = float(np.mean((power * freqs[:, None]).sum(axis=0) / total))
        rolloff = float(np.mean(freqs[np.argmax(np.cumsum(power, axis=0) >= .85 * total, axis=0)]))
        flux = float(np.mean(np.maximum(0, np.diff(spec, axis=1))))
        rms = float(np.sqrt(np.mean(x*x)))
        zcr = float(np.mean(np.abs(np.diff(np.sign(x))) > 0))
        # Onset-envelope autocorrelation gives a TEMPO ESTIMATE, not an exact BPM.
        envelope = np.maximum(0, np.diff(total))
        envelope -= envelope.mean()
        ac = np.correlate(envelope, envelope, mode="full")[len(envelope)-1:]
        lo, hi = int(60 / 180 * 16000 / hop), min(len(ac)-1, int(60 / 65 * 16000 / hop))
        bpm = round(60 * 16000 / hop / (lo + int(np.argmax(ac[lo:hi+1]))), 1) if hi > lo else None
        image = 20 * np.log10(spec[::-1] + 1e-5)
        image = np.clip((image + 70) / 70 * 255, 0, 255).astype(np.uint8)
        rgba = np.zeros((*image.shape, 3), dtype=np.uint8)
        rgba[:, :, 0] = image
        rgba[:, :, 1] = (image * .65).astype(np.uint8)
        rgba[:, :, 2] = (200 - image // 2).astype(np.uint8)
        thumb = Image.fromarray(rgba).resize((900, 256))
        panel = Image.new("RGB", (900, 300), "#101820")
        panel.paste(thumb, (0, 30))
        ImageDraw.Draw(panel).text((15, 8), f"PCM 16 kHz | 0-8 kHz | 20 s | {Path(path).name[:75]}", fill="white")
        image_path = output_dir / f"spectrogram-{idx}.png"
        panel.save(image_path)
        tracks.append({"filename": Path(path).name, "rms_dbfs": round(20*math.log10(max(rms, 1e-8)), 2),
                       "zero_crossing_rate": round(zcr, 4), "spectral_centroid_hz": round(centroid),
                       "rolloff_85_hz": round(rolloff), "spectral_flux": round(flux, 5),
                       "tempo_estimate_bpm": bpm, "spectrogram": str(image_path),
                       "sample_seconds": round(len(x)/16000, 2)})
    if not tracks:
        raise ValueError("Tidak ditemukan audio untuk dianalisis.")
    return {"method": "ffprobe + PCM 16kHz + STFT 1024/hop512; heuristic, no song identification",
            "tracks": tracks, "generated_at": time.time()}