"""Panel Live asli, dengan enam instance StreamManager independen dan OAuth opsional."""
from __future__ import annotations
import json
from pathlib import Path
import streamlit as st
import services as svc
from . import state, ai, media, youtube
from .ui_common import channel_manager


def _mmss(sec):
    sec = int(sec)
    return f"{sec//3600}:{sec%3600//60:02d}:{sec%60:02d}"


@st.cache_data(show_spinner=False)
def _dur(path_str, mtime):
    return svc.media_info(path_str)["dur"]


def _push_vol(stream, slot, layer):
    key = f"l_v{layer}_{slot}"
    if key in st.session_state:
        stream.set_volume(layer, st.session_state[key])


def _metadata(slot, v_rand, a_rand, a_loop, topic, automatic=False):
    prefix = f"live_meta_{slot}_"
    meta = state.kv_get(f"live-meta-{slot}", {}).get("metadata", {})
    title = st.text_input("Judul siaran", meta.get("title", f"Live {slot} · {topic}"), key=prefix+"title", max_chars=95)
    description = st.text_area("Deskripsi", meta.get("description", "Playlist dari Library."), key=prefix+"description", height=120)
    tags = st.text_input("Hashtag", " ".join(meta.get("hashtags", ["#Live", "#Musik"])), key=prefix+"tags")
    result = {"title": title, "description": description, "hashtags": tags.split(), "tags": meta.get("tags", []), "category_id": "10"}
    if st.button("Analisis audio + riset referensi + racik metadata", key=f"live_ai_{slot}"):
        try:
            with st.spinner("ffprobe → PCM → spektrogram → Ollama…"):
                paths = [str(p) for p in (a_rand or a_loop or v_rand)[:3]]
                evidence = media.analyze_audio(paths, state.ANALYSIS/f"live-{slot}") if paths else {"method": "Tidak ada audio", "tracks": []}
                public = json.loads(json.dumps(evidence))
                for t in public.get("tracks", []):
                    t.pop("spectrogram", None)
                research = ai.web_research(topic, "live")
                images = [t["spectrogram"] for t in evidence.get("tracks", []) if Path(t.get("spectrogram", "")).is_file()]
                generated = ai.metadata(topic, {"audio_analysis": public, "research": research}, live=True, images=images)
            state.kv_set(f"live-meta-{slot}", {"metadata": generated, "analysis": evidence, "research": research})
            for field, value in (("title", generated["title"]), ("description", generated["description"]), ("tags", " ".join(generated["hashtags"]))):
                st.session_state[prefix+field] = value
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    saved = state.kv_get(f"live-meta-{slot}", {})
    if saved:
        with st.expander("Bukti analisis & referensi metadata"):
            for track in saved.get("analysis", {}).get("tracks", []):
                if Path(track.get("spectrogram", "")).is_file():
                    st.image(track["spectrogram"], caption="Spektrogram PCM nyata; bukan identifikasi lagu/artis")
            for ref in saved.get("research", {}).get("references", []):
                st.markdown(f"- [{ref.get('title', 'Referensi')}]({ref.get('url', '')})")
            st.caption("Referensi adalah sampel pencarian, bukan jaminan viral. Fitur spektral bukan pengenalan lagu.")
    if automatic and not meta.get("title") and ai.configured():
        result = _generate_metadata(slot, v_rand, a_rand, a_loop, topic)
    return result


def _generate_metadata(slot, v_rand, a_rand, a_loop, topic):
    paths = [str(p) for p in (a_rand or a_loop or v_rand)[:3]]
    evidence = media.analyze_audio(paths, state.ANALYSIS/f"live-{slot}") if paths else {"method": "Tidak ada audio", "tracks": []}
    public = json.loads(json.dumps(evidence))
    for t in public.get("tracks", []):
        t.pop("spectrogram", None)
    research = ai.web_research(topic, "live")
    result = ai.metadata(topic, {"audio_analysis": public, "research": research}, live=True)
    state.kv_set(f"live-meta-{slot}", {"metadata": result, "analysis": evidence, "research": research})
    return result


