"""Google OAuth + YouTube Data API. Tokens and resumable session URIs are encrypted."""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlencode, urlparse, parse_qs
import fcntl
import requests
from .config import RUN, SCOPES, REDIRECT_URI, UPLOAD_CHUNK, secret
from .security import encrypt, decrypt, redact
from . import state as store

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class APIError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(f"YouTube HTTP {status}: {message}")


def client_config():
    cid, cs = secret("GOOGLE_CLIENT_ID"), secret("GOOGLE_CLIENT_SECRET")
    if not cid or not cs:
        raise ValueError("Isi GOOGLE_CLIENT_ID dan GOOGLE_CLIENT_SECRET di Secrets. Gunakan OAuth client tipe Web application.")
    return cid, cs, secret("GOOGLE_REDIRECT_URI", REDIRECT_URI)


def configured():
    return bool(secret("GOOGLE_CLIENT_ID") and secret("GOOGLE_CLIENT_SECRET"))


def begin_auth(browser_hash: str) -> str:
    if len(browser_hash) != 64:
        raise ValueError("Sesi browser OAuth belum siap. Muat ulang aplikasi.")
    cid, _, redirect = client_config()
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    with store.connect(True) as c:
        c.execute("DELETE FROM oauth WHERE created<?", (time.time()-600,))
        c.execute("INSERT INTO oauth VALUES(?,?,?,?)", (state, encrypt(verifier), browser_hash, time.time()))
    return AUTH+"?"+urlencode({"client_id": cid, "redirect_uri": redirect, "response_type": "code",
                              "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent",
                              "include_granted_scopes": "true", "state": state,
                              "code_challenge": challenge, "code_challenge_method": "S256"})


def _error(r):
    try:
        data = r.json()
        msg = data.get("error_description") or data.get("error", {}).get("message") or data.get("error") or "Request ditolak"
        if isinstance(msg, dict):
            msg = str(msg)
    except Exception:
        msg = "Respons bukan JSON"
    return APIError(r.status_code, redact(str(msg))[:450])


def finish_auth(callback_or_code: str, browser_hash: str = "") -> list[dict]:
    code = callback_or_code.strip()
    state = None
    if code.startswith(("http://", "https://")):
        q = parse_qs(urlparse(code).query)
        if q.get("error"):
            raise ValueError("Izin Google ditolak. Tidak ada channel yang dihubungkan.")
        code, state = q.get("code", [""])[0], q.get("state", [""])[0]
    if not state:
        raise ValueError("Tempel URL callback lengkap yang mengandung code DAN state, bukan code saja.")
    with store.connect(True) as c:
        row = c.execute("SELECT * FROM oauth WHERE state=?", (state,)).fetchone()
        if not row:
            raise ValueError("OAuth state tidak dikenal/sudah dipakai. Mulai koneksi baru.")
        c.execute("DELETE FROM oauth WHERE state=?", (state,))
    if not browser_hash or not secrets.compare_digest(row["browser_hash"], browser_hash):
        raise ValueError("OAuth dimulai dari sesi browser lain. Kembali ke sesi asal atau mulai koneksi baru di sesi ini.")
    if time.time()-row["created"] > 600:
        raise ValueError("OAuth kedaluwarsa (10 menit). Mulai lagi.")
    cid, cs, redirect = client_config()
    try:
        r = requests.post(TOKEN, data={"client_id": cid, "client_secret": cs, "code": code,
                                       "code_verifier": decrypt(row["verifier"]), "grant_type": "authorization_code",
                                       "redirect_uri": redirect}, timeout=45)
    finally:
        del code
    if not r.ok:
        raise _error(r)
    tokens = r.json()
    if not tokens.get("refresh_token"):
        raise ValueError("Google tidak memberi refresh token. Cabut izin aplikasi pada akun Google lalu hubungkan ulang dengan consent.")
    tokens["expiry"] = time.time()+float(tokens.get("expires_in", 3600))-90
    try:
        resp = requests.get(API+"/channels", params={"part": "snippet", "mine": "true", "maxResults": 50},
                            headers={"Authorization": "Bearer "+tokens["access_token"]}, timeout=30)
    finally:
        pass
    if not resp.ok:
        raise _error(resp)
    items = resp.json().get("items", [])
    if not items:
        raise ValueError("Akun ini tidak mempunyai channel YouTube yang dapat diakses.")
    result = []
    for item in items:
        aid = secrets.token_hex(12)
        snippet = item["snippet"]
        vault = encrypt(json.dumps(tokens))
        with store.connect(True) as c:
            old = c.execute("SELECT id FROM channels WHERE channel_id=?", (item["id"],)).fetchone()
            if old:
                aid = old["id"]
                c.execute("UPDATE channels SET title=?,thumbnail=?,vault=? WHERE id=?",
                          (snippet["title"], snippet.get("thumbnails", {}).get("default", {}).get("url", ""), vault, aid))
            else:
                c.execute("INSERT INTO channels VALUES(?,?,?,?,?,?)",
                          (aid, item["id"], snippet["title"], snippet.get("thumbnails", {}).get("default", {}).get("url", ""), vault, time.time()))
        result.append({"id": aid, "title": snippet["title"], "channel_id": item["id"]})
    return result


