"""Deploy this SEPARATE app to the redirect hostname you control.
It never exchanges codes for tokens and never asks for a client secret.
"""
from urllib.parse import urlparse, urlencode
import streamlit as st

st.set_page_config(page_title="OAuth Relay · liveoprek2", page_icon="↗")
st.title("Kembali ke Studio")
st.caption("Relay ini menampilkan callback sekali pakai. Jangan bagikan URL atau kode kepada siapa pun.")
q = st.query_params
if q.get("error"):
    st.error("Izin Google ditolak.")
elif q.get("code") and q.get("state"):
    callback = str(st.secrets.get("REDIRECT_URI", "https://redirect1x.streamlit.app")).rstrip("/")+"/?"+urlencode({"code":q["code"],"state":q["state"],"scope":q.get("scope","")})
    st.success("Salin URL di bawah, lalu tempel di panel OAuth pada sesi Studio yang memulai koneksi.")
    st.code(callback, language=None)
    target = str(st.secrets.get("STUDIO_URL", "")).rstrip("/")
    p = urlparse(target)
    if p.scheme == "https" and p.hostname:
        st.link_button("Buka Studio", target)
        st.caption("Jika tombol membuka sesi browser baru, jangan selesaikan OAuth di sana. Tempel callback ke sesi asal: state terikat pada sesi tersebut.")
    else:
        st.info("Administrator relay perlu mengisi STUDIO_URL pada Secrets.")
else:
    st.info("Belum ada callback. Mulai koneksi channel dari aplikasi Studio.")
st.caption("Kode berlaku singkat dan hanya dapat ditukar dengan PKCE verifier dari sesi asal. Relay tidak menyimpan token.")