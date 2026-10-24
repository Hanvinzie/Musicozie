"""Mode instrumen (Piano <-> Biola): definisi mode, LFO vibrato biola, dan pemindah mode kepalan ganda.

* Piano  : MIDI program 0, nada perkusif - noteon saat gestur terbentuk, noteoff saat dilepas.
* Biola  : MIDI program 40, nada ditahan (sustain) dengan vibrato halus lewat pitch bend.
Pemetaan gestur (nada C-B) identik di kedua mode.

Pindah mode: kepalan ganda (00000 di tangan kiri DAN kanan) ditahan `MODE_SWITCH_HOLD_S` (1,5 dtk).
Pemindah hanya aktif lagi setelah kepalan dilepas (tidak berulang selama kepalan tetap ditahan).
Catatan: gestur "silang pergelangan (X)" dari spesifikasi belum diimplementasi; hanya kepalan ganda.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import config


@dataclass(frozen=True)
class InstrumentMode:
    key: str
    label: str
    program: int
    bank: int
    sustained: bool  # True: nada ditahan terus + vibrato; False: nada perkusif
    vibrato: bool


MODES = {
    "piano": InstrumentMode("piano", "PIANO", config.PIANO_PROGRAM, config.BANK, sustained=False, vibrato=False),
    "violin": InstrumentMode("violin", "VIOLIN", config.VIOLIN_PROGRAM, config.BANK, sustained=True, vibrato=True),
}
ORDER = ("piano", "violin")


def next_mode(key: str) -> str:
    """piano -> violin -> piano."""
    return ORDER[(ORDER.index(key) + 1) % len(ORDER)]


def bend_units_per_cent() -> float:
    """Unit pitch bend (14-bit, tengah 0, +-8192) per cent, untuk rentang bend +-BEND_RANGE_SEMITONES."""
    return 8192.0 / (config.BEND_RANGE_SEMITONES * 100.0)


def vibrato_bend(elapsed_s: float) -> int:
    """Nilai pitch bend (-8192..8191, 0 = netral) untuk vibrato `elapsed_s` detik setelah nada dimulai.

    Selama VIBRATO_DELAY_S nada bersih; lalu kedalaman naik halus (VIBRATO_RAMP_S) ke VIBRATO_DEPTH_CENTS.
    """
    if elapsed_s <= config.VIBRATO_DELAY_S:
        return 0
    depth = min(1.0, (elapsed_s - config.VIBRATO_DELAY_S) / config.VIBRATO_RAMP_S)
    cents = config.VIBRATO_DEPTH_CENTS * depth * math.sin(2 * math.pi * config.VIBRATO_RATE_HZ * (elapsed_s - config.VIBRATO_DELAY_S))
    return max(-8192, min(8191, int(round(cents * bend_units_per_cent()))))


class ModeSwitch:
    """Deteksi kepalan ganda yang ditahan. `update()` mengembalikan True tepat sekali saat tahanan tercapai."""

    def __init__(self, hold_s: float = config.MODE_SWITCH_HOLD_S, dropout_s: float = config.MODE_SWITCH_DROPOUT_S):
        self.hold_s, self.dropout_s = hold_s, dropout_s
        self._start: Optional[float] = None
        self._last_ok = -1e9
        self._armed = True
        self._now = 0.0

    @staticmethod
    def is_double_fist(left: Optional[Sequence[int]], right: Optional[Sequence[int]]) -> bool:
        return left is not None and right is not None and not any(left) and not any(right)

    @property
    def progress(self) -> float:
        """0..1 kemajuan tahanan (untuk HUD)."""
        if self._start is None:
            return 0.0
        return max(0.0, min(1.0, (self._now - self._start) / self.hold_s))

    def update(self, left: Optional[Sequence[int]], right: Optional[Sequence[int]], now: float) -> bool:
        self._now = now
        if self.is_double_fist(left, right):
            self._last_ok = now
            if self._armed and self._start is None:
                self._start = now
        elif now - self._last_ok > self.dropout_s:  # dilepas cukup lama -> reset & siap lagi
            self._start = None
            self._armed = True
        if self._armed and self._start is not None and now - self._start >= self.hold_s:
            self._armed = False
            self._start = None
            return True
        return False
