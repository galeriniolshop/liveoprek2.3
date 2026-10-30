"""Konfigurasi tambahan; data tetap memakai folder Library aplikasi asli."""
from __future__ import annotations
import os
from pathlib import Path
import services as svc

ROOT = Path(__file__).resolve().parents[1]
DATA = svc.BASE
WORK = svc.TMP / "creative"
ANALYSIS = DATA / "analysis"
RUN = DATA / "run"
DB = DATA / "extensions.sqlite3"
VIDEO_EXT = svc.VIDEO_EXTS
AUDIO_EXT = svc.AUDIO_EXTS
IMAGE_EXT = svc.IMAGE_EXTS
UPLOAD_CHUNK = 8 * 1024 * 1024
REDIRECT_URI = "https://redirect1x.streamlit.app"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/youtube.readonly"]
for folder in (WORK, ANALYSIS, RUN):
    folder.mkdir(parents=True, exist_ok=True)


def secret(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st
        if name in st.secrets:
            return str(st.secrets[name])
        if "google" in st.secrets and name.startswith("GOOGLE_"):
            return str(st.secrets["google"].get(name.removeprefix("GOOGLE_").lower(), default))
    except Exception:
        pass
    return default


def flag(name: str, default=False):
    return secret(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


def font(name="regular"):
    names = {"regular": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf",
             "italic": "DejaVuSans-Oblique.ttf", "serif": "DejaVuSerif.ttf"}
    return str(ROOT / "assets" / "fonts" / names.get(name, names["regular"]))
