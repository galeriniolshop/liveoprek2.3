# Perubahan dari source asli yang diunggah

Baseline: `app.py`, `services.py`, `mediatools.py`, `uploader.py` dari folder uploads. Referensi asli disimpan terpisah dan tidak diubah. Rekonstruksi tujuh-tab gelap sebelumnya tidak dipakai sebagai basis.

## Dipertahankan

- Tema terang dan judul Studio Render & Live.
- Lima tab asli: Library, Impor, Normalisasi & Tes, Live 24 Jam, Job.
- Library tunggal berbasis folder `data/`; pencarian, pilihan, preview, download, pindah, hapus dengan perlindungan file aktif.
- Impor Google Drive file/folder dan yt-dlp; cookie JSON/Netscape opsional; uploader resumable port 8502 dan tunnel cloudflared opsional.
- Normalisasi/test audio loudness/AAC dan video H.264, termasuk file baru atau replace-in-place setelah verifikasi.
- JobRunner asli sebagai antrean bersama, monitoring disk, opening sekali, video acak utuh, audio RANDOM utuh, LOOP+RANDOM, cache/copy/transcode, reconnect.

## Ditambahkan

- Tab Clipdrop → Video: satu request gambar, key sekali pakai dari query URL, empat efek partikel, musik Library, render MP4.
- Tab Viral Shorts: quote card dan reaction vertikal; Ollama `gemma4:31b`, TTS Indonesia, subtitle, ducking/banner, metadata berbasis bukti, upload manual/auto dengan consent.
- OAuth multi-channel melalui redirect `https://redirect1x.streamlit.app`, PKCE/state terikat browser, token terenkripsi, relay manual-copy dan fallback callback.
- Google resumable upload 8 MiB dengan penyimpanan sesi/offset; chunk uploader lokal diverifikasi hash dan dapat dilanjutkan.
- StreamManager asli menjadi enam instance slot independen, konfigurasi/log/cache-part per slot, fallback hening, manual RTMP atau OAuth, FFmpeg tee sampai empat target tambahan.
- Riset Ollama khusus live tidak dipaksa menjadi query Shorts; metadata tidak mengklaim hasil identifikasi lagu dari spektrogram.
- Lock file lintas job/normalisasi/live; cancel kooperatif untuk render/upload baru; retry tidak memakai ulang CookieBox yang sudah dibersihkan.
- Deno resmi terpin/terverifikasi checksum dan diteruskan eksplisit ke yt-dlp/EJS.
- Tema light eksplisit, contoh Secrets, launcher lokal, relay, tes, dan laporan validasi.

## Perbaikan penting

- Key Clipdrop tidak masuk session state/job/disk; query dibersihkan dan error tidak mengecho body provider. Referensi key dihapus setelah request, tetapi penghapusan forensik RAM/proxy tidak diklaim.
- Kunci enkripsi lokal dibuat otomatis bila `APP_SECRET` tidak diisi; deployment publik dengan OAuth/API tetap meminta `APP_PASSWORD`.
- RTMP divalidasi, stream key disamarkan dari log, timeout/error tee ditangani; tag H.264/Annex-B disesuaikan pada batas tee FLV.
- Enam slot tidak saling mengganti konfigurasi; cache part memakai nama slot agar tidak bertabrakan.
- Uploader menolak path berbahaya, file kosong, token/ukuran/hash salah; respons memakai nosniff.
- Syarat durasi audio berbasis crossfade lama tidak dipakai lagi karena live baru memutar track utuh tanpa crossfade.

## Batas yang tetap jujur

- `render.py` dan `marge.py` tidak ada dalam unggahan asli. Fungsi legacy yang mengimpornya tidak dihidupkan kembali dengan modul palsu; render baru memakai `extensions/render.py`.
- Normalisasi asli belum memiliki cancel kooperatif di tengah subprocess; pembatalan job baru berlaku pada alur render/upload baru.
- Streamlit Cloud bukan host encoder 24/7. Enam slot membutuhkan VPS yang memadai; tidak ada klaim uji beban 24 jam.
- Tidak ada push GitHub dari sesi ini; tidak ada kredensial produksi yang dibagikan atau diminta di chat.
