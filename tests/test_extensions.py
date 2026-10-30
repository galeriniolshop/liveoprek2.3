from pathlib import Path
import io
import json
import time
import pytest
import requests


def test_render_all_particles_and_card(appdata, sample):
    from extensions import render, media
    draft = {"ribbon": "TETAP PULANG", "lines": ["Ada jalan yang panjang.", "Ada hati yang tetap pulang."], "signature": "ruang miring"}
    for effect in ("rain", "petals", "snow", "embers"):
        output = appdata/(effect+".mp4")
        render.motion_video(str(sample["image"]), str(output), appdata/effect, effect, 5,
                            str(sample["audio"]), draft, 360, 640)
        v = next(s for s in media.probe(output)["streams"] if s["codec_type"] == "video")
        assert v["codec_name"] == "h264" and (v["width"], v["height"]) == (360, 640)
        assert media.has_audio(output) and 4.9 < media.duration(output) < 5.3


def test_reaction_tts_fallback_ducking_and_subtitles(appdata, sample):
    from extensions import tts, render, media
    segments = tts.synthesize(["Wah, kok bisa begitu, warga?", "Aku perlu waktu mencerna ini."], appdata/"voice", fallback=True)
    narration, timed = render.build_narration(segments, appdata/"reaction", 7)
    output = appdata/"reaction.mp4"
    render.reaction_video(str(sample["video"]), str(output), appdata/"reaction", "REAKSI WARGA", narration, timed, 7, 360, 640)
    assert media.duration(output) > 6.9
    assert "Dialogue:" in (appdata/"reaction"/"reaction.ass").read_text()
    assert "00:00:" in render.srt_text(timed)


def test_creative_job_uses_original_output_and_auto_upload(appdata, sample, monkeypatch):
    import services as svc
    from extensions import jobs, state
    runner = svc.JobRunner(1)
    calls = []
    def fake_upload(runner, path, account, meta, consent):
        calls.append((path, account, consent))
        return {"id": "upload1"}
    monkeypatch.setattr(jobs, "submit_upload", fake_upload)
    job = jobs.submit_creative(runner, "motion", {"image": str(sample["image"]), "music": str(sample["audio"]),
                               "seconds": 5, "resolution": "720p", "auto_upload": True, "consent": True, "account_id": "account"})
    # Use low resolution for this integration test without changing production default.
    deadline = time.time()+35
    while job["status"] in ("antre", "berjalan") and time.time() < deadline:
        time.sleep(.1)
    assert job["status"] == "selesai", job["detail"]
    result = job["result"]
    assert Path(result["path"]).parent == svc.DIRS["output"]
    assert result["upload_job_id"] == "upload1"
    assert calls[0][1:] == ("account", True)


