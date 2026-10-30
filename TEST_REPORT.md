# Laporan validasi — revisi source asli

Tanggal pemeriksaan: 30 Oktober 2026. Lingkungan sandbox Linux, Python 3.13, Streamlit 1.66.1, FFmpeg 7.1.5, yt-dlp 2026.10.26, Deno v2.9.8.

## Hasil yang benar-benar dijalankan

| Pemeriksaan | Hasil |
|---|---|
| `python -m pytest -q` pada revisi aktif final | **28 passed**, 102.79 detik |
| `python -m compileall -q app.py services.py mediatools.py uploader.py extensions scripts relay run_local.py tests` | PASS |
| `python -m pip check` | No broken requirements found |
| Syntax JavaScript inline uploader (`node --check`) | PASS |
| Streamlit AppTest: tab, tema, password, query hygiene, Shorts, enam slot, start live manual | PASS |
| Browser Chromium headless, preferensi gelap OS/browser | Aplikasi tetap putih/terang; sidebar terang; nol page error |
| Health app `8501/_stcore/health` | `ok` |
| Uploader companion `8502/ping` | `{"ok": true}` |
| Form Clipdrop dengan key uji tidak valid | Query key dibersihkan dari URL, input kosong, key tidak muncul di teks halaman; request provider tidak diklaim sukses |
| Enam proses encoder live nyata bersamaan | PASS; enam output H.264 ber-audio, slot independen |
| RTMP lokal nyata ke dua penerima melalui FFmpeg tee | PASS; kedua FLV memiliki video dan audio |

## Cakupan tes otomatis

- Library: pindah/hapus dan perlindungan file aktif.
- Job asli: progres, lock, retry aman, cancel antrean; job ber-cookie tidak di-retry setelah rahasia dibersihkan.
- Normalisasi asli: AAC, sample rate, loudness, replace-in-place setelah verifikasi.
- Live: opening sekali, random bag, isolasi enam slot, redaksi stream key, validasi RTMP, perintah tee.
- Audio final terencode: LOOP 440 Hz + RANDOM 1000 Hz sama-sama terdengar; RANDOM saja; fallback hening tetap memiliki stream audio.
- Render: partikel, quote card, reaction, subtitle/TTS, verifikasi output, auto-upload ber-consent.
- YouTube: OAuth state/PKCE, token terenkripsi, resumable 8 MiB dan lanjut offset.
- Uploader lokal: auth, resume bagian, hash/ukuran/path, file kosong, tampilan terang.
- Impor: cookie JSON/Netscape, URL, Deno ditemukan, opsi runtime eksplisit yt-dlp.
- Ollama: prompt berbasis riset, model `gemma4:31b`, query live bukan query Shorts-only, tidak mengarang jumlah views.
- Clipdrop: key tidak masuk payload job/state dan referensi dibersihkan.

## Belum diverifikasi / batas operasional

- Tidak ada upload produksi ke akun YouTube, request Clipdrop berbayar yang sukses, atau inferensi Ollama Cloud dengan kredensial produksi dalam sesi ini. Tes memakai mock/kredensial uji dan media lokal.
- Tidak ada uji beban 24 jam, enam encoder pada VPS produksi, reconnect jaringan panjang, atau deployment Streamlit Cloud milik user.
- Cloudflared tunnel dan alur browser uploader besar belum diuji end-to-end pada deployment publik; protokol/server lokal dan tes resume sudah diperiksa.
- Relay `https://redirect1x.streamlit.app` harus dideploy/dikendalikan user; paket menyertakan kode relay, bukan mengklaim domain sudah diperbarui.
- Normalisasi asli belum cancel kooperatif di tengah subprocess. Cancel kooperatif tersedia untuk render/upload baru.
- `render.py`/`marge.py` legacy tidak disertakan karena memang tidak ada pada unggahan; tidak dibuat palsu.
- Query URL Clipdrop adalah batas desain yang diminta, bukan jaminan penghapusan forensik dari proxy/riwayat/RAM.
- GitHub push tidak dilakukan. ZIP dan manifest adalah artefak yang benar-benar dihasilkan.

Angka historis 14/25 tes dari tahap sebelumnya tidak dipakai sebagai validasi final; laporan ini memakai hasil **28 tes** pada revisi aktif.