def accounts() -> list[dict]:
    return store.rows("SELECT id,channel_id,title,thumbnail FROM channels ORDER BY title")


def access_token(account_id: str, force=False) -> str:
    with _locks_guard:
        lock = _locks.setdefault(account_id, threading.Lock())
    with lock:
        lockpath = RUN / f"oauth-{account_id}.lock"
        with lockpath.open("w") as lockfile:
            fcntl.flock(lockfile, fcntl.LOCK_EX)
            account = store.one("SELECT * FROM channels WHERE id=?", (account_id,))
            if not account:
                raise ValueError("Pilih channel OAuth yang valid.")
            tokens = json.loads(decrypt(account["vault"]))
            if force or time.time() >= tokens.get("expiry", 0):
                cid, cs, _ = client_config()
                r = requests.post(TOKEN, data={"client_id": cid, "client_secret": cs,
                                               "refresh_token": tokens["refresh_token"], "grant_type": "refresh_token"}, timeout=45)
                if not r.ok:
                    raise _error(r)
                fresh = r.json()
                tokens.update(fresh)
                tokens["expiry"] = time.time()+float(fresh.get("expires_in", 3600))-90
                with store.connect(True) as c:
                    c.execute("UPDATE channels SET vault=? WHERE id=?", (encrypt(json.dumps(tokens)), account_id))
            return tokens["access_token"]


def request(method, endpoint, account_id, *, params=None, body=None, retry=True) -> dict:
    headers = {"Authorization": "Bearer "+access_token(account_id), "Content-Type": "application/json"}
    try:
        r = requests.request(method, API+"/"+endpoint, params=params, headers=headers,
                             json=body, timeout=(15, 60))
    finally:
        headers.clear()
    if r.status_code == 401 and retry:
        access_token(account_id, force=True)
        return request(method, endpoint, account_id, params=params, body=body, retry=False)
    if not r.ok:
        raise _error(r)
    return r.json() if r.content else {}


def disconnect(account_id: str, active_account_ids=()):
    if account_id in set(active_account_ids):
        raise ValueError("Channel sedang dipakai live. Hentikan slot terlebih dahulu.")
    row = store.one("SELECT vault FROM channels WHERE id=?", (account_id,))
    if row:
        tok = json.loads(decrypt(row["vault"])).get("refresh_token")
        try:
            requests.post("https://oauth2.googleapis.com/revoke", data={"token": tok}, timeout=20)
        except requests.RequestException:
            pass
    with store.connect(True) as c:
        c.execute("DELETE FROM channels WHERE id=?", (account_id,))


def snippet(metadata: dict) -> dict:
    tags = metadata.get("hashtags", [])
    desc = metadata.get("description", "")
    hashline = " ".join(x if x.startswith("#") else "#"+x for x in tags)
    if hashline and hashline not in desc:
        desc += "\n\n"+hashline
    result = {"title": metadata.get("title", "Shorts baru")[:100], "description": desc[:4900],
              "tags": metadata.get("tags", [])[:20], "categoryId": str(metadata.get("category_id", "22")),
              "defaultLanguage": "id", "defaultAudioLanguage": "id"}
    # YouTube tag quota is approximately 500 characters, including separators.
    used = 0
    kept = []
    for tag in result["tags"]:
        cost = len(tag)+(2 if "," in tag or " " in tag else 0)+1
        if used+cost <= 490:
            kept.append(tag)
            used += cost
    result["tags"] = kept
    return result


def video_body(metadata):
    return {"snippet": snippet(metadata), "status": {
        "privacyStatus": metadata.get("privacy", "private"), "selfDeclaredMadeForKids": bool(metadata.get("made_for_kids", False)),
        "embeddable": True, "containsSyntheticMedia": bool(metadata.get("synthetic", True))}}


def _init_upload(account_id, path, metadata, size):
    hdr = {"Authorization": "Bearer "+access_token(account_id), "Content-Type": "application/json; charset=UTF-8",
           "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"}
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos",
                      params={"uploadType": "resumable", "part": "snippet,status"}, headers=hdr,
                      json=video_body(metadata), timeout=60)
    hdr.clear()
    if not r.ok:
        raise _error(r)
    uri = r.headers.get("Location")
    if not uri or urlparse(uri).hostname not in {"www.googleapis.com", "googleapis.com", "youtube.googleapis.com"}:
        raise RuntimeError("Google tidak memberi session upload yang valid.")
    return uri


