# Studio Render & Live — revisi dari source asli

Folder ini berangkat dari **app.py, services.py, mediatools.py, dan uploader.py asli** yang Anda unggah. Tampilan tetap terang; Library, impor Google Drive/yt-dlp, uploader port 8502/cloudflared, normalisasi, live, dan Job asli tetap dipakai. Bukan aplikasi tujuh-tab gelap dari revisi sebelumnya.

## Isi utama

- `app.py`: antarmuka asli + Clipdrop → Video + Viral Shorts + OAuth + enam slot live.
- `services.py`: engine asli yang diperluas; JobRunner bersama, StreamManager per slot, cache/copy, PCM audio, tee.
- `mediatools.py`: normalisasi audio/video asli; ditambah lock file agar tidak dipakai bersamaan dengan render/live/hapus.
- `uploader.py`: uploader resumable asli; validasi token/ukuran/path, lanjut bagian, dan konfigurasi URL publik.
- `extensions/`: fitur tambahan yang memakai Library dan antrean asli, bukan menyimpan media di Library kedua.
- `tests/`: pengujian lokal, termasuk audio final, enam slot, OAuth/resumable, dan UI AppTest.
- `relay/`: relay OAuth untuk `https://redirect1x.streamlit.app`.

`render.py` dan `marge.py` disebut oleh beberapa fungsi legacy dalam source asli, tetapi **tidak ikut diunggah**. File itu tidak dibuat-buat. Fungsi legacy tersebut tidak dipakai oleh alur Clipdrop/Shorts baru; render baru memakai `extensions/render.py` dan antrean asli. Jika Anda masih memakai fungsi legacy itu di tempat lain, sertakan modul aslinya secara terpisah.

## Jalankan lokal

