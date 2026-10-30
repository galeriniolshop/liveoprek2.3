"""Ollama Cloud with grounded web research, strict JSON, and no fabricated metrics."""
from __future__ import annotations
import base64
import json
from pathlib import Path
import re
import time
import requests
from .config import secret
from .media import check_cancel

MODEL = "gemma4:31b"  # API model name; the CLI alias is gemma4:31b-cloud.
BASE = "https://ollama.com"


def configured() -> bool:
    return bool(secret("OLLAMA_API_KEY"))


def post(endpoint: str, payload: dict, timeout=120, cancel=None) -> dict:
    key = secret("OLLAMA_API_KEY")
    if not key:
        raise ValueError("OLLAMA_API_KEY belum diisi di Secrets server (bukan URL browser).")
    check_cancel(cancel)
    try:
        r = requests.post(BASE + endpoint, json=payload,
                          headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                          timeout=(15, timeout))
        if not r.ok:
            raise RuntimeError(f"Ollama HTTP {r.status_code}. Periksa kunci, model, kuota, atau izin web search.")
        return r.json()
    except requests.RequestException:
        raise RuntimeError("Koneksi Ollama gagal/timeout. Job tidak memakai naskah AI palsu.")
    finally:
        del key


def web_research(topic: str, mode="poem", account_id=None, cancel=None) -> dict:
    intent = {"poem": "kata kata puitis viral", "reaction": "reaction lucu", "live": "live musik playlist 24 jam"}.get(mode, mode)
    query = f"YouTube {'Shorts ' if mode != 'live' else ''}Indonesia {topic} {intent} {time.strftime('%Y')}"
    results = post("/api/web_search", {"query": query[:500], "max_results": 6}, cancel=cancel).get("results", [])
    refs = [{"title": str(x.get("title", ""))[:200], "url": x.get("url", ""),
             "snippet": str(x.get("content", ""))[:1000], "views": None, "source": "Ollama web_search"}
            for x in results if str(x.get("url", "")).startswith(("https://", "http://"))]
    # Optional official, quota-consuming YouTube search; never label search rank as view count.
    api_key = secret("YOUTUBE_API_KEY")
    headers = {}
    if account_id and not api_key:
        try:
            headers = {"Authorization": "Bearer " + _account_token(account_id)}
        except Exception:
            pass  # Web-search references remain available without YouTube OAuth.
    params = {"part": "snippet", "type": "video", "q": topic[:80] + (" #Shorts" if mode != "live" else " live"),
              "maxResults": 5, "order": "viewCount", **({"videoDuration": "short"} if mode != "live" else {}), "relevanceLanguage": "id",
              "publishedAfter": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()-30*86400))}
    if api_key:
        params["key"] = api_key
    if api_key or headers:
        try:
            r = requests.get("https://www.googleapis.com/youtube/v3/search", params=params, headers=headers, timeout=30)
            if r.ok:
                items = r.json().get("items", [])
                ids = [x["id"]["videoId"] for x in items if x.get("id", {}).get("videoId")]
                p = {"part": "snippet,statistics,contentDetails", "id": ",".join(ids)}
                if api_key:
                    p["key"] = api_key
                details = requests.get("https://www.googleapis.com/youtube/v3/videos", params=p, headers=headers, timeout=30)
                stats = {x["id"]: x for x in details.json().get("items", [])} if details.ok else {}
                for item in items:
                    vid = item.get("id", {}).get("videoId")
                    if not vid:
                        continue
                    d = stats.get(vid, {})
                    refs.append({"title": item["snippet"]["title"], "url": ("https://www.youtube.com/watch?v=" if mode == "live" else "https://www.youtube.com/shorts/") + vid,
                                 "snippet": item["snippet"].get("description", "")[:700],
                                 "views": int(d["statistics"]["viewCount"]) if d.get("statistics", {}).get("viewCount") is not None else None,
                                 "published_at": item["snippet"].get("publishedAt"), "duration": d.get("contentDetails", {}).get("duration"),
                                 "source": "YouTube Data API; 30 hari terakhir"})
        except (requests.RequestException, KeyError, ValueError):
            pass  # grounded web refs remain usable; no invented YouTube metrics
    return {"query": query, "collected_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "references": refs[:11],
            "disclaimer": "Referensi pencarian adalah sampel, bukan pemeringkatan lengkap atau jaminan viral. View hanya ditampilkan bila dikembalikan API."}


def _account_token(account_id):
    from .youtube import access_token
    return access_token(account_id)


def extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError("Ollama tidak mengembalikan JSON yang valid.")
        result = json.loads(match.group())
    if not isinstance(result, dict):
        raise ValueError("Output AI harus berupa objek JSON.")
    return result


def chat_json(system: str, user: dict, schema: dict, cancel=None, images=None) -> dict:
    message = {"role": "user", "content": json.dumps(user, ensure_ascii=False)}
    if images:
        message["images"] = [base64.b64encode(Path(p).read_bytes()).decode() for p in images[:3]]
    payload = {"model": secret("OLLAMA_MODEL", MODEL), "stream": False,
               "messages": [{"role": "system", "content": system}, message],
               "format": schema, "options": {"temperature": .65, "num_ctx": 16384, "num_predict": 2200}}
    result = post("/api/chat", payload, 180, cancel)
    return extract_json(result.get("message", {}).get("content", ""))


