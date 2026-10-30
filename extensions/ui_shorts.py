from __future__ import annotations
from pathlib import Path
import streamlit as st
from . import state as store, ai, media, tts, jobs as creative_jobs
from .config import ANALYSIS
from .ui_common import choose, channel_manager, channel_select, metadata_panel, upload_controls, manual_upload


def poem_mode():
    st.markdown("### Kata yang punya ruang.")
    st.caption("Kartu pita kapital · bait rata tengah · tanda tangan miring kanan bawah · hati vektor · zoompan 9:16.")
    topic = st.text_input("Tema / keresahan", "Tentang pulang ketika dewasa", key="poem_topic")
    signature = st.text_input("Tanda tangan", "ruang miring", max_chars=35, key="poem_signature")
    if st.button("Riset referensi + susun kartu · Ollama Cloud", key="poem_research"):
        try:
            with st.spinner("Mencari referensi terkini lalu menyusun naskah orisinal…"):
                research = ai.web_research(topic, "poem")
                draft = ai.poem(topic, research, signature)
            st.session_state.poem_draft = draft
            st.session_state.poem_lines = "\n".join(draft.get("lines", []))
            st.session_state.poem_ribbon = draft.get("ribbon", "")
        except Exception as e:
            st.error(str(e))
    draft = st.session_state.get("poem_draft")
    if draft:
        st.info(draft.get("ribbon", ""))
        lines = st.text_area("Bait (satu baris per jeda visual)", "\n".join(draft.get("lines", [])), height=180, key="poem_lines")
        draft["lines"] = [x.strip() for x in lines.splitlines() if x.strip()][:5]
        draft["signature"] = signature
        st.text_input("Judul pita kapital", key="poem_ribbon", value=draft.get("ribbon", ""), max_chars=36)
        draft["ribbon"] = st.session_state.poem_ribbon.upper()
        with st.expander("Bukti riset / referensi"):
            for r in draft.get("research", {}).get("references", []):
                views = f" · {r['views']:,} tayangan" if r.get("views") is not None else " · jumlah tayangan tidak tersedia"
                st.markdown(f"- [{r.get('title', 'Referensi')}]({r.get('url', '')}){views}")
            st.caption(draft.get("research", {}).get("disclaimer", "Tidak ada riset yang diklaim bila tombol riset belum digunakan."))
            st.write(draft.get("research_summary", ""))
    else:
        st.info("Klik riset untuk membuat draft, atau antrekan render dengan naskah AI otomatis. OLLAMA_API_KEY diperlukan.")
    images = store.assets("image")
    if not images:
        st.warning("Belum ada latar. Buat gambar Clipdrop atau unggah gambar vertikal di tab Impor.")
        image_id = None
    else:
        lookup = {a["id"]: a for a in images}
        preferred = next((a["id"] for a in images if a["name"].startswith("Clipdrop")), images[0]["id"])
        image_id = st.selectbox("Latar Clipdrop / gambar Library", list(lookup), index=list(lookup).index(preferred),
                                format_func=lambda x: lookup[x]["name"], key="poem_image")
    c1, c2, c3 = st.columns(3)
    effect = c1.selectbox("Partikel", ["rain", "petals", "snow", "embers"], format_func=lambda x: {"rain":"Hujan", "petals":"Kelopak", "snow":"Salju", "embers":"Bara"}[x], key="poem_effect")
    seconds = c2.slider("Durasi (detik)", 5, 60, 15, key="poem_seconds")
    resolution = c3.selectbox("Resolusi", ["720p", "1080p"], key="poem_resolution")
    audio = store.assets("audio")
    music_ids = choose("Pool musik acak (kosong = hening)", audio, "poem_music", [a["id"] for a in audio])
    channel_manager("poem")
    account = channel_select("poem", False)
    with st.expander("Metadata & publikasi", expanded=False):
        meta = metadata_panel("poem", draft or {"topic": topic, "title": topic})
        opts = upload_controls("poem", meta, account)
    if st.button("Render Kartu Shorts → MP4", type="primary", key="poem_render"):
        if not image_id or (not draft and not ai.configured()):
            st.error("Pilih gambar latar dan siapkan draft/Ollama terlebih dahulu.")
            return
        if opts["auto_upload"] and not meta["title"].strip():
            st.error("Auto-upload memerlukan judul.")
            return
        try:
            if draft:
                draft.update({k: meta[k] for k in ("title", "description", "hashtags", "tags")})
            payload = {"image": image_id, "music_pool": music_ids, "topic": topic, "signature": signature,
                       "draft": draft, "effect": effect, "seconds": seconds, "resolution": resolution,
                       "metadata": meta, **opts}
            job = creative_jobs.submit_creative(st.session_state["_creative_runner"], "poem", payload)
            st.success("Job render masuk antrean: " + job["id"])
        except Exception as e:
            st.error(str(e))


