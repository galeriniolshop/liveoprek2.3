from pathlib import Path
import json
import pytest


def test_original_cookie_and_url_import_parsing(appdata):
    import services as svc
    urls = svc.parse_urls("https://youtu.be/abc, https://drive.google.com/file/d/xyz/view\nhttps://example.com/a.mp4")
    assert len(urls) == 3
    assert svc.classify_url(urls[0]) == "web"
    assert svc.classify_url(urls[1]) == "gdrive_file"
    text, count, domains = svc.parse_cookies(json.dumps([{"domain":".youtube.com", "name":"sid", "value":"secret", "path":"/", "secure":True, "expirationDate":2000000000}]))
    assert count == 1 and "youtube.com" in domains
    box = svc.CookieBox(text)
    release = box.make_releaser()
    p = box.write_to(svc.TMP)
    assert p.read_text().rstrip().endswith("sid\tsecret")
    release()
    assert box.write_to(svc.TMP) is None
    p.unlink()


def test_deno_runtime_discovered_and_version(appdata):
    import services as svc
    import subprocess
    assert svc.ensure_deno()
    result = subprocess.run([__import__("shutil").which("deno"), "--version"], capture_output=True, text=True)
    assert result.returncode == 0 and "deno" in result.stdout


def test_ollama_grounded_prompt_and_no_fake_views(appdata, monkeypatch):
    from extensions import ai
    calls = []
    def post(endpoint, payload, *args, **kw):
        calls.append((endpoint, payload))
        if endpoint == "/api/web_search":
            return {"results":[{"title":"Referensi nyata", "url":"https://example.com/reference", "content":"Sampel pencarian"}]}
        return {"message":{"content":json.dumps({"ribbon":"PULANG", "lines":["Ada jalan pulang."], "signature":"ruang", "title":"Pulang", "description":"Puisi orisinal.", "tags":["puisi"], "hashtags":["#Shorts"], "visual_prompt":"quiet lake, no text", "research_summary":"Sampel terbatas."})}}
    monkeypatch.setattr(ai, "post", post)
    research = ai.web_research("pulang", "poem")
    assert research["references"][0]["views"] is None
    draft = ai.poem("pulang", research)
    assert draft["lines"] == ["Ada jalan pulang."]
    assert calls[-1][1]["model"] == "gemma4:31b"
    assert calls[-1][1]["stream"] is False
    assert "research" in json.loads(calls[-1][1]["messages"][1]["content"])


def test_live_research_is_not_shorts_only(appdata, monkeypatch):
    from extensions import ai
    calls = []
    monkeypatch.setattr(ai, "post", lambda endpoint,payload,**kw: (calls.append(payload), {"results":[]})[1])
    ai.web_research("musik santai", "live")
    assert "Shorts" not in calls[0]["query"]
    assert "live musik playlist 24 jam" in calls[0]["query"]


def test_ytdlp_receives_explicit_deno_runtime(appdata, monkeypatch):
    import services as svc
    import yt_dlp
    seen = {}
    class FakeDL:
        def __init__(self, opts): seen.update(opts)
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def extract_info(self,url,download=True): return {"id":"test"}
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeDL)
    monkeypatch.setattr(svc, "ensure_deno", lambda: True)
    ok, detail = svc._ytdlp({"detail":""}, "https://youtu.be/test", appdata, "video", 720, True)
    assert ok, detail
    assert "deno" in seen["js_runtimes"]
