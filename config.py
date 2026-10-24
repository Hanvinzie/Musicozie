"""Konstanta global Musicozie: path aset, threshold, mapping MIDI & gestur."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = "1.0"

import urllib.request

# --- Aset ---
SOUNDFONT_PATH = ROOT / "TBOSf.sf2"
HAND_MODEL_PATH = ROOT / "models" / "hand_landmarker.task"
DASHBOARD_DIR = ROOT / "dashboard"

GITHUB_SF2_URL = "https://github.com/username/musicozie/releases/download/v1.0.0/TBOSf.sf2"

if not SOUNDFONT_PATH.exists():
    print(f"Downloading {SOUNDFONT_PATH.name} from GitHub Release...")
    try:
        SOUNDFONT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Menambahkan User-Agent agar tidak diblokir oleh GitHub
        req = urllib.request.Request(
            GITHUB_SF2_URL, 
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req) as response, open(SOUNDFONT_PATH, 'wb') as out_file:
            out_file.write(response.read())
        print("SoundFont download completed successfully!")
    except Exception as e:
        print(f"Failed to download SoundFont from GitHub Release: {e}")

# --- Kamera ---
CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
JPEG_QUALITY = 70

# --- Server (loopback saja: tanpa autentikasi, jangan ekspos ke jaringan) ---
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
WS_HZ = 30

# --- Peran tangan (sudut pandang pemain). Tukar kedua nilai ini untuk membalik peran tangan; UI ikut berubah. ---
MELODY_HAND = "right"     # tangan yang membentuk gestur nada C-B
MODIFIER_HAND = "left"    # tangan pemicu Minor Toggle (hanya jempol terbuka)

# --- Logic ---
DEBOUNCE_MS = 100
LOST_GRACE_MS = 150  # tangan hilang sesaat (frame drop MediaPipe) tidak langsung mematikan nada

# --- Vision ---
OPEN_RATIO = 1.25         # jari terbuka bila jarak ujung->wrist > OPEN_RATIO * jarak MCP->wrist
THUMB_TUCK_RATIO = 0.95   # ibu jari TERTUTUP bila d(ujung ibu jari, MCP kelingking) / d(MCP ibu jari, MCP kelingking) < rasio ini
MIN_HAND_SCORE = 0.5

# --- Audio (FluidSynth) ---
AUDIO_DRIVER = "coreaudio"
AUDIO_PERIOD_SIZE = 512  # frame per periode (~11.6 ms @ 44.1 kHz)
AUDIO_PERIODS = 2
SAMPLE_RATE = 44100
GAIN = 0.8
MELODY_CHANNEL = 0
MELODY_VELOCITY = 105

# --- Instrumen. TBOSf.sf2 terverifikasi: bank 0 prog 0 = Grand Piano, bank 0 prog 40 = Violin. ---
DEFAULT_INSTRUMENT = "piano"
PIANO_PROGRAM = 0
VIOLIN_PROGRAM = 40
BANK = 0

# Vibrato biola (LFO pitch bend). Rentang bend diset ke +-2 semitone (RPN).
BEND_RANGE_SEMITONES = 2
VIBRATO_RATE_HZ = 5.5
VIBRATO_DEPTH_CENTS = 20.0
VIBRATO_DELAY_S = 0.15   # nada awal bersih dulu, lalu vibrato masuk
VIBRATO_RAMP_S = 0.25

# Pindah instrumen: kepalan ganda (00000 di kedua tangan) ditahan selama ini
MODE_SWITCH_HOLD_S = 1.5
MODE_SWITCH_DROPOUT_S = 0.2  # kedip deteksi singkat tidak mereset hitungan tahan

# --- Nada C-B (tangga nada C mayor; dulu Do-Re-Mi). Pola 5-bit: (ibu jari, telunjuk, tengah, manis, kelingking), 1 = terbuka ---
# pola -> (nama solfege, MIDI)
SOLFEGE = {
    (1, 0, 0, 0, 0): ("C", 60),
    (1, 1, 0, 0, 0): ("D", 62),
    (1, 1, 1, 0, 0): ("E", 64),
    (1, 1, 1, 1, 0): ("F", 65),
    (1, 1, 1, 1, 1): ("G", 67),
    (0, 1, 1, 1, 1): ("A", 69),
    (0, 1, 1, 1, 0): ("B", 71),
    (0, 1, 1, 0, 0): ("C High", 72),
}
MINOR_SHIFT = -1  # semitone, saat Minor Toggle aktif
# Minor Toggle: tangan KANAN hanya ibu jari terbuka (10000) -> nada tangan kiri turun MINOR_SHIFT semitone
MINOR_TRIGGER = (1, 0, 0, 0, 0)
