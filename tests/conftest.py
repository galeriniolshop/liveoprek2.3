import importlib
import os
from pathlib import Path
import sys
import pytest


@pytest.fixture()
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVEOPREK_DATA", str(tmp_path))
    monkeypatch.setenv("APP_SECRET", "test-only-secret-012345678901234567890123456789")
    monkeypatch.setenv("UPLOAD_TOKEN", "test-only-upload-token")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    for name in list(sys.modules):
        if name in {"services", "mediatools", "uploader"} or name.startswith("extensions"):
            monkeypatch.delitem(sys.modules, name)
    import services as svc
    from extensions import state
    state.init()
    yield tmp_path
    for stream in list(svc.STREAM_INSTANCES.values()):
        if stream.running:
            stream.stop()


@pytest.fixture()
def sample(appdata):
    from extensions import media
    import services as svc
    folder = appdata / "fixtures"
    folder.mkdir()
    video, audio = folder / "sample.mp4", folder / "sample.m4a"
    media.ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15", "-f", "lavfi", "-i",
                  "sine=frequency=440:sample_rate=44100", "-t", "3", "-c:v", "libx264", "-preset", "ultrafast",
                  "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)])
    media.ffmpeg(["-f", "lavfi", "-i", "sine=frequency=660:sample_rate=44100", "-t", "4", "-c:a", "aac", str(audio)])
    from PIL import Image
    image = folder / "sample.png"
    Image.new("RGB", (360, 640), "#dceaf2").save(image)
    return {"video": svc.place_file(video)[1], "audio": svc.place_file(audio)[1], "image": svc.place_file(image)[1]}