def reaction_mode():
    st.markdown("### Klipnya jalan. Warganya komentar.")
    st.caption("Referensi gaya: https://www.youtube.com/shorts/tCDG43O80HA. Gaya reaction umum, bukan salinan identitas/kreator lain.")
    videos = store.assets("results")
    if not videos:
        st.warning("Impor atau unggah klip vertikal terlebih dahulu.")
        return
    lookup = {a["id"]: a for a in videos}
    source = st.selectbox("Klip sumber", list(lookup), format_func=lambda x: lookup[x]["name"], key="reaction_source")
    try:
        max_seconds = min(60, int(media.duration(store.asset_path(source))))
    except Exception:
        max_seconds = 60
    if max_seconds >= 5:
        seconds = st.slider("Panjang hasil (detik)", 5, max_seconds, min(30, max_seconds), key="reaction_seconds")
    else:
        seconds = max(1, max_seconds)
        st.caption(f"Klip pendek: memakai durasi sumber {seconds} detik. Naskah harus cukup pendek; render menolak TTS yang tidak muat.")
    context = st.text_area("Apa yang terjadi di klip? (konteks jujur untuk AI)", "Momen kucing tiba-tiba berhenti ketika melihat mentimun.", key="reaction_context", height=100)
    if st.button("Racik naskah reaksi dari frame + konteks", key="reaction_ai"):
        try:
            from .jobs import extract_frames
            with st.spinner("Ollama membaca sampel frame dan menulis reaksi…"):
                frames = extract_frames(store.asset_path(source), ANALYSIS/"preview-reaction", seconds)
                draft = ai.reaction(context, seconds, images=frames)
            st.session_state.reaction_draft = draft
            st.session_state.reaction_source_saved = source
            st.session_state.reaction_banner = draft.get("banner", "")
            st.session_state.reaction_lines = "\n".join(draft.get("lines", []))
        except Exception as e:
            st.error(str(e))
    draft = st.session_state.get("reaction_draft") if st.session_state.get("reaction_source_saved") == source else None
    if draft:
        draft["banner"] = st.text_input("Banner judul atas", draft.get("banner", ""), max_chars=44, key="reaction_banner")
        text = st.text_area("Narasi / subtitle (satu baris = satu segmen TTS)", "\n".join(draft.get("lines", [])), height=180, key="reaction_lines")
        draft["lines"] = [x.strip() for x in text.splitlines() if x.strip()][:6]
        st.caption("Subtitle otomatis diselaraskan dengan durasi TTS tiap kalimat, bukan transkripsi audio asli. Kecepatan disesuaikan tanpa memotong kalimat.")
    c1, c2, c3 = st.columns(3)
    voice_label = c1.selectbox("Narator TTS", list(tts.VOICES), key="reaction_voice")
    rate = c2.selectbox("Kecepatan suara", ["-10%", "+0%", "+10%"], index=1, key="reaction_rate")
    crop = c3.selectbox("Frame 9:16", ["Crop tengah", "Fit + baris latar"], key="reaction_crop") == "Crop tengah"
    fallback = st.checkbox("Izinkan fallback espeak-ng bila Edge TTS gagal (robot, bukan suara neural)", value=False)
    st.caption("Default TTS: Microsoft Edge id-ID-GadisNeural / ArdiNeural. Memerlukan internet; layanan ini dapat berubah/menolak request.")
    channel_manager("reaction")
    account = channel_select("reaction", False)
    with st.expander("Metadata & publikasi", expanded=False):
        meta = metadata_panel("reaction", draft or {"title": context[:80], "description": context})
        opts = upload_controls("reaction", meta, account)
    if st.button("Render Reaction Shorts → MP4", type="primary", key="reaction_render"):
        if not draft and not ai.configured():
            st.error("Buat draft atau isi OLLAMA_API_KEY untuk naskah otomatis.")
            return
        if opts["auto_upload"] and not meta["title"].strip():
            st.error("Isi judul sebelum auto-upload.")
            return
        try:
            if draft:
                draft.update({k: meta[k] for k in ("title", "description", "hashtags", "tags")})
            payload = {"source": source, "context": context, "seconds": seconds, "draft": draft,
                       "voice": tts.VOICES[voice_label], "rate": rate, "crop": crop, "fallback_tts": fallback,
                       "resolution": "1080p", "metadata": meta, **opts}
            job = creative_jobs.submit_creative(st.session_state["_creative_runner"], "reaction", payload)
            st.success("Job reaction masuk antrean: " + job["id"])
        except Exception as e:
            st.error(str(e))


def render():
    mode = st.radio("Mode Viral Shorts", ["A · Kartu kata / puisi", "B · Reaction Warga +62", "Kirim / Upload hasil"], horizontal=True, key="shorts_mode")
    st.divider()
    if mode.startswith("A"):
        poem_mode()
    elif mode.startswith("B"):
        reaction_mode()
    else:
        manual_upload()