Python 3.11–3.13 disarankan. FFmpeg **dan** ffprobe wajib tersedia.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run_local.py
```

Buka `http://localhost:8501`. Uploader asli berjalan pada port 8502 saat diperlukan. Data default berada di `<folder ini>/data`; ZIP tidak menyertakan runtime/media/rahasia dari sesi pengujian.

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg espeak-ng libcairo2 fonts-dejavu-core
```

CairoSVG dipakai untuk signature/vektor. Font DejaVu disertakan beserta lisensinya. `espeak-ng` adalah fallback TTS lokal; suara online Edge TTS adalah pilihan lain, bukan suara kloning artis tertentu.

## Streamlit Community Cloud

1. Unggah isi folder ini ke repositori Anda; entrypoint `app.py`.
2. `requirements.txt` dan `packages.txt` sudah berada di root.
3. Isi Secrets dari `.streamlit/secrets.example.toml`. Jangan commit `secrets.toml` sungguhan.
4. Untuk deployment publik dengan OAuth/API, isi `APP_PASSWORD`. Aplikasi menolak akses publik tanpa password bila OAuth atau API dikonfigurasi. `ALLOW_PUBLIC_ACCESS=true` hanya untuk uji sandbox/lokal yang memang sengaja terbuka.
5. Storage Cloud bersifat sementara dan app dapat tidur/restart. Download hasil penting; **Cloud bukan host yang dijamin untuk encoder 24/7**. Gunakan VPS untuk siaran panjang dan enam encoder sekaligus.

YouTube impor memakai Deno/EJS. Installer `scripts/install_deno.py` mengunduh binary resmi Linux x64 yang dipin versi dan diverifikasi SHA-256; ini bukan paket Python `deno`. Pada arsitektur lain, pasang Deno ≥2.3 sendiri.

```bash
python scripts/install_deno.py
```

## Alur kerja

### Library / Impor / Job asli

- Cari, pilih, preview, download, pindahkan, dan hapus file dengan konfirmasi serta perlindungan file yang sedang dipakai.
- Impor Google Drive/yt-dlp tetap tersedia, termasuk cookies Netscape opsional. Cookie tidak dipersistenkan; kotak cookie ditutup setelah antrean selesai.
- Uploader port 8502 menerima bagian dan dapat dilanjutkan setelah terputus. Bagian diverifikasi hash, ukuran, nama aman, dan token. Jangan bagikan URL/token uploader kepada publik.
- Untuk upload lewat tunnel asli, set `UPLOAD_PUBLIC_URL` ke URL cloudflared port 8502 bila diperlukan. URL tunnel dapat berubah setelah restart.
- Antrean unduh dan render memakai worker asli. Job ber-cookie tidak di-retry otomatis setelah cookie dibersihkan; kirim ulang impor dengan cookie baru agar tidak diam-diam mengunduh tanpa autentikasi. Job tanpa cleanup rahasia tetap dapat dicoba ulang.

### Clipdrop → Video

Ketik prompt dan API key, pilih hujan/kelopak/salju/bara serta musik Library. Satu request gambar berbayar/berkuota dibuat, lalu FFmpeg merender MP4 lokal. Gambar masuk Thumbnail; MP4 masuk Hasil.

Key dikirim dari form melalui query URL satu kali, dikonsumsi backend, lalu parameter URL dan input dibersihkan. Key tidak dimasukkan ke job, session state, database, atau disk aplikasi. **Batas nyata:** URL dapat terlihat oleh browser/proxy/riwayat infrastruktur, dan penghapusan menyeluruh dari RAM tidak dapat dijamin. Gunakan HTTPS dan key yang dapat dicabut; jangan memakai URL berisi key untuk dibagikan.

### Viral Shorts

- Quote card: ribbon atas, ayat/puisi rata tengah, signature italic dan vektor hati, zoompan, partikel, musik Library.
- Reaction: video vertikal dari sumber milik Anda/berizin, banner, subtitle, voice-over Indonesia, ducking musik. Contoh referensi `tCDG43O80HA`; aplikasi tidak menyalin/mengklaim video orang lain.
- Metadata hanya dari analisis media nyata dan sampel riset web. Spektrum audio bukan identifikasi lagu/artis. Tidak ada jaminan viral atau monetisasi.
- Upload hanya setelah consent eksplisit. Auto-upload diantrekan terpisah setelah render selesai, memakai token channel yang dipilih.

### Normalisasi & Tes asli

Alur loudness/AAC, uji keseragaman H.264, simpan file baru atau ganti file asli tetap tersedia. Penggantian in-place dilakukan setelah validasi dan memakai file sementara; file aktif dilindungi lock.

### Live 24 Jam

Enam StreamManager independen (`slot 1–6`). Tiap slot dapat memiliki opening sekali, video acak utuh, audio RANDOM utuh yang tidak dipotong saat video berganti, LOOP opsional secara simultan, fallback hening, cache/transcode, dan reconnect. Pengaturan disimpan per slot.

- Manual RTMP atau OAuth YouTube.
- Simulcast FFmpeg `tee`: satu encode, sampai empat target tambahan, maksimal lima tujuan. Kegagalan satu slave tidak menghentikan slave lain; lihat log.
- Enam slot berarti sampai enam encoder: kebutuhan CPU/RAM/bandwidth bertambah besar. Tidak ada klaim sudah lolos uji beban 24 jam.

## OAuth YouTube dan relay

Redirect URI aplikasi dan Google Cloud harus sama persis:

```text
https://redirect1x.streamlit.app
```

Deploy `relay/app.py` pada host tersebut dan isi `RELAY_SECRET` yang sama dengan aplikasi utama. Relay menampilkan URL callback sekali pakai untuk disalin ke sesi Studio asal; state dan PKCE terikat pada sesi tersebut. Relay tidak menukar kode atau meneruskan token secara otomatis. Relay tidak menyimpan token YouTube. Jika relay tidak tersedia, gunakan fallback URL callback manual di expander OAuth.

OAuth client perlu `client_id`, `client_secret`, dan redirect tersebut. Proyek API Google yang belum diaudit dapat memaksa hasil upload tetap private. Itu kebijakan YouTube, bukan kegagalan yang boleh dipalsukan menjadi public.

Upload memakai Google resumable protocol dengan chunk **8 MiB**; aplikasi dapat menanyakan offset untuk melanjutkan sesi yang masih berlaku. Live API membuat/mengikat broadcast lalu menunggu ingest aktif sebelum transisi. Kuota, hak channel, pembatasan konten, dan kebijakan platform tetap berlaku.

## Ollama

Model cloud: `gemma4:31b`; model lokal dapat diatur sendiri. API memakai Bearer key dari Secrets/env, bukan hardcoded. Riset web memakai API Ollama yang tersedia pada akun Anda. Jika web search tidak tersedia/kuota habis, aplikasi tidak boleh mengarang referensi.

```toml
OLLAMA_API_KEY = "..."
OLLAMA_HOST = "https://ollama.com"
OLLAMA_MODEL = "gemma4:31b"
```

## Pemeriksaan

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q app.py services.py mediatools.py uploader.py extensions scripts relay run_local.py tests
```

Lihat `TEST_REPORT.md` untuk cakupan dan batas pengujian. Tidak ada kredensial produksi Clipdrop/Ollama/YouTube yang dipakai untuk mengklaim sukses end-to-end. Uji RTMP lokal, render media, audio terencode, AppTest, dan browser ringan sudah dilakukan; deployment Cloud, beban enam encoder 24 jam, serta akun produksi tetap perlu diverifikasi di lingkungan Anda.

GitHub push **tidak dilakukan** dari sesi ini. ZIP adalah hasil kerja yang benar-benar tersedia untuk diunduh.
