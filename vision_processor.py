"""Pipeline MediaPipe HandLandmarker + status 5 jari (ibu jari, telunjuk, tengah, manis, kelingking; 1 = terbuka).

Fungsi murni menerima `lm`: list 21 titik (x, y) ternormalisasi.
Frame di-flip horizontal (tampilan selfie) SEBELUM inferensi. Label HandLandmarker diukur terbalik terhadap
tampilan selfie, jadi ditukar di `side_from_label` agar "left" = tangan kiri fisik pemain.
"""
from __future__ import annotations

import math
import sys
import time
from typing import Optional, Sequence

import config
from gesture_matrix import HandState, mode_text

WRIST = 0
# (tip, mcp) untuk telunjuk, tengah, manis, kelingking
FINGER_IDS = ((8, 5), (12, 9), (16, 13), (20, 17))

HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def is_finger_open(lm: Sequence, tip_id: int, mcp_id: int, ratio: float = config.OPEN_RATIO) -> bool:
    """Rumus PRD (jarak Euclidean ke wrist) dengan margin `ratio` agar jari setengah tekuk = tertutup."""
    return _dist(lm[tip_id], lm[WRIST]) > ratio * _dist(lm[mcp_id], lm[WRIST])


def finger_states(lm: Sequence) -> tuple:
    return tuple(int(is_finger_open(lm, t, m)) for t, m in FINGER_IDS)


def thumb_ratio(lm: Sequence) -> float:
    """d(ujung ibu jari, MCP kelingking) / d(MCP ibu jari, MCP kelingking). Kecil = ibu jari menekuk ke telapak."""
    base = _dist(lm[2], lm[17])
    return _dist(lm[4], lm[17]) / base if base > 1e-6 else 1.0


def is_thumb_open(lm: Sequence, ratio: float = config.THUMB_TUCK_RATIO) -> bool:
    """Ibu jari terbuka (menjauh dari telapak) bila rasio >= THUMB_TUCK_RATIO; tertutup bila menekuk ke telapak."""
    return thumb_ratio(lm) >= ratio


def finger_states5(lm: Sequence) -> tuple:
    """(ibu jari, telunjuk, tengah, manis, kelingking), 1 = terbuka."""
    return (int(is_thumb_open(lm)),) + finger_states(lm)


def build_hand_state(side: str, lm: Sequence) -> HandState:
    pts = [(float(p[0]), float(p[1])) for p in lm]
    return HandState(side=side, fingers=finger_states5(pts), landmarks=pts)


def side_from_label(label: str, swap: bool = True) -> str:
    """MediaPipe label -> player's physical hand ("left"/"right").

    Measured on a real webcam: HandLandmarker (Tasks API) reports labels from the camera's point of view, so after
    the selfie flip the label is inverted (label "Left" appears on the image's right = the player's RIGHT hand).
    `swap=True` (default) corrects that. Use swap=False only if a future MediaPipe version returns player-side labels.
    """
    side = label.lower()
    if swap:
        side = "right" if side == "left" else "left"
    return side


def pick_best_per_side(candidates: list) -> list:
    """candidates: [(score, HandState)]. Simpan skor tertinggi per sisi (hindari dua deteksi 'left')."""
    best: dict = {}
    for score, hs in candidates:
        if hs.side not in best or score > best[hs.side][0]:
            best[hs.side] = (score, hs)
    return [hs for _, hs in best.values()]


