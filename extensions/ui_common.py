from __future__ import annotations
import hashlib
import json
from pathlib import Path
import time
import streamlit as st
from .config import secret
from . import state as store, ai, youtube
import services as svc
from .jobs import submit_upload

RUNNER = None


def human(n):
    n = float(n or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:,.1f} {unit}"
        n /= 1024


def choose(label, items, key, default=None):
    ids = [a["id"] for a in items]
    lookup = {a["id"]: a for a in items}
    selected = st.multiselect(label, ids, default=[x for x in (default or []) if x in ids],
                              format_func=lambda x: lookup[x]["name"], key=key)
    return selected


def channel_manager(prefix):
    with st.expander("Google OAuth · koneksi multi-channel", expanded=False):
        st.caption("OAuth client: Web application. Redirect default: https://redirect1x.streamlit.app. "
                   "Domain tersebut harus Anda kendalikan; paket ini menyertakan aplikasi relay di folder relay/.")
        if not youtube.configured():
            st.info("Isi GOOGLE_CLIENT_ID dan GOOGLE_CLIENT_SECRET di Secrets. Jangan menaruh client secret/refresh token di URL.")
            return
        if st.button("Hubungkan / tambah channel", key=prefix+"oauth"):
            if "oauth_browser" not in st.session_state:
                st.session_state.oauth_browser = hashlib.sha256(__import__("secrets").token_bytes(32)).hexdigest()
            try:
                url = youtube.begin_auth(st.session_state.oauth_browser)
                st.link_button("Buka izin Google →", url, type="primary")
                st.caption("Setelah izin, salin URL callback lengkap dari relay kembali ke sesi studio ini.")
            except Exception as e:
                st.error(str(e))
        callback = st.text_input("URL callback lengkap (code + state)", type="password", key=prefix+"callback")
        if st.button("Verifikasi & simpan channel", key=prefix+"exchange"):
            try:
                channels = youtube.finish_auth(callback, st.session_state.get("oauth_browser", ""))
                st.session_state[prefix+"callback"] = ""
                st.success("Terhubung: "+", ".join(c["title"] for c in channels))
                st.rerun()
            except Exception as e:
                st.error(str(e))
        for a in youtube.accounts():
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{a['title']}** · `{a['channel_id']}`")
            if c2.button("Putuskan", key=prefix+"del"+a["id"]):
                try:
                    youtube.disconnect(a["id"], [s.account_id for s in svc.STREAM_INSTANCES.values() if s.running])
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        st.caption("Token disimpan terenkripsi di server. Semua admin yang masuk berbagi Library dan channel; aplikasi ini bukan layanan multi-tenant.")


def channel_select(prefix, required=True):
    channels = youtube.accounts()
    if not channels:
        if required:
            st.caption("Hubungkan channel melalui panel OAuth untuk mengaktifkan unggahan.")
        return None
    options = [a["id"] for a in channels]
    return st.selectbox("Channel YouTube", options, format_func=lambda x: next(a["title"] for a in channels if a["id"] == x), key=prefix+"channel")