class Response:
    def __init__(self, status, data=None, headers=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._data = data or {}
        self.headers = headers or {}
        self.content = b"{}"
    def json(self):
        return self._data


def test_oauth_pkce_binding_and_encrypted_persistence(appdata, monkeypatch):
    from extensions import youtube, state
    from extensions.security import encrypt
    from urllib.parse import urlparse, parse_qs
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    url = youtube.begin_auth("a"*64)
    assert "redirect1x.streamlit.app" in url and "code_challenge_method=S256" in url
    token = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(ValueError, match="sesi browser lain"):
        youtube.finish_auth("https://relay/?code=abc&state="+token, "b"*64)
    with pytest.raises(ValueError, match="sudah dipakai"):
        youtube.finish_auth("https://relay/?code=abc&state="+token, "a"*64)
    with state.connect(True) as c:
        c.execute("INSERT INTO channels VALUES(?,?,?,?,?,?)", ("aid", "cid", "Channel", "", encrypt(json.dumps({"access_token":"secret-access", "refresh_token":"secret-refresh", "expiry":time.time()+3600})), time.time()))
    assert youtube.accounts()[0]["title"] == "Channel"
    assert "secret-refresh" not in state.DB.read_bytes().decode(errors="ignore")
    assert youtube.access_token("aid") == "secret-access"


def test_google_resumable_8mib_and_deduplication(appdata, sample, monkeypatch):
    from extensions import youtube, state
    size = youtube.UPLOAD_CHUNK + 123
    path = state.asset(sample["video"])
    with Path(path["path"]).open("wb") as f:
        f.truncate(size)
    path = state.asset(path["path"])
    received = bytearray()
    puts = []
    monkeypatch.setattr(youtube, "access_token", lambda *a, **k: "test-token")
    def post(url, **kw):
        return Response(201, headers={"Location":"https://www.googleapis.com/upload/session"})
    def put(url, **kw):
        rg = kw["headers"]["Content-Range"]
        puts.append(rg)
        if rg.startswith("bytes */"):
            return Response(308, headers={"Range":f"bytes 0-{len(received)-1}"} if received else {})
        start = int(rg.split()[1].split("-")[0])
        assert start == len(received)
        assert len(kw["data"]) <= 8*1024**2
        received.extend(kw["data"])
        if len(received) == size:
            return Response(201, {"id":"VIDEO123"})
        return Response(308, headers={"Range":f"bytes 0-{len(received)-1}"})
    monkeypatch.setattr(youtube.requests, "post", post)
    monkeypatch.setattr(youtube.requests, "put", put)
    meta = {"title":"Test", "privacy":"private"}
    assert youtube.upload_video("account", path, meta, "j1")["video_id"] == "VIDEO123"
    assert puts == [f"bytes 0-{youtube.UPLOAD_CHUNK-1}/{size}", f"bytes {youtube.UPLOAD_CHUNK}-{size-1}/{size}"]
    assert youtube.upload_video("account", path, meta, "j2")["video_id"] == "VIDEO123"
    assert len(puts) == 2


def test_original_uploader_resume_auth_and_range(appdata, sample):
    import uploader
    server = uploader.UploadServer(0, "test-token", .001)
    server.start()
    assert not server.error
    port = server.httpd.server_port
    base = f"http://127.0.0.1:{port}"
    headers = {"X-Token":"test-token"}
    raw = sample["image"].read_bytes()
    try:
        assert requests.get(base+"/status?name=resume.png").status_code == 401
        assert requests.get(base+"/status?name=resume.png", headers=headers).json()["offset"] == 0
        cut = len(raw)//2
        assert requests.put(base+f"/chunk?name=resume.png&offset=0", headers=headers, data=raw[:cut]).json()["offset"] == cut
        assert requests.put(base+f"/chunk?name=resume.png&offset=0", headers=headers, data=raw[:cut]).status_code == 409
        r = requests.put(base+f"/chunk?name=resume.png&offset={cut}", headers=headers, data=raw[cut:])
        assert r.status_code == 200
        r = requests.post(base+f"/finish?name=resume.png&hint=auto&size={len(raw)}", headers=headers)
        assert r.status_code == 200, r.text
        name = r.json()["saved_as"]
        r = requests.get(base+f"/file?kind=thumb&name={name}&t=test-token", headers={"Range":"bytes=0-9"})
        assert r.status_code == 206 and r.content == raw[:10]
        page = requests.get(base+"/").text
        assert "color-scheme:light" in page and "prefers-color-scheme:dark" not in page
    finally:
        server.httpd.shutdown()
        server.httpd.server_close()


def test_clipdrop_key_not_in_job_or_html_storage(appdata, monkeypatch):
    from extensions import clipdrop
    html = clipdrop.request_html([])
    assert "background:#fff" in html and "localStorage" not in html
    assert "topWin.history.replaceState" in html
    def post(url, **kw):
        assert kw["headers"]["x-api-key"] == "one-shot-key"
        class ImageResponse(Response):
            def iter_content(self, n):
                yield (appdata/"../fixtures-not-used").name.encode() if False else (Path(__file__).parent/"" ).name.encode()
        # A real tiny image, not a provider credential echo.
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
        r = Response(200, headers={"Content-Type":"image/png"})
        r.iter_content = lambda n: [buf.getvalue()]
        r.close = lambda: None
        return r
    monkeypatch.setattr(clipdrop.requests, "post", post)
    output = clipdrop.generate("test", "one-shot-key")
    assert output.is_file()
    assert b"one-shot-key" not in output.read_bytes()
