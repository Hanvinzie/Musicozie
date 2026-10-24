"""Pipeline multi-thread: Vision -> Logic -> Audio, plus SharedState untuk dashboard/server.

Thread 1 (Vision) : baca kamera, MediaPipe, encode JPEG  -> frame_q (maxsize=2, drop-old)  
Thread 2 (Logic)  : gesture_matrix + debounce 100 ms     -> audio_q  
Thread 3 (Audio)  : FluidSynth (audio_engine.AudioThread)  
"""  
from __future__ import annotations

import logging  
import queue  
import threading  
import time  
from dataclasses import dataclass  
from typing import Optional

import config  
from gesture_matrix import HandState, Note, is_minor_active, resolve_pair  
from instrument_modes import MODES, ModeSwitch, next_mode

log = logging.getLogger("musicozie.pipeline")

LOST_GRACE_MS = config.LOST_GRACE_MS  
AUDIO_BUFFER_MS = 1000.0 * config.AUDIO_PERIOD_SIZE * config.AUDIO_PERIODS / config.SAMPLE_RATE

RESOLUTIONS = {"640x480": (640, 480), "320x240": (320, 240)}

@dataclass  
class FramePacket:  
    t_capture: float  
    hands: list

# --------------------------------------------------------------------------- Logic
class GestureLogic:  
    def __init__(self, debounce_ms: float = config.DEBOUNCE_MS, lost_grace_ms: float = LOST_GRACE_MS):  
        self.debounce_ms = debounce_ms  
        self.lost_grace_ms = lost_grace_ms  
        self.current: Optional[Note] = None  
        self.minor_active = False  
        self._changed_at = -1e9  
        self._seen: dict = {}  

    def reset(self) -> list:  
        cmds = [("note_off",)] if self.current is not None else []  
        self.current = None  
        self.minor_active = False  
        self._seen.clear()  
        return cmds

    def _effective(self, side: str, hands_by_side: dict, now: float):  
        h = hands_by_side.get(side)  
        if h is not None:  
            self._seen[side] = (tuple(h.fingers), now)  
            return tuple(h.fingers)  
        fingers, t = self._seen.get(side, (None, -1e9))  
        return fingers if (now - t) * 1000 < self.lost_grace_ms else None

    def update(self, hands: list, now: float) -> tuple:  
        by_side = {h.side: h for h in hands}  
        melody = self._effective(config.MELODY_HAND, by_side, now)  
        modifier = self._effective(config.MODIFIER_HAND, by_side, now)  
        self.minor_active = is_minor_active(modifier)  
        desired = resolve_pair(melody, modifier)  
        cmds, events = [], []  
        if desired != self.current and (now - self._changed_at) * 1000 >= self.debounce_ms:  
            self._changed_at = now  
            if self.current is not None:  
                cmds.append(("note_off",))  
            self.current = desired  
            if desired is None:  
                events.append({"kind": "note_off"})  
            else:  
                cmds.append(("note_on", desired.midi))  
                events.append({"kind": "note_on", "name": desired.name, "solfege": desired.solfege,  
                               "midi": desired.midi, "minor": desired.minor, "label": desired.label})  
        return cmds, events

# --------------------------------------------------------------------------- State bersama
def hand_to_dict(h: HandState) -> dict:  
    return {  
        "side": h.side,  
        "fingers": list(h.fingers),  
        "code": h.code,  
        "landmarks": [[round(x, 4), round(y, 4)] for x, y in h.landmarks],  
    }