def metadata_panel(prefix, defaults=None, live=False):
    defaults = defaults or {}
    fingerprint = hashlib.sha256(json.dumps(defaults, sort_keys=True).encode()).hexdigest()[:12]
    if st.session_state.get(prefix+"meta_version") != fingerprint:
        for field, value in [("title", defaults.get("title", "")), ("description", defaults.get("description", "")),
                             ("tags", ", ".join(defaults.get("tags", []))),
                             ("hashtags", " ".join(defaults.get("hashtags", [] if live else ["#Shorts"])))]:
            st.session_state[prefix+field] = value
        st.session_state[prefix+"meta_version"] = fingerprint
    if not live:
        if st.button("Racik Judul + Deskripsi SEO + Hashtag + Tags · Ollama", key=prefix+"metadata_ai"):
            try:
                with st.spinner("Menyusun metadata berdasarkan konten yang tersedia…"):
                    result = ai.metadata(defaults.get("title") or defaults.get("topic") or "Konten Shorts orisinal",
                                         {"content": defaults}, live=False)
                for field in ("title", "description", "tags", "hashtags"):
                    value = result.get(field, [])
                    st.session_state[prefix+field] = ", ".join(value) if field == "tags" else " ".join(value) if field == "hashtags" else value
                st.rerun()
            except Exception as e:
                st.error(str(e))
        st.caption("Optimasi boleh meningkatkan kejelasan/daya tarik, bukan menjamin CTR, algoritma, atau viral.")
    st.text_input("Judul", max_chars=95 if live else 100, key=prefix+"title")
    st.text_area("Deskripsi", height=140, max_chars=4200, key=prefix+"description")
    c1, c2 = st.columns(2)
    c1.text_input("Hashtag (pisahkan spasi)", key=prefix+"hashtags")
    c2.text_input("Tags (pisahkan koma)", key=prefix+"tags")
    meta = {"title": st.session_state.get(prefix+"title", ""), "description": st.session_state.get(prefix+"description", ""),
            "hashtags": st.session_state.get(prefix+"hashtags", "").split(),
            "tags": [x.strip() for x in st.session_state.get(prefix+"tags", "").split(",") if x.strip()],
            "category_id": str(defaults.get("category_id", "10" if live else "22"))}
    if not live:
        meta["privacy"] = st.selectbox("Privasi unggahan", ["private", "unlisted", "public"], key=prefix+"privacy",
                                     format_func=lambda x: {"private": "Private — rekomendasi", "unlisted": "Tidak publik", "public": "Publik — tayang untuk semua"}[x])
        meta["synthetic"] = st.checkbox("Tandai media sintetis/realistis yang diubah ( disclosure YouTube )", value=True, key=prefix+"synthetic")
        meta["made_for_kids"] = st.checkbox("Konten dibuat khusus untuk anak-anak", value=False, key=prefix+"kids")
    return meta


def upload_controls(prefix, meta, account):
    auto = st.checkbox("Auto-upload setelah render selesai", value=False, key=prefix+"auto")
    consent = st.checkbox("Saya punya hak atas media/musik dan menyetujui unggahan ke channel & privasi yang dipilih.",
                          value=False, key=prefix+"consent")
    if (auto or consent) and (not account or not consent):
        st.warning("Unggahan memerlukan channel dan persetujuan eksplisit.")
    if auto and meta.get("privacy") == "public":
        st.warning("Mode publik dipilih. Pastikan konten, izin, disclosure, dan setelan anak sudah benar.")
    st.caption("Chunk Google 8 MiB; offset tersimpan untuk retry. Proyek API yang belum diaudit dapat dipaksa private oleh YouTube.")
    return {"auto_upload": bool(auto and consent and account), "consent": bool(consent and account),
            "account_id": account, "privacy": meta.get("privacy", "private"),
            "synthetic": meta.get("synthetic", True), "made_for_kids": meta.get("made_for_kids", False)}


def manual_upload(prefix="manual"):
    st.subheader("Kirim / Upload Hasil Shorts")
    channel_manager(prefix)
    account = channel_select(prefix)
    videos = store.assets("results")
    if not videos:
        st.info("Belum ada video dalam Library.")
        return
    lookup = {a["id"]: a for a in videos}
    aid = st.selectbox("Hasil video", list(lookup), format_func=lambda x: lookup[x]["name"], key=prefix+"asset")
    asset = store.asset(aid)
    defaults = store.kv_get("video-meta:" + asset["path"], {"title": Path(asset["name"]).stem, "hashtags": ["#Shorts"]})

    meta = metadata_panel(prefix, defaults)
    confirm = st.checkbox("Konfirmasi hak konten & tujuan upload", key=prefix+"confirm")
    if st.button("Antrekan upload manual", key=prefix+"send", type="primary", disabled=not account):
        if not confirm:
            st.error("Centang konfirmasi hak konten sebelum upload.")
            return
        try:
            job = submit_upload(RUNNER, asset["path"], account, meta, True)
            st.success("Masuk antrean: " + job["id"])
        except Exception as e:
            st.error(str(e))