def render(get_stream, disk_min):
    st.caption("Streaming dari file di Library, satu koneksi yang tidak putus saat ganti video/lagu. "
               "Opening sekali di awal → video acak berulang. Audio RANDOM diputar utuh, independen dari video.")
    channel_manager("live")
    streams = {slot: get_stream(slot) for slot in range(1, 7)}
    cols = st.columns(6)
    for slot, col in enumerate(cols, 1):
        col.metric(f"Slot {slot}", "🔴 Live" if streams[slot].state == "live" else "🛠️ Proses" if streams[slot].running else "⚪ Siap")
    slot = st.selectbox("Slot yang diatur", list(range(1, 7)), format_func=lambda n: f"Slot {n} · {streams[n].state}", key="live_selected_slot")
    stream = streams[slot]
    st.info("Enam slot berjalan independen. Slot lain tetap aktif saat Anda berpindah panel. "
            "Streamlit Cloud tidak menjamin proses 24/7; gunakan VPS untuk siaran panjang.")
    vlib, alib = svc.library_videos(), svc.list_paths("audio")
    k = lambda name: f"{name}_{slot}"
    st.markdown("#### 🎞️ Alur video")
    use_opening = st.checkbox("Putar opening sekali saat live dimulai", value=True, key=k("l_open_on"))
    f1, f2 = st.columns(2)
    v_open = f1.multiselect("1️⃣ Opening (acak jika memilih beberapa)", vlib, format_func=svc.label, key=k("l_open"), disabled=not use_opening)
    v_rand = f2.multiselect("2️⃣ Video acak (diputar penuh dan berulang)", vlib, format_func=svc.label, key=k("l_rand"))
    active_opening = v_open if use_opening else []
    st.caption("Opening boleh kosong. Setelah opening selesai, video acak terus berjalan; opening tidak diulang saat reconnect.")
    st.markdown("#### 🎵 Audio random kontinu")
    a_rand = st.multiselect("🎲 Pilih file audio untuk diputar acak terus-menerus", alib, format_func=svc.label, key=k("l_arand"))
    st.caption("Setiap file diputar sampai selesai. Urutan diacak tanpa pengulangan berurutan; pergantian video tidak mereset lagu.")
    st.markdown("##### 🎚️ Volume (bisa diubah saat live berjalan)")
    h1, h2 = st.columns([3, 1.4])
    h1.slider("Volume audio random", 0.0, 2.0, 1.0, .05, key=k("l_vr"), on_change=_push_vol, args=(stream, slot, "r"))
    h2.button("↩️ Default", key=k("l_vreset"), on_click=lambda s, n: (st.session_state.update({f"l_vr_{n}": 1.0}), s.set_volume("r", 1.0)), args=(stream, slot))
    if v_rand or a_rand:
        st.info(f"Alur: {'Opening ('+str(len(active_opening))+') → ' if active_opening else ''}"
                f"Video acak ({len(v_rand)} file · {_mmss(sum(_dur(str(p), p.stat().st_mtime) for p in v_rand))}) | "
                f"Audio random: {len(a_rand)} file · {_mmss(sum(_dur(str(p), p.stat().st_mtime) for p in a_rand))}")
    st.markdown("#### 📡 Tujuan siaran")
    accounts = youtube.accounts()
    mode = st.radio("Koneksi utama", ["Stream key manual", "YouTube OAuth"], horizontal=True, key=k("l_connect_mode"),
                    disabled=not accounts, help="Hubungkan channel di panel Google OAuth untuk mengaktifkan mode OAuth.")
    account = None
    broadcast = None
    privacy = "private"
    if mode == "YouTube OAuth" and accounts:
        account = st.selectbox("Channel YouTube", [a["id"] for a in accounts], format_func=lambda aid: next(a["title"] for a in accounts if a["id"] == aid), key=k("l_account"))
        privacy = st.selectbox("Privasi siaran", ["private", "unlisted", "public"], key=k("l_privacy"))
        rtmp, skey = "", ""
    else:
        presets = {"RTMP YouTube (standar)": "rtmp://a.rtmp.youtube.com/live2",
                   "RTMPS YouTube (terenkripsi)": "rtmps://a.rtmps.youtube.com:443/live2", "Kustom": ""}
        l0, l1, l2 = st.columns([1.2, 1.2, 1])
        server = l0.selectbox("Server tujuan", list(presets), key=k("l_srv"))
        rtmp = l1.text_input("RTMP URL", presets[server] or "rtmp://", key=k("l_rtmp_"+server), disabled=server != "Kustom")
        skey = l2.text_input("Stream Key", type="password", key=k("l_key"))
    with st.expander("⚙️ Pengaturan lanjutan"):
        vmode = st.radio("Mode video", ["auto", "normalize", "copy"], horizontal=True, key=k("l_vmode"),
                         format_func={"auto": "Otomatis (disarankan)", "normalize": "Selalu samakan", "copy": "Kirim apa adanya"}.get)
        n1, n2, n3 = st.columns(3)
        height = n1.selectbox("Resolusi (jika disamakan)", [480, 720, 1080], index=1, key=k("l_h"))
        fps = n2.selectbox("FPS", [24, 25, 30], index=2, key=k("l_fps"))
        bitrate = n3.selectbox("Bitrate video kbps", [0, 1500, 2500, 4000, 6000], format_func=lambda b: "Auto" if b == 0 else str(b), key=k("l_br"))
        o1, o2 = st.columns(2)
        shuffle = o1.checkbox("Acak video pada tiap pergantian", value=True, key=k("l_shuf"))
        hours = o2.number_input("Batas durasi (jam, 0 = tanpa batas)", 0.0, 720.0, 0.0, 1.0, key=k("l_hours"))
        a_loop = st.multiselect("Audio LOOP tambahan (opsional, bercampur dengan RANDOM)", alib, format_func=svc.label, max_selections=1, key=k("l_aloop"))
        st.slider("Volume audio LOOP", 0.0, 2.0, .6, .05, key=k("l_vl"), on_change=_push_vol, args=(stream, slot, "l"))
        silence = st.checkbox("Izinkan audio hening bila tidak memilih musik", value=False, key=k("l_silence"))
        extra = st.text_area("Tujuan simulcast tambahan · satu URL RTMP(S) lengkap per baris", height=85, key=k("l_extra"),
                             help="Maksimum 3 tujuan tambahan + 1 utama. Stream key tambahan tidak dicetak di log.")
        if st.button("🧹 Hapus cache hasil penyamaan", key=k("l_clrcache"), disabled=any(s.running for s in streams.values())):
            st.toast(f"{svc.clear_live_cache()} file cache dihapus")
    with st.expander("📝 Judul, deskripsi & riset metadata"):
        topic = st.text_input("Topik / nama program", "Musik santai teman belajar", key=k("l_topic"))
        automatic = st.checkbox("Riset + racik otomatis saat start bila belum ada metadata", value=False, key=k("l_auto_meta"))
        meta = _metadata(slot, v_rand, a_rand, a_loop, topic)
    all_v = list(dict.fromkeys([*active_opening, *v_rand]))
    all_a = list(dict.fromkeys([*a_loop, *a_rand]))
    s1, s2 = st.columns(2)
    if s1.button("▶️ Mulai Live", type="primary", disabled=stream.running, key=k("l_start")):
        try:
            if not v_rand:
                raise ValueError("Pilih minimal satu video acak; opening opsional.")
            if not a_rand and not a_loop and not silence:
                raise ValueError("Pilih audio atau aktifkan fallback hening di pengaturan lanjutan.")
            targets = [svc.validate_rtmp(x.strip()) for x in extra.splitlines() if x.strip()]
            if len(targets) > 3:
                raise ValueError("Maksimum tiga tujuan tambahan.")
            if account:
                with st.spinner("Menyiapkan metadata dan broadcast YouTube…"):
                    metadata = dict(meta)
                    if automatic and not state.kv_get(f"live-meta-{slot}", {}).get("metadata", {}).get("title"):
                        metadata = _generate_metadata(slot, v_rand, a_rand, a_loop, topic)
                    if not metadata["title"].strip():
                        raise ValueError("Judul siaran wajib diisi.")
                    metadata["description"] += "\n\n" + " ".join(metadata["hashtags"])
                    broadcast = youtube.create_live(account, metadata, privacy, f"{height}p", fps)
                url = broadcast["url"]
                rtmp, skey = url.rsplit("/", 1)
            else:
                svc.validate_rtmp(rtmp.rstrip("/") + "/" + skey.strip())
                if not skey.strip():
                    raise ValueError("Stream key wajib diisi atau pilih YouTube OAuth.")
            stream.start({"videos": all_v, "audios": all_a, "v_open": active_opening, "v_rand": v_rand,
                          "a_loop": a_loop, "a_rand": a_rand, "vol_rand": st.session_state[k("l_vr")],
                          "vol_loop": st.session_state[k("l_vl")], "rtmp_url": rtmp.strip(), "stream_key": skey.strip(),
                          "vmode": vmode, "height": height, "fps": fps, "vbr_k": bitrate, "shuffle": shuffle,
                          "disk_min_gb": disk_min, "allow_silence": silence, "extra_targets": targets,
                          "account_id": account, "broadcast_id": broadcast["broadcast_id"] if broadcast else None,
                          "stream_id": broadcast["stream_id"] if broadcast else None}, hours)
            st.rerun()
        except Exception as exc:
            if broadcast and account:
                youtube.complete_live(account, broadcast["broadcast_id"])
            st.error(str(exc).replace(skey, "[STREAM_KEY]") if skey else str(exc))
    if s2.button("⏹️ Stop Live", disabled=not stream.running, key=k("l_stop")):
        stream.stop()
        st.rerun()

    @st.fragment(run_every=3)
    def live_status():
        icon = {"live": "🔴 LIVE berjalan", "menyiapkan": "🛠️ Menyiapkan file…", "menghubungkan": "🔌 Menghubungkan…",
                "menyambung ulang": "🔁 Menyambung ulang…", "selesai": "✅ Selesai", "error": "❌ Gagal"}.get(stream.state, "⚪ Tidak streaming")
        (st.success if stream.state == "live" else st.error if stream.state == "error" else st.warning)(icon + (f" — {stream.detail}" if stream.detail else ""))
        a, b, c, d, e = st.columns(5)
        a.metric("Uptime", stream.uptime())
        b.metric("Auto-restart", stream.restarts)
        pr = stream.progress or {}
        c.metric("Kecepatan", pr.get("speed", "-") or "-")
        d.metric("Bitrate", (pr.get("bitrate", "-") or "-").strip())
        e.metric("Kualitas kirim", stream.health if stream.running else "-")
        if stream.running:
            x, y, z = st.columns(3)
            x.metric("Video diputar", (stream.now_video or "-")[:28])
            y.metric("Audio random", (stream.now_audio or "-")[:28])
            z.metric("Pergantian video", stream.switches)
            if stream.prep_info:
                st.caption("🛠️ " + stream.prep_info)
        for note in stream.notes:
            st.caption("• " + note)
        with st.expander("Log ffmpeg · slot " + str(slot)):
            st.code(stream.log_tail() or "(kosong)", language="text")
    live_status()
