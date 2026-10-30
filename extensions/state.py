"""SQLite kecil untuk OAuth, draft, dan sesi upload; Library tetap milik services.py."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from .config import DB, DATA

_INIT = False
_LOCK = threading.Lock()


@contextmanager
def connect(write=False):
    init()
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        if write:
            c.execute("BEGIN IMMEDIATE")
        yield c
        if write:
            c.commit()
    except Exception:
        if write:
            c.rollback()
        raise
    finally:
        c.close()


def init():
    global _INIT
    with _LOCK:
        if _INIT:
            return
        DB.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB, timeout=30) as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS oauth(state TEXT PRIMARY KEY,verifier TEXT NOT NULL,browser_hash TEXT NOT NULL,created REAL);
            CREATE TABLE IF NOT EXISTS channels(id TEXT PRIMARY KEY,channel_id TEXT UNIQUE,title TEXT,thumbnail TEXT,vault TEXT NOT NULL,created REAL);
            CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated REAL);
            CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY,path TEXT NOT NULL,channel_id TEXT NOT NULL,
                fingerprint TEXT,metadata TEXT,session_uri TEXT,offset INTEGER DEFAULT 0,video_id TEXT,updated REAL);
            """)
        try:
            DB.chmod(0o600)
        except OSError:
            pass
        _INIT = True


def rows(sql, args=()):
    with connect() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql, args=()):
    with connect() as c:
        r = c.execute(sql, args).fetchone()
        return dict(r) if r else None


def kv_set(key, value):
    with connect(True) as c:
        c.execute("INSERT OR REPLACE INTO kv VALUES(?,?,?)", (key,json.dumps(value,ensure_ascii=False),time.time()))


def kv_get(key, default=None):
    row = one("SELECT value FROM kv WHERE key=?", (key,))
    return json.loads(row["value"]) if row else default


def library_path(path):
    p = Path(path).resolve()
    if DATA not in p.parents or not p.is_file():
        raise ValueError("File Library tidak ditemukan atau berada di luar folder data.")
    return p


def asset_path(asset):
    # Kompatibel dengan renderer; sumber kebenaran file tetap services.DIRS.
    return library_path(asset["path"] if isinstance(asset, dict) else asset)


def asset(path):
    p = library_path(path)
    stat = p.stat()
    return {"id": str(p),
            "path": str(p), "name": p.name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def fingerprint(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def assets(kind):
    import services as svc
    if kind == "image":
        paths = [p for p in svc.list_paths("thumb") if p.suffix.lower() in svc.IMAGE_EXTS]
    elif kind == "results":
        paths = [p for k in ("output", "video") for p in svc.list_paths(k) if p.suffix.lower() in svc.VIDEO_EXTS]
    else:
        paths = svc.list_paths(kind)
    return [asset(p) for p in paths]
