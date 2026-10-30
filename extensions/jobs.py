"""Job tambahan memakai JobRunner, Library, dan folder output aplikasi asli."""
from __future__ import annotations
import json
from pathlib import Path
import random
import shutil
import time
import uuid
import services as svc
from . import state, media, render, ai, tts, youtube
from .config import WORK, ANALYSIS


def extract_frames(source, folder, seconds):
    folder.mkdir(parents=True, exist_ok=True)
    result = []
    for i, fraction in enumerate((.15, .45, .75)):
        p = folder / f"frame-{i}.jpg"
        media.ffmpeg(["-ss", f"{seconds*fraction:.3f}", "-i", str(source), "-frames:v", "1", "-vf", "scale=384:-2", str(p)], timeout=60)
        result.append(str(p))
    return result


def _save_output(path: Path, name: str, metadata=None):
    info = media.probe(path)
    v = next((s for s in info["streams"] if s.get("codec_type") == "video"), {})
    if v.get("codec_name") != "h264" or not media.has_audio(path) or media.duration(path) <= 0:
        raise RuntimeError("Verifikasi MP4 gagal: memerlukan H.264, audio AAC, dan durasi valid.")
    dest = svc.unique_path(svc.DIRS["output"], svc.safe_name(name))
    shutil.move(str(path), str(dest))
    if metadata:
        state.kv_set("video-meta:" + str(dest), metadata)
    return dest


def submit_upload(runner, path, account_id, metadata, consent=False):
    if not consent:
        raise ValueError("Persetujuan hak konten dan tujuan upload diperlukan.")
    a = state.asset(path)
    meta = dict(metadata)
    meta.setdefault("hashtags", ["#Shorts"])
    def run(job):
        job["detail"] = "Google resumable upload · potongan 8 MiB"
        result = youtube.upload_video(account_id, a, meta, job["id"],
                                      lambda v: job.update(progress=v, detail=f"Upload Google {v*100:.1f}%"),
                                      lambda: job["cancel_event"].is_set())
        job["result"] = result
        return True, result["url"] + " · " + result.get("privacy", "private")
    return runner.submit("Upload YouTube · " + a["name"], run, files=[a["path"]])


def submit_creative(runner, kind, payload, title=None):
    """Tidak ada kunci Clipdrop di payload. Semua sumber dikunci selama job aktif."""
    p = json.loads(json.dumps(payload, default=str))
    sources = [p[k] for k in ("image", "source", "music") if p.get(k)]
    sources += p.get("music_pool", [])
    for source in sources:
        state.library_path(source)
    if p.get("auto_upload") and (not p.get("consent") or not p.get("account_id")):
        raise ValueError("Auto-upload memerlukan channel dan persetujuan eksplisit.")
    label = {"motion": "Clipdrop → Video", "poem": "Kartu Shorts", "reaction": "Reaction Warga +62"}[kind]
    def run(job):
        folder = WORK / (kind + "-" + job["id"] + "-" + uuid.uuid4().hex[:6])
        folder.mkdir(parents=True, exist_ok=True)
        cancel = lambda: job["cancel_event"].is_set()
        def progress(value):
            job["progress"] = max(0, min(.98, value))
        def stage(text, value):
            media.check_cancel(cancel)
            job["detail"] = text
            progress(value)
        try:
            metadata = p.get("metadata") or {}
            draft = p.get("draft")
            seconds = max(5, min(60, float(p.get("seconds", 15))))
            width = 720 if p.get("resolution") == "720p" else 1080
            height = width * 16 // 9 // 2 * 2
            if kind in ("motion", "poem"):
                image = state.library_path(p["image"])
                if kind == "poem" and not draft:
                    stage("Riset web + bait orisinal Ollama", .03)
                    research = ai.web_research(p["topic"], "poem", p.get("account_id"), cancel)
                    draft = ai.poem(p["topic"], research, p.get("signature", "ruang miring"), cancel)
                pool = p.get("music_pool") or ([p["music"]] if p.get("music") else [])
                music = random.choice(pool) if pool else None
                stage("Render zoompan + partikel + musik 9:16", .15)
                target = folder / "shorts.mp4"
                render.motion_video(str(image), str(target), folder, p.get("effect", "rain"), seconds, music,
                                    draft if kind == "poem" else None, width, height, cancel,
                                    lambda v: progress(.15 + .75*v))
                metadata = {**metadata, **{k: draft[k] for k in ("title", "description", "tags", "hashtags") if draft and k in draft}} if draft else metadata
                name = (draft.get("title", "Kartu Shorts") if draft else "Clipdrop") + ".mp4"
            else:
                source = state.library_path(p["source"])
                seconds = min(seconds, media.duration(source))
                analysis = ANALYSIS / ("reaction-" + job["id"])
                if not draft:
                    stage("Sampel frame + konteks → naskah Ollama", .03)
                    frames = extract_frames(source, analysis, seconds)
                    research = ai.web_research(p.get("context", "kejadian lucu"), "reaction", p.get("account_id"), cancel) if p.get("research") else None
                    draft = ai.reaction(p.get("context", ""), seconds, research, frames, cancel)
                stage("TTS Indonesia per kalimat", .13)
                segments = tts.synthesize(draft["lines"], folder, p.get("voice", "id-ID-GadisNeural"),
                                          p.get("rate", "+0%"), p.get("fallback_tts", False), cancel)
                stage("Subtitle mengikuti durasi TTS nyata", .26)
                narration, timed = render.build_narration(segments, folder, seconds, cancel)
                analysis.mkdir(parents=True, exist_ok=True)
                (analysis / "reaction.srt").write_text(render.srt_text(timed), encoding="utf-8")
                (analysis / "reaction.json").write_text(json.dumps({"draft": draft, "subtitles": timed}, ensure_ascii=False), encoding="utf-8")
                stage("Ducking audio asli + banner + subtitle", .32)
                target = folder / "reaction.mp4"
                render.reaction_video(str(source), str(target), folder, draft["banner"], narration, timed, seconds,
                                      width, height, p.get("crop", True), cancel, lambda v: progress(.32 + .58*v))
                metadata = {**metadata, **{k: draft[k] for k in ("title", "description", "tags", "hashtags") if k in draft}}
                name = draft.get("title", "Reaction Warga +62") + ".mp4"
            stage("Verifikasi dan simpan ke Library/Hasil", .94)
            media.check_cancel(cancel)
            dest = _save_output(target, name, metadata)
            result = {"path": str(dest), "name": dest.name, "metadata": metadata}
            job["result"] = result
            upload_id = None
            if p.get("auto_upload"):
                meta = {**metadata, **{k: p[k] for k in ("privacy", "synthetic", "made_for_kids") if k in p}}
                meta.setdefault("title", dest.stem)
                meta.setdefault("description", "#Shorts")
                uj = submit_upload(runner, dest, p["account_id"], meta, p.get("consent", False))
                upload_id = uj["id"]
                job["result"]["upload_job_id"] = upload_id
            return True, dest.name + (" · upload diantrekan " + upload_id if upload_id else " · tersimpan di folder Hasil")
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    return runner.submit((title or label) + " · " + (p.get("topic") or p.get("context") or "Library")[:60], run, files=sources)