class SharedState:  
    def __init__(self):  
        self._lock = threading.Lock()  
        self.jpeg: Optional[bytes] = None  
        self.frame_id = 0  
        self.hands: list = []  
        self.note: Optional[Note] = None  
        self.switch_progress = 0.0  
        self.minor_active = False  
        self.instrument = config.DEFAULT_INSTRUMENT  
        self.latency_ms = 0.0  
        self.fps = 0.0  
        self.status = "starting"  
        self.message = ""  
        self.camera_enabled = True  
        self.debounce_ms = config.DEBOUNCE_MS  
        self.resolution = "640x480"  
        self.stop_event = threading.Event()

    def set_frame(self, jpeg: Optional[bytes], hands: list, fps: float) -> None:  
        with self._lock:  
            if jpeg is not None:  
                self.jpeg = jpeg  
                self.frame_id += 1  
            self.hands = hands  
            self.fps = fps

    def clear_frame(self) -> None:  
        with self._lock:  
            self.jpeg = None  
            self.frame_id += 1  
            self.hands = []  
            self.fps = 0.0

    def apply_events(self, events: list, note: Optional[Note], latency_ms: float) -> None:  
        with self._lock:  
            self.note = note  
            if any(e["kind"] == "note_on" for e in events):  
                self.latency_ms = latency_ms if self.latency_ms == 0 else 0.8 * self.latency_ms + 0.2 * latency_ms

    def set_switch_progress(self, value: float) -> None:  
        with self._lock:  
            self.switch_progress = value

    def set_minor_active(self, value: bool) -> None:  
        with self._lock:  
            self.minor_active = bool(value)

    def hud(self) -> tuple:  
        with self._lock:  
            return self.note, MODES[self.instrument].label, self.switch_progress, self.minor_active

    def set_status(self, status: str, message: str = "") -> None:  
        with self._lock:  
            self.status, self.message = status, message

    def configure(self, debounce_ms=None, resolution=None, instrument=None, camera=None) -> None:  
        with self._lock:  
            if instrument in MODES:  
                self.instrument = instrument  
            if debounce_ms is not None:  
                self.debounce_ms = max(0.0, min(1000.0, float(debounce_ms)))  
            if resolution in RESOLUTIONS:  
                self.resolution = resolution  
            if isinstance(camera, bool):  
                self.camera_enabled = camera

    def get_jpeg(self) -> tuple:  
        with self._lock:  
            return self.frame_id, self.jpeg

    def snapshot(self) -> dict:  
        with self._lock:  
            return {  
                "status": self.status,  
                "message": self.message,  
                "camera_enabled": self.camera_enabled,  
                "fps": round(self.fps, 1),  
                "latency_ms": round(self.latency_ms, 1),  
                "debounce_ms": self.debounce_ms,  
                "resolution": self.resolution,  
                "hands": [hand_to_dict(h) for h in self.hands],  
                "instrument": self.instrument,  
                "mode_label": MODES[self.instrument].label,  
                "switch_progress": round(self.switch_progress, 3),  
                "minor_active": self.minor_active,  
                "note": {"name": self.note.name, "solfege": self.note.solfege, "midi": self.note.midi,  
                         "minor": self.note.minor, "label": self.note.label} if self.note else None,  
            }

# --------------------------------------------------------------------------- Threads
def put_drop_old(q: "queue.Queue", item) -> None:  
    while True:  
        try:  
            q.put_nowait(item)  
            return  
        except queue.Full:  
            try:  
                q.get_nowait()  
            except queue.Empty:  
                pass

class VisionThread(threading.Thread):  
    def __init__(self, state: SharedState, frame_q: "queue.Queue", cap=None, want_video: bool = True, camera_index: int = config.CAMERA_INDEX):  
        super().__init__(name="vision", daemon=True)  
        self.state, self.frame_q, self.cap, self.want_video, self.camera_index = state, frame_q, cap, want_video, camera_index

    def run(self) -> None:  
        import cv2  
        from vision_processor import VisionProcessor, draw_hud, open_camera

        cap, proc = self.cap, None  
        try:  
            proc = VisionProcessor()  
        except Exception as e:  
            log.error("Model vision gagal dimuat: %s", e)  
            self.state.set_status("error", str(e))  
            if cap is not None:  
                cap.release()  
            return

        was_enabled = True  
        cur_res, fps, t_prev = None, 0.0, time.monotonic()  
        try:  
            while not self.state.stop_event.is_set():  
                if not self.state.camera_enabled:  
                    if was_enabled:  
                        was_enabled = False  
                        if cap is not None:  
                            cap.release()  
                            cap = None  
                        self.state.clear_frame()  
                        put_drop_old(self.frame_q, FramePacket(time.monotonic(), []))  
                    time.sleep(0.1)  
                    continue  
                if not was_enabled:  
                    was_enabled = True  
                    try:  
                        cap = open_camera(self.camera_index)  
                        cur_res = None  
                        self.state.set_status("ok")  
                    except Exception as e:  
                        log.warning("Kamera lokal tidak tersedia (Cloud/Headless Mode): %s", e)  
                        self.state.set_status("ok", "Running in server mode")  
                if cap is None:  
                    # Di server cloud (cap is None), pertahankan status "ok" tanpa mencoba membaca frame OpenCV lokal
                    if self.state.status != "ok":
                        self.state.set_status("ok")
                    time.sleep(0.1)  
                    continue

                res = self.state.resolution  
                if res != cur_res:  
                    w, h = RESOLUTIONS[res]  
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)  
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)  
                    cur_res = res  
                ok, frame = cap.read()  
                if not ok:  
                    put_drop_old(self.frame_q, FramePacket(time.monotonic(), []))  
                    time.sleep(0.1)  
                    continue  
                if self.state.status != "ok":  
                    self.state.set_status("ok")  
                t_cap = time.monotonic()  
                frame, hands = proc.process(frame)  
                jpeg = None  
                if self.want_video:  
                    note, mode_label, progress, minor = self.state.hud()  
                    draw_hud(frame, note, mode_label, progress, minor)  
                    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, config.JPEG_QUALITY])  
                    jpeg = buf.tobytes() if ok else None  
                put_drop_old(self.frame_q, FramePacket(t_cap, hands))  
                now = time.monotonic()  
                inst = 1.0 / max(now - t_prev, 1e-6)  
                fps = 0.9 * fps + 0.1 * inst if fps else inst  
                t_prev = now  
                self.state.set_frame(jpeg, hands, fps)  
        finally:  
            if cap is not None:  
                cap.release()  
            if proc is not None:
                proc.close()

