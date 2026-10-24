"""Verifikasi lingkungan Musicozie: import, SoundFont, FluidSynth, kamera (opsional)."""
import struct
import sys

import config

OK, FAIL = "\u2713", "\u2717"
failed = False


def report(ok: bool, msg: str) -> None:
    global failed
    failed |= not ok
    print(f" {OK if ok else FAIL} {msg}")


def soundfont_presets(path):
    """Baca daftar preset (bank, program, nama) dari chunk 'phdr' SF2."""
    data = path.read_bytes()
    i = data.find(b"phdr")
    size = struct.unpack("<I", data[i + 4 : i + 8])[0]
    out = []
    for k in range(0, size - 38, 38):  # record terakhir = terminator
        rec = data[i + 8 + k : i + 8 + k + 38]
        prog, bank = struct.unpack("<HH", rec[20:24])
        out.append((bank, prog, rec[:20].split(b"\0")[0].decode("latin1")))
    return out


def main(check_camera: bool) -> int:
    print(f"Python {sys.version.split()[0]}")
    report((3, 11) <= sys.version_info[:2] <= (3, 12), "Python 3.11/3.12 (wheel MediaPipe)")

    for mod in ("cv2", "mediapipe", "numpy", "fastapi", "uvicorn", "fluidsynth"):
        try:
            m = __import__(mod)
            report(True, f"import {mod} {getattr(m, '__version__', '')}")
        except Exception as e:  # noqa: BLE001
            report(False, f"import {mod}: {e}")

    report(config.HAND_MODEL_PATH.exists(), f"model tangan: {config.HAND_MODEL_PATH.name}")

    if config.SOUNDFONT_PATH.exists():
        presets = {(b, p): n for b, p, n in soundfont_presets(config.SOUNDFONT_PATH)}
        from instrument_modes import MODES

        for key, mode in MODES.items():
            found = presets.get((mode.bank, mode.program))
            report(found is not None, f"preset {key} bank{mode.bank}/prog{mode.program}: {found}")
    else:
        report(False, f"SoundFont tidak ditemukan: {config.SOUNDFONT_PATH}")

    try:
        import fluidsynth

        fs = fluidsynth.Synth(samplerate=float(config.SAMPLE_RATE))
        fs.setting("audio.period-size", config.AUDIO_PERIOD_SIZE)
        fs.start(driver=config.AUDIO_DRIVER)
        fs.delete()
        report(True, f"FluidSynth driver {config.AUDIO_DRIVER} (period {config.AUDIO_PERIOD_SIZE})")
    except Exception as e:  # noqa: BLE001
        report(False, f"FluidSynth: {e}")

    if check_camera:
        import cv2

        cap = cv2.VideoCapture(config.CAMERA_INDEX)
        ok, _ = cap.read() if cap.isOpened() else (False, None)
        cap.release()
        report(ok, f"kamera index {config.CAMERA_INDEX} (izinkan akses kamera untuk Terminal di macOS)")
    else:
        print(" - kamera dilewati (pakai --camera untuk menguji)")

    print("\nSEMUA OK" if not failed else "\nADA MASALAH")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main("--camera" in sys.argv))