def _offset(uri, account_id, size):
    r = requests.put(uri, headers={"Authorization": "Bearer "+access_token(account_id),
                                    "Content-Length": "0", "Content-Range": f"bytes */{size}"}, timeout=60)
    if r.status_code in (200, 201):
        return size, r.json()
    if r.status_code == 308:
        rg = r.headers.get("Range")
        return int(rg.split("-")[-1])+1 if rg else 0, None
    raise _error(r)


def upload_video(account_id, asset: dict, metadata: dict, job_id: str, progress=None, cancel=None) -> dict:
    from .media import check_cancel
    path = Path(store.asset_path(asset))
    size = path.stat().st_size
    fingerprint = store.fingerprint(path)
    key = hashlib.sha256((account_id+asset["id"]+fingerprint+json.dumps(metadata, sort_keys=True)).encode()).hexdigest()
    row = store.one("SELECT * FROM uploads WHERE id=?", (key,))
    if row and row["video_id"]:
        return {"video_id": row["video_id"], "url": "https://www.youtube.com/watch?v="+row["video_id"], "privacy": metadata.get("privacy", "private")}
    if not row:
        with store.connect(True) as c:
            c.execute("INSERT INTO uploads(id,path,channel_id,fingerprint,metadata,updated) VALUES(?,?,?,?,?,?)",
                      (key, str(path), account_id, fingerprint, json.dumps(metadata), time.time()))
        row = store.one("SELECT * FROM uploads WHERE id=?", (key,))
    if row["fingerprint"] != fingerprint or row["path"] != str(path):
        raise ValueError("File berubah sejak sesi upload dibuat; mulai upload baru.")
    uri = decrypt(row["session_uri"]) if row["session_uri"] else ""
    offset = row["offset"]
    def save(offset, uri):
        with store.connect(True) as c:
            c.execute("UPDATE uploads SET offset=?,session_uri=?,updated=? WHERE id=?", (offset, encrypt(uri), time.time(), key))
    if not uri:
        uri = _init_upload(account_id, path, metadata, size)
        offset = 0
        save(offset, uri)
    else:
        try:
            offset, done = _offset(uri, account_id, size)
            if done:
                return _finish_upload(key, done, metadata)
        except APIError as e:
            if e.status not in (400, 404, 410):
                raise
            uri, offset = _init_upload(account_id, path, metadata, size), 0
        save(offset, uri)
    deadline = time.time()+6*3600
    with path.open("rb") as f:
        while offset < size:
            if time.time() > deadline:
                raise RuntimeError("Batas upload 6 jam tercapai; offset tersimpan. Retry manual untuk melanjutkan.")
            check_cancel(cancel)
            f.seek(offset)
            block = f.read(UPLOAD_CHUNK)
            if not block:
                raise RuntimeError("Berkas berubah saat upload; batalkan dan periksa aset.")
            end = offset+len(block)-1
            headers = {"Authorization": "Bearer "+access_token(account_id), "Content-Length": str(len(block)),
                       "Content-Type": "video/mp4", "Content-Range": f"bytes {offset}-{end}/{size}"}
            last_error = None
            for attempt in range(5):
                check_cancel(cancel)
                try:
                    r = requests.put(uri, headers=headers, data=block, timeout=(20, 240))
                    if r.status_code in (200, 201):
                        result = _finish_upload(key, r.json(), metadata)
                        if progress:
                            progress(1)
                        return result
                    if r.status_code == 308:
                        rg = r.headers.get("Range")
                        new_offset = int(rg.split("-")[-1])+1 if rg else offset
                        if new_offset <= offset:
                            raise RuntimeError("Upload tidak maju; hentikan lalu coba lagi.")
                        offset = new_offset
                        save(offset, uri)
                        last_error = None
                        break
                    if r.status_code in (408, 429, 500, 502, 503, 504):
                        last_error = _error(r)
                        time.sleep(min(30, 2**attempt)+secrets.randbelow(100)/100)
                        offset, done = _offset(uri, account_id, size)
                        if done:
                            return _finish_upload(key, done, metadata)
                        save(offset, uri)
                        # Always reread from the server-confirmed offset below.
                        break
                    if r.status_code == 401 and attempt == 0:
                        headers["Authorization"] = "Bearer "+access_token(account_id, True)
                        continue
                    raise _error(r)
                except requests.RequestException as exc:
                    last_error = RuntimeError("Koneksi upload terputus; offset tersimpan untuk retry.")
                    time.sleep(min(20, 2**attempt))
                    try:
                        offset, done = _offset(uri, account_id, size)
                        if done:
                            return _finish_upload(key, done, metadata)
                        save(offset, uri)
                    except (requests.RequestException, APIError):
                        pass
                    break
            else:
                raise RuntimeError("Retry upload habis: "+str(last_error))
            if last_error is not None:
                # The outer loop rereads from the confirmed offset, including partial commits.
                continue
            if progress:
                progress(offset/size*.98)
    raise RuntimeError("Upload selesai dibaca tetapi Google belum mengembalikan video ID. Retry akan menanyakan offset Google.")