class LogicThread(threading.Thread):  
    def __init__(self, state: SharedState, frame_q: "queue.Queue", audio_q: "queue.Queue"):  
        super().__init__(name="logic", daemon=True)  
        self.state, self.frame_q, self.audio_q = state, frame_q, audio_q  
        self.logic = GestureLogic(state.debounce_ms)  
        self.switch = ModeSwitch()  
        self._instrument = state.instrument

    def run(self) -> None:  
        while not self.state.stop_event.is_set():  
            try:  
                pkt = self.frame_q.get(timeout=0.05)  
            except queue.Empty:  
                continue  
            self.step(pkt, time.monotonic())  
        for cmd in self.logic.reset():  
            self.audio_q.put(cmd)  
        self.audio_q.put(("all_off",))

    def step(self, pkt: FramePacket, now: float) -> None:  
        if not self.state.camera_enabled:  
            for cmd in self.logic.reset():  
                self.audio_q.put(cmd)  
            self.switch.update(None, None, now)  
            self.state.set_switch_progress(0.0)  
            self.state.set_minor_active(False)  
            self.state.apply_events([], None, 0.0)  
            return  
        by_side = {h.side: h for h in pkt.hands}  
        left, right = by_side.get("left"), by_side.get("right")  
        if self.switch.update(left.fingers if left else None, right.fingers if right else None, now):  
            self.state.configure(instrument=next_mode(self.state.instrument))  
        self.state.set_switch_progress(self.switch.progress)

        if self.state.instrument != self._instrument:  
            self._instrument = self.state.instrument  
            self.audio_q.put(("instrument", self._instrument))  
            for cmd in self.logic.reset():  
                self.audio_q.put(cmd)  
            self.state.apply_events([], None, 0.0)  
        self.logic.debounce_ms = self.state.debounce_ms  
        cmds, events = self.logic.update(pkt.hands, now)  
        for cmd in cmds:  
            self.audio_q.put(cmd)  
        latency = (time.monotonic() - pkt.t_capture) * 1000 + AUDIO_BUFFER_MS  
        self.state.apply_events(events, self.logic.current, latency)  
        self.state.set_minor_active(self.logic.minor_active)

def start_pipeline(state: SharedState, camera_index: int = config.CAMERA_INDEX, want_video: bool = True, soundfont=None, require_camera: bool = False):  
    from audio_engine import AudioEngine, AudioThread  
    from vision_processor import open_camera

    cap = None  
    try:  
        cap = open_camera(camera_index)  
        state.set_status("ok")  
    except Exception as e:  
        if require_camera:  
            raise  
        log.warning("Kamera fisik tidak tersedia (Cloud/Server mode): %s", e)  
        # Tetap set status ke "ok" di mode server
        state.set_status("ok")

    frame_q: queue.Queue = queue.Queue(maxsize=2)  
    audio_q: queue.Queue = queue.Queue()  
    engine = AudioEngine(soundfont=soundfont, instrument=state.instrument)  
    threads = [  
        AudioThread(engine, audio_q, state.stop_event),  
        LogicThread(state, frame_q, audio_q),  
        VisionThread(state, frame_q, cap, want_video, camera_index),  
    ]  
    for t in threads:  
        t.start()  
    return threads, engine