class VisionProcessor:
    def __init__(self, model_path=config.HAND_MODEL_PATH):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        if not model_path.exists():
            raise FileNotFoundError(f"Hand model not found: {model_path} (re-run the setup steps in the README)")
        self._mp = mp
        opts = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=config.MIN_HAND_SCORE,
            min_tracking_confidence=config.MIN_HAND_SCORE,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(opts)
        self._t0 = time.monotonic()
        self._last_ts = -1

    def process(self, frame_bgr):
        """Return (frame_flipped_bgr, [HandState])."""
        import cv2

        frame = cv2.flip(frame_bgr, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        ts = max(int((time.monotonic() - self._t0) * 1000), self._last_ts + 1)  # harus naik monoton
        self._last_ts = ts
        result = self._landmarker.detect_for_video(image, ts)

        cands = []
        for lms, cats in zip(result.hand_landmarks, result.handedness):
            cat = cats[0]
            side = side_from_label(cat.category_name)
            cands.append((cat.score, build_hand_state(side, [(p.x, p.y) for p in lms])))
        return frame, pick_best_per_side(cands)

    def close(self) -> None:
        self._landmarker.close()


def open_camera(index: int = config.CAMERA_INDEX, width: int = config.FRAME_WIDTH, height: int = config.FRAME_HEIGHT):
    import cv2

    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise RuntimeError(
            f"Camera index {index} could not be opened. On macOS: System Settings > Privacy & Security > "
            "Camera, allow your Terminal/IDE app, then try again."
        )
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def draw_hands(frame, hands: Sequence[HandState]) -> None:
    import cv2

    h, w = frame.shape[:2]
    for hs in hands:
        pts = [(int(x * w), int(y * h)) for x, y in hs.landmarks]
        for a, b in HAND_CONNECTIONS:
            cv2.line(frame, pts[a], pts[b], (255, 255, 255), 1)
        for p in pts:
            cv2.circle(frame, p, 3, (102, 255, 0), -1)
        label = f"{hs.side[0].upper()} {hs.code}"
        cv2.putText(frame, label, (pts[0][0] - 40, min(pts[0][1] + 24, h - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)


def draw_hud(frame, note, mode_label: str, switch_progress: float = 0.0, minor_active: bool = False) -> None:
    """HUD OpenCV: instrumen (PIANO/VIOLIN), status [MODE: MAJOR] / [MODE: MINOR TOGGLE ACTIVE],
    nama nada C-B (mis. 'Eb (Minor)'), dan progres pindah mode.

    `note` = gesture_matrix.Note atau None. Font Hershey hanya ASCII, jadi bemol ditulis 'b' (lihat Note.label_ascii).
    """
    import cv2

    h, w = frame.shape[:2]
    bar_h = 52
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, bar_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    green, white, grey = (102, 255, 0), (255, 255, 255), (160, 160, 160)
    cv2.putText(frame, mode_label, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, green, 2)
    amber = (0, 184, 255)  # BGR
    cv2.putText(frame, mode_text(minor_active), (10 + 14 * len(mode_label) + 14, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                amber if minor_active else white, 1)
    text = note.label_ascii if note else "-"
    cv2.putText(frame, text, (10, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.8, white if note else grey, 2)
    if switch_progress > 0:
        x0 = max(10, w - 190)
        cv2.putText(frame, "Switching mode...", (x0, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.45, white, 1)
        cv2.rectangle(frame, (x0, 30), (w - 10, 40), grey, 1)
        cv2.rectangle(frame, (x0, 30), (x0 + int((w - 10 - x0) * min(1.0, switch_progress)), 40), green, -1)


def _debug() -> int:
    import cv2

    import instrument_modes
    from gesture_matrix import is_minor_active, resolve_hands

    cap, vp = open_camera(), VisionProcessor()
    mode, switch = config.DEFAULT_INSTRUMENT, instrument_modes.ModeSwitch()
    print("Tekan q / ESC untuk keluar. Rasio ibu jari ditampilkan untuk kalibrasi THUMB_TUCK_RATIO.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame, hands = vp.process(frame)
            by = {h.side: h for h in hands}
            left, right = by.get("left"), by.get("right")
            modifier = by.get(config.MODIFIER_HAND)
            if switch.update(left.fingers if left else None, right.fingers if right else None, time.monotonic()):
                mode = instrument_modes.next_mode(mode)
            draw_hands(frame, hands)
            draw_hud(frame, resolve_hands(hands), instrument_modes.MODES[mode].label, switch.progress,
                     is_minor_active(modifier.fingers if modifier else None))
            y = 80
            for hs in hands:
                cv2.putText(frame, f"{hs.side} thumb ratio {thumb_ratio(hs.landmarks):.2f} (buka >= {config.THUMB_TUCK_RATIO})",
                            (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                y += 20
            cv2.imshow("Musicozie vision debug", frame)
            if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                break
    finally:
        cap.release()
        vp.close()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    if "--debug" in sys.argv:
        sys.exit(_debug())
    print("pakai: python -m vision_processor --debug")
