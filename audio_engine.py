"""Wrapper FluidSynth + thread audio (satu suara melodi).

Perintah dikirim lewat queue sebagai tuple:
  ("note_on", midi) | ("note_off",) | ("instrument", "piano"|"violin") | ("all_off",)

Piano  : noteon/noteoff perkusif per gestur.
Biola  : nada ditahan, vibrato halus lewat pitch bend (LFO, dijalankan oleh `tick()` ~100 Hz).
"""
from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import config
from instrument_modes import MODES, vibrato_bend

log = logging.getLogger("musicozie.audio")


class FluidBackend:
    """Backend FluidSynth sungguhan (pyfluidsynth)."""

    def __init__(self, soundfont: Path, driver: str = config.AUDIO_DRIVER):
        import fluidsynth

        if not Path(soundfont).exists():
            raise FileNotFoundError(f"SoundFont tidak ditemukan: {soundfont}")
        self.fs = fluidsynth.Synth(gain=config.GAIN, samplerate=float(config.SAMPLE_RATE))
        self.fs.setting("audio.period-size", config.AUDIO_PERIOD_SIZE)
        self.fs.setting("audio.periods", config.AUDIO_PERIODS)
        self.fs.start(driver=driver)
        self.sfid = self.fs.sfload(str(soundfont))
        if self.sfid < 0:
            raise RuntimeError(f"Gagal memuat SoundFont: {soundfont}")

    def program_select(self, ch: int, bank: int, program: int) -> None:
        self.fs.program_select(ch, self.sfid, bank, program)

    def set_bend_range(self, ch: int, semitones: int) -> None:
        # RPN 0 (pitch bend sensitivity): CC101=0, CC100=0, CC6=semitone, CC38=cent, lalu RPN null
        for ctrl, val in ((101, 0), (100, 0), (6, semitones), (38, 0), (101, 127), (100, 127)):
            self.fs.cc(ch, ctrl, val)

    def pitch_bend(self, ch: int, value: int) -> None:
        self.fs.pitch_bend(ch, value)

    def noteon(self, ch: int, note: int, vel: int) -> None:
        self.fs.noteon(ch, note, vel)

    def noteoff(self, ch: int, note: int) -> None:
        self.fs.noteoff(ch, note)

    def all_notes_off(self, ch: int) -> None:
        self.fs.all_notes_off(ch)

    def close(self) -> None:
        self.fs.delete()


class AudioEngine:
    def __init__(self, backend=None, soundfont: Optional[Path] = None, instrument: str = config.DEFAULT_INSTRUMENT):
        self.backend = backend if backend is not None else FluidBackend(soundfont or config.SOUNDFONT_PATH)
        self._note: Optional[int] = None
        self._onset = 0.0
        self._bend = 0
        self._lock = threading.Lock()
        self.instrument: Optional[str] = None
        self.set_instrument(instrument)

    @property
    def active_note(self) -> Optional[int]:
        return self._note

    def set_instrument(self, name: str) -> None:
        """Ganti program (piano/violin). Nada yang sedang bunyi dimatikan dulu."""
        if name not in MODES:
            log.warning("instrumen tidak dikenal: %r", name)
            return
        with self._lock:
            self._all_off_locked()
            mode = MODES[name]
            ch = config.MELODY_CHANNEL
            self.backend.program_select(ch, mode.bank, mode.program)
            self.backend.set_bend_range(ch, config.BEND_RANGE_SEMITONES)
            self._set_bend(0, force=True)
            self.instrument = name

    def note_on(self, midi: int, now: Optional[float] = None) -> None:
        ch = config.MELODY_CHANNEL
        with self._lock:
            if self._note is not None:  # monofonik: matikan nada lama dulu
                self.backend.noteoff(ch, self._note)
            self._set_bend(0)
            self.backend.noteon(ch, midi, config.MELODY_VELOCITY)
            self._note = midi
            self._onset = time.monotonic() if now is None else now

    def note_off(self) -> None:
        with self._lock:
            if self._note is not None:
                self.backend.noteoff(config.MELODY_CHANNEL, self._note)
                self._note = None
            self._set_bend(0)

    def tick(self, now: Optional[float] = None) -> None:
        """Perbarui vibrato (hanya mode biola & ada nada aktif)."""
        with self._lock:
            if self._note is None or not MODES[self.instrument].vibrato:
                return
            t = (time.monotonic() if now is None else now) - self._onset
            self._set_bend(vibrato_bend(t))

    def _set_bend(self, value: int, force: bool = False) -> None:
        if force or value != self._bend:
            self.backend.pitch_bend(config.MELODY_CHANNEL, value)
            self._bend = value

    def all_notes_off(self) -> None:
        with self._lock:
            self._all_off_locked()

    def _all_off_locked(self) -> None:
        if self._note is not None:
            self.backend.noteoff(config.MELODY_CHANNEL, self._note)
            self._note = None
        self.backend.all_notes_off(config.MELODY_CHANNEL)
        self._set_bend(0)

    def handle(self, cmd: tuple) -> None:
        kind = cmd[0]
        if kind == "note_on":
            self.note_on(cmd[1])
        elif kind == "note_off":
            self.note_off()
        elif kind == "instrument":
            self.set_instrument(cmd[1])
        elif kind == "all_off":
            self.all_notes_off()
        else:
            log.warning("perintah audio tidak dikenal: %r", cmd)

    def stop(self) -> None:
        self.all_notes_off()
        self.backend.close()


class AudioThread(threading.Thread):
    """Thread 3: konsumsi audio_q + jalankan LFO vibrato, tanpa memblokir vision/logic."""

    TICK_S = 0.01

    def __init__(self, engine: AudioEngine, audio_q: "queue.Queue", stop_event: threading.Event):
        super().__init__(name="audio", daemon=True)
        self.engine, self.q, self.stop_event = engine, audio_q, stop_event

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                cmd = self.q.get(timeout=self.TICK_S)
            except queue.Empty:
                cmd = None
            if cmd is not None:
                try:
                    self.engine.handle(cmd)
                except Exception:  # noqa: BLE001
                    log.exception("gagal menangani perintah audio %r", cmd)
            self.engine.tick()
        self.engine.all_notes_off()  # tidak ada nada menggantung


def _demo() -> None:
    eng = AudioEngine()
    scale = sorted(midi for _, midi in config.SOLFEGE.values())
    try:
        for inst in ("piano", "violin"):
            print(f"[{inst}] Do Re Mi Fa Sol La Si Do'")
            eng.set_instrument(inst)
            for m in scale:
                eng.note_on(m)
                end = time.monotonic() + (0.35 if inst == "piano" else 0.7)
                while time.monotonic() < end:  # tick() meniru AudioThread (vibrato)
                    eng.tick()
                    time.sleep(0.01)
                eng.note_off()
            time.sleep(0.3)
    finally:
        eng.stop()


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        print("pakai: python -m audio_engine --demo")