def _finish_upload(key, response, metadata):
    vid = response.get("id")
    if not vid:
        raise RuntimeError("Respons upload tidak memiliki video ID.")
    with store.connect(True) as c:
        c.execute("UPDATE uploads SET video_id=?,offset=?,updated=? WHERE id=?", (vid, -1, time.time(), key))
    return {"video_id": vid, "url": "https://www.youtube.com/watch?v="+vid,
            "privacy": metadata.get("privacy", "private"), "note": "Proyek API belum diaudit dapat mengunci video ke private."}


def create_live(account_id, metadata, privacy="private", resolution="720p", fps=30):
    stream = request("POST", "liveStreams", account_id, params={"part": "snippet,cdn,status"}, body={
        "snippet": {"title": metadata["title"][:100]},
        "cdn": {"frameRate": "variable" if fps > 30 else str(fps), "ingestionType": "rtmp", "resolution": resolution},
        "contentDetails": {"isReusable": False}})
    try:
        broadcast = request("POST", "liveBroadcasts", account_id, params={"part": "snippet,status,contentDetails"}, body={
            "snippet": {"title": metadata["title"][:100], "description": metadata.get("description", "")[:4900],
                        "scheduledStartTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
            "contentDetails": {"enableAutoStart": False, "enableAutoStop": False, "enableDvr": True,
                               "latencyPreference": "normal", "monitorStream": {"enableMonitorStream": True}}})
        request("POST", "liveBroadcasts/bind", account_id,
                params={"id": broadcast["id"], "streamId": stream["id"], "part": "id,snippet,status"})
    except Exception:
        # Do not leak an orphaned reusable ingest endpoint.
        try:
            request("DELETE", "liveStreams", account_id, params={"id": stream["id"]})
        except Exception:
            pass
        raise
    ingest = stream["cdn"]["ingestionInfo"]
    return {"broadcast_id": broadcast["id"], "stream_id": stream["id"],
            "url": ingest["rtmpUrl"].rstrip("/")+"/"+ingest["streamName"]}


def wait_live(account_id, info, stop, timeout=180):
    deadline = time.time()+timeout
    while time.time() < deadline:
        if stop():
            raise RuntimeError("Live dibatalkan sebelum aktif.")
        broadcast = request("GET", "liveBroadcasts", account_id, params={"part": "status", "id": info["broadcast_id"]})
        lifecycle = broadcast.get("items", [{}])[0].get("status", {}).get("lifeCycleStatus")
        if lifecycle == "live":
            return
        if lifecycle == "testing":
            request("POST", "liveBroadcasts/transition", account_id,
                    params={"id": info["broadcast_id"], "broadcastStatus": "live", "part": "status"})
            return
        if lifecycle == "complete":
            raise RuntimeError("Broadcast YouTube sudah complete; hentikan dan start slot untuk membuat siaran baru.")
        stream = request("GET", "liveStreams", account_id, params={"part": "status", "id": info["stream_id"]})
        if stream.get("items") and stream["items"][0]["status"]["streamStatus"] == "active":
            request("POST", "liveBroadcasts/transition", account_id,
                    params={"id": info["broadcast_id"], "broadcastStatus": "testing", "part": "status"})
            for _ in range(40):
                if stop():
                    raise RuntimeError("Live dibatalkan saat testing.")
                b = request("GET", "liveBroadcasts", account_id, params={"part": "status", "id": info["broadcast_id"]})
                if b.get("items") and b["items"][0]["status"]["lifeCycleStatus"] == "testing":
                    request("POST", "liveBroadcasts/transition", account_id,
                            params={"id": info["broadcast_id"], "broadcastStatus": "live", "part": "status"})
                    return
                time.sleep(2)
            raise RuntimeError("YouTube tidak masuk testing tepat waktu.")
        time.sleep(4)
    raise RuntimeError("Sinyal RTMP belum aktif di YouTube. Periksa log FFmpeg, stream key, dan batas siaran akun.")


def complete_live(account_id, broadcast_id):
    if not broadcast_id:
        return
    try:
        request("POST", "liveBroadcasts/transition", account_id,
                params={"id": broadcast_id, "broadcastStatus": "complete", "part": "status"})
    except APIError:
        # A failed/prepared broadcast cannot always transition directly to complete.
        pass