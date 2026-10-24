"""Konstanta global Musicozie: path aset, threshold, mapping MIDI & gestur."""  
import os  
from pathlib import Path  
import requests

ROOT = Path(__file__).resolve().parent  
VERSION = "1.0"

# --- Path Aset ---  
SOUNDFONT_PATH = ROOT / "TBOSf.sf2"  
HAND_MODEL_PATH = ROOT / "models" / "hand_landmarker.task"  
DASHBOARD_DIR = ROOT / "dashboard"

# URL Direct GitHub Release  
GITHUB_SF2_URL = "https://github.com/Hanvinzie/Musicozie/releases/download/v1.0.0/TBOSf.sf2"

def ensure_soundfont():  
    """Memastikan file SoundFont ada; unduh dari GitHub Release jika belum ada."""  
    if not SOUNDFONT_PATH.exists():  
        print(f"Downloading {SOUNDFONT_PATH.name} from GitHub Release...")  
        try:  
            SOUNDFONT_PATH.parent.mkdir(parents=True, exist_ok=True)  
            headers = {"User-Agent": "Mozilla/5.0"}  
            
            response = requests.get(  
                GITHUB_SF2_URL,  
                headers=headers,  
                stream=True,  
                allow_redirects=True,  
                timeout=30  
            )  
            response.raise_for_status()

            with open(SOUNDFONT_PATH, "wb") as out_file:  
                for chunk in response.iter_content(chunk_size=1024 * 1024):  # 1MB per chunk  
                    if chunk:  
                        out_file.write(chunk)  
            print("SoundFont download completed successfully!")  
            
        except Exception as e:  
            print(f"CRITICAL: Failed to download SoundFont: {e}")  
            if SOUNDFONT_PATH.exists():  
                SOUNDFONT_PATH.unlink()  
            raise RuntimeError(f"Required asset {SOUNDFONT_PATH.name} could not be downloaded.") from e

# Jalankan pengecekan saat module config dimuat  
ensure_soundfont()

# --- Kamera ---  
CAMERA_INDEX = 0  
FRAME_WIDTH = 640  
FRAME_HEIGHT = 480  
JPEG_QUALITY = 70

# --- Server Configuration ---  
# Gunakan port & host dari environment variable agar kompatibel dengan Render
PORT = int(os.environ.get("PORT", 8000))  
HOST = os.environ.get("HOST", "0.0.0.0")  
SERVER_HOST = HOST  
SERVER_PORT = PORT  
WS_HZ = 30  

# --- Peran tangan (sudut pandang pemain) ---  
MELODY_HAND = "right"     # tangan yang membentuk gestur nada C-B  
MODIFIER_HAND = "left"    # tangan pemicu Minor Toggle (hanya jempol terbuka)  

# --- Logic ---  
DEBOUNCE_MS = 100  
LOST_GRACE_MS = 150  # frame drop MediaPipe  

# --- Vision ---  
OPEN_RATIO = 1.25  
THUMB_TUCK_RATIO = 0.95  
MIN_HAND_SCORE = 0.5  

# --- Audio (FluidSynth) ---  
AUDIO_DRIVER = "coreaudio"  
AUDIO_PERIOD_SIZE = 512  
AUDIO_PERIODS = 2  
SAMPLE_RATE = 44100  
GAIN = 0.8  
MELODY_CHANNEL = 0  
MELODY_VELOCITY = 105  

# --- Instrumen ---  
DEFAULT_INSTRUMENT = "piano"  
PIANO_PROGRAM = 0  
VIOLIN_PROGRAM = 40  
BANK = 0  

# Vibrato biola  
BEND_RANGE_SEMITONES = 2  
VIBRATO_RATE_HZ = 5.5  
VIBRATO_DEPTH_CENTS = 20.0  
VIBRATO_DELAY_S = 0.15  
VIBRATO_RAMP_S = 0.25  

# Pindah instrumen  
MODE_SWITCH_HOLD_S = 1.5  
MODE_SWITCH_DROPOUT_S = 0.2  

# --- Nada C-B ---  
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
MINOR_SHIFT = -1  
MINOR_TRIGGER = (1, 0, 0, 0, 0)