def _strings(maximum):
    return {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": maximum}


POEM_SCHEMA = {"type": "object", "properties": {
    "ribbon": {"type": "string"}, "lines": _strings(6), "signature": {"type": "string"},
    "title": {"type": "string"}, "description": {"type": "string"}, "tags": _strings(15),
    "hashtags": _strings(6), "visual_prompt": {"type": "string"}, "research_summary": {"type": "string"}},
    "required": ["ribbon", "lines", "signature", "title", "description", "tags", "hashtags", "visual_prompt", "research_summary"]}


def poem(topic: str, research: dict, signature="ruang miring", cancel=None) -> dict:
    system = ("Anda penulis Shorts Indonesia. Gunakan referensi yang benar-benar diberikan; jangan mengarang angka tren. "
              "Tulis orisinal, bukan menyalin puisi orang. ribbon maksimal 32 karakter kapital, 3-5 baris bait pendek masing-masing <=42 karakter, "
              "total <=180 karakter. Nada reflektif, emosional, mudah dibaca. signature adalah nama ruang/kreator, bukan URL. "
              "Visual prompt bahasa Inggris untuk latar Clipdrop vertikal 9:16, tanpa tulisan, sisakan ruang tengah. "
              "Judul <=90 karakter, deskripsi SEO jujur, hashtag relevan termasuk #Shorts. Jangan menjanjikan CTR/viral.")
    data = chat_json(system, {"topic": topic, "signature": signature, "research": research}, POEM_SCHEMA, cancel)
    data["ribbon"] = str(data["ribbon"]).upper()[:36]
    data["lines"] = [str(x)[:48] for x in data["lines"][:5]]
    data["signature"] = str(data.get("signature") or signature)[:35]
    data["research"] = research
    return data


REACTION_SCHEMA = {"type": "object", "properties": {
    "banner": {"type": "string"}, "lines": _strings(8), "title": {"type": "string"},
    "description": {"type": "string"}, "hashtags": _strings(6), "tags": _strings(15)},
    "required": ["banner", "lines", "title", "description", "hashtags", "tags"]}


def reaction(context: str, seconds: float, research: dict | None = None, images=None, cancel=None) -> dict:
    system = ("Anda narator reaction YouTube Shorts gaya Warga +62: santai, seru, akrab, tidak kasar atau merendahkan. "
              "Naskah harus reaksi terhadap konteks/frame yang benar-benar tersedia, jangan mengaku melihat bagian video yang tidak diberikan. "
              "Maksimal 6 baris, setiap baris 5-11 kata, total maksimum yang diucapkan sesuai durasi. "
              "Banner lucu <=40 karakter. SISIPKAN jeda pemahaman, bukan kata 'jeda'. Hindari klaim palsu, identitas orang, dan fitnah. "
              "Sertakan komentar yang bisa diucapkan alami dalam Bahasa Indonesia. Metadata relevan #Shorts; bukan jaminan viral.")
    data = chat_json(system, {"context": context, "duration_seconds": seconds,
                              "max_spoken_words": max(12, int(seconds*2.1)), "research": research or {}},
                     REACTION_SCHEMA, cancel, images)
    data["banner"] = str(data["banner"])[:44]
    data["lines"] = [str(x)[:130] for x in data["lines"][:6]]
    return data


META_SCHEMA = {"type": "object", "properties": {
    "title": {"type": "string"}, "description": {"type": "string"}, "hashtags": _strings(8),
    "tags": _strings(20), "category_id": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["title", "description", "hashtags", "tags", "category_id", "reason"]}


def metadata(topic: str, evidence: dict, live=False, cancel=None, images=None) -> dict:
    system = ("Buat metadata YouTube Bahasa Indonesia yang menarik, jujur, tidak clickbait menipu. "
              "Title <=90 karakter, description <=4200 karakter, tags pendek tanpa #, hashtags relevan. "
              "Kategori 10 untuk musik, 24 hiburan, 22 orang/blog; pilih yang sesuai. "
              "Gaya Warga +62 boleh ringan. Gunakan hanya bukti konten yang diberikan. Analisis PCM adalah heuristik, bukan identifikasi lagu/artis. "
              "Jangan mengarang lagu, artis, jumlah penonton, atau tren. Live boleh menyebut radio/playlist bila sesuai. "
              "Sertakan #Shorts hanya untuk Shorts, bukan live. Jelaskan alasan singkat. Tidak ada jaminan algoritma/viral.")
    data = chat_json(system, {"topic": topic, "live": live, "evidence": evidence}, META_SCHEMA, cancel, images)
    data["title"] = str(data["title"])[:95]
    data["description"] = str(data["description"])[:4200]
    data["tags"] = [str(x).replace("#", "")[:40] for x in data["tags"][:20]]
    data["hashtags"] = list(dict.fromkeys([str(x) if str(x).startswith("#") else "#"+str(x) for x in data["hashtags"]]))[:8]
    if not live and "#Shorts" not in data["hashtags"]:
        data["hashtags"].append("#Shorts")
    return data