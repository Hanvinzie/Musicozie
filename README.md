# Musicozie

Instrumen virtual real-time yang dimainkan dengan gestur jari (buka/tutup) lewat webcam.
Tangan kiri memainkan tangga nada C-B (C D E F G A B C-High) dari pola 5 jari; tangan kanan hanya jempol terbuka = Minor Toggle
(turun 1 semitone). Instrumen Piano atau Biola. Suara dari FluidSynth (`TBOSf.sf2`),
dashboard web lokal untuk memantau kamera, skeleton tangan, gestur, dan nada.

## Setup (macOS)

Butuh Python 3.11 atau 3.12 (wheel MediaPipe belum ada untuk 3.13+).

```bash
brew install fluid-synth
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
# model tangan MediaPipe (sudah ada di models/ bila repo ini lengkap)
mkdir -p models && curl -L -o models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
.venv/bin/python check_env.py --camera     # verifikasi semuanya
```

Izin kamera: System Settings > Privacy & Security > Camera, aktifkan untuk Terminal/IDE yang dipakai.
Saat pertama dijalankan macOS menampilkan dialog izin; jalankan ulang setelah mengizinkan.

## Menjalankan

```bash
.venv/bin/python main.py                  # pipeline + dashboard di http://127.0.0.1:8000
.venv/bin/python main.py --headless       # tanpa dashboard (log status tiap 2 dtk)
.venv/bin/python main.py --camera 1 --port 8080 --soundfont path/lain.sf2
.venv/bin/python -m audio_engine --demo   # tes suara
.venv/bin/python -m vision_processor --debug   # jendela OpenCV: skeleton + bit jari
.venv/bin/python -m gesture_matrix 11100 kanan=10000   # -> E♭ (Minor) -> D#4 [63]
```

Tekan Ctrl+C untuk berhenti (semua nada dimatikan dan FluidSynth ditutup).

## Gestur

Pola 5-bit: **ibu jari, telunjuk, tengah, manis, kelingking** (1 = terbuka). Tangan **kiri** menentukan nada;
tangan **kanan** adalah modifier minor. Pemetaan identik di mode Piano dan Biola.

| Nada | Oktaf | MIDI | Pola | Gestur |
| --- | --- | --- | --- | --- |
| C | C4 | 60 | `10000` | hanya jempol |
| D | D4 | 62 | `11000` | jempol + telunjuk |
| E | E4 | 64 | `11100` | jempol + telunjuk + tengah |
| F | F4 | 65 | `11110` | jempol + telunjuk + tengah + manis |
| G | G4 | 67 | `11111` | telapak terbuka penuh |
| A | A4 | 69 | `01111` | 4 jari terbuka, jempol tertutup |
| B | B4 | 71 | `01110` | telunjuk + tengah + manis |
| C High | C5 | 72 | `01100` | telunjuk + tengah |

Kepalan (`00000`) atau pola lain = diam. Tangan kanan saja (tanpa tangan kiri) = diam.

### Minor Toggle (tangan kanan)

Selama gestur 5-bit **tangan kanan persis `10000`** (hanya ibu jari terbuka), semua nada tangan kiri turun 1 semitone (MIDI -1):

| C | D | E | F | G | A | B | C High |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 59 (B3) | 61 (C#4) | 63 (D#4) | 64 (E4) | 66 (F#4) | 68 (G#4) | 70 (A#4) | 71 (B4) |

Tangan kanan idle atau gestur lain (termasuk gestur yang sama dengan kiri) = mayor. Lepas jempol = kembali mayor.
HUD OpenCV menampilkan `[MODE: MAJOR]` atau `[MODE: MINOR TOGGLE ACTIVE]`, dan nada mis. `E♭ (Minor)`.
Hanya nada tunggal yang diturunkan; arpeggio/akor dari spesifikasi **belum diimplementasi**.

### Mode instrumen

- **Piano**: MIDI program 0, perkusif (noteon saat gestur terbentuk, noteoff saat dilepas).
- **Biola**: MIDI program 40, nada ditahan dengan vibrato halus (LFO pitch bend ±20 cent, 5,5 Hz, masuk setelah 0,15 dtk).
- **Pindah mode**: kepalan di **kedua tangan** (`00000` + `00000`) ditahan **1,5 detik**; bar progres tampil di HUD.
  Setelah pindah, kepalan harus dilepas dulu sebelum bisa memindah lagi. Atau klik tombol Piano/Biola di dashboard.
  Gestur silang pergelangan (X) dari spesifikasi **belum diimplementasi**.

Debounce 100 ms (cooldown: perubahan pertama langsung dibunyikan, perubahan berikutnya ditahan 100 ms), jadi saat
mengangkat jempol kanan nada mayor bisa terdengar sekejap sebelum turun (status HUD berubah langsung). Tangan yang hilang kurang dari 150 ms tidak mematikan nada.

Kalibrasi: deteksi ibu jari memakai `THUMB_TUCK_RATIO` di `config.py`; jalankan `python -m vision_processor --debug`
untuk melihat rasionya secara live dan sesuaikan bila jempol sering salah terbaca. Semua ambang belum diuji dengan tangan nyata.

Server mengirim header keamanan di semua respons (CSP ketat tanpa `unsafe-inline`, `nosniff`, `X-Frame-Options: DENY`,
`no-referrer`), aset statis di-revalidasi (ETag), dan `GET /healthz` tersedia untuk pemeriksaan kesehatan. WebSocket otomatis
memakai `wss://` bila halaman dibuka lewat HTTPS dan menyambung ulang dengan backoff bila terputus.

**Catatan deploy:** kamera dan suara diproses oleh proses Python di komputer yang menjalankannya, jadi aplikasi ini
dirancang untuk berjalan lokal. Server tanpa autentikasi dan hanya bind ke `127.0.0.1`; mengeksposnya ke jaringan/internet
(reverse proxy, `0.0.0.0`) akan membuka video kamera Anda. Jika perlu diakses jarak jauh, tambahkan autentikasi + HTTPS di depannya
dan longgarkan pemeriksaan Host/Origin di `server.py` secara sadar.

## Arsitektur

Thread Vision (kamera + MediaPipe HandLandmarker) -> `queue(2)` buang-frame-lama -> thread Logic
(`gesture_matrix` + Minor Toggle + debounce + `instrument_modes.ModeSwitch`) -> `audio_q` -> thread Audio
(FluidSynth, `coreaudio`, period-size 512, 2 periode; satu channel melodi, program piano/biola dari `TBOSf.sf2`, tick vibrato 100 Hz).
Thread Server (FastAPI/uvicorn) melayani `/`, `/video` (MJPEG), `/ws` (state ~30 Hz, config, sim).

## Latensi

Buffer audio 512 frame x 2 periode ~= 23 ms @ 44,1 kHz (jalur audio saja). Angka "LATENSI" di dashboard =
waktu capture -> perintah audio + estimasi buffer audio; belum termasuk latensi sensor webcam (~33 ms/frame @ 30 fps).
Dengan kamera, dashboard menampilkan sekitar 50-60 ms pada mesin pengembang (capture -> perintah audio + estimasi buffer);
latensi total tergantung webcam dan beban CPU - ukur sendiri di dashboard.

## Keamanan

Server TIDAK memakai autentikasi dan menyiarkan video kamera. Karena itu bind dikunci ke `127.0.0.1`
(jangan diubah ke `0.0.0.0`), dan header `Host`/`Origin` diperiksa agar halaman web lain tidak bisa
membaca stream atau mengontrol instrumen dari browser Anda.

## Tes

```bash
.venv/bin/pytest -q
```
