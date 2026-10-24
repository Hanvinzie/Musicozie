"""Penerjemah pola 5 jari -> nada C-B, plus Minor Toggle.

Logika murni (tanpa kamera/audio).
Pola 5-bit: (ibu jari, telunjuk, tengah, manis, kelingking), 1 = terbuka.

* Tangan MELODI (`config.MELODY_HAND`, bawaan KANAN) = nada utama (C D E F G A B C-High, tangga nada C mayor).
* Tangan MODIFIER (`config.MODIFIER_HAND`, bawaan KIRI): selama HANYA ibu jari yang terbuka
  (`10000`, `config.MINOR_TRIGGER`), nada turun 1 semitone (minor / flat). Idle atau gestur lain = mayor.
* Kepalan (00000) atau pola tak dikenal di tangan melodi = diam.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Optional, Sequence

import config

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def midi_name(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


@dataclass
class HandState:
    """Status satu tangan hasil vision."""

    side: str  # "left" | "right" (sudut pandang pemain)
    fingers: tuple = (0, 0, 0, 0, 0)  # ibu jari, telunjuk, tengah, manis, kelingking
    landmarks: list = field(default_factory=list)  # [(x, y), ...] ternormalisasi 0..1

    @property
    def code(self) -> str:
        return "".join(str(int(f)) for f in self.fingers)


@dataclass(frozen=True)
class Note:
    solfege: str  # nama nada: "C", "D", ... "B", "C High" (nama field dipertahankan)
    midi: int
    minor: bool = False

    @property
    def name(self) -> str:
        return midi_name(self.midi)

    @property
    def label(self) -> str:
        """Label tampilan HUD, mis. 'Mi♭ (Minor)'."""
        return f"{self.solfege}\u266d (Minor)" if self.minor else self.solfege

    @property
    def label_ascii(self) -> str:
        """Versi ASCII untuk font OpenCV (tanpa simbol bemol)."""
        return f"{self.solfege}b (Minor)" if self.minor else self.solfege


def _bits(fingers: Sequence[int]) -> tuple:
    return tuple(1 if f else 0 for f in fingers)


def resolve_solfege(fingers: Sequence[int]) -> Optional[Note]:
    """Pola 5-bit -> Note mayor, atau None (kepalan / tak dikenal)."""
    hit = config.SOLFEGE.get(_bits(fingers))
    return Note(hit[0], hit[1]) if hit else None


def is_minor_active(modifier: Optional[Sequence[int]]) -> bool:
    """Minor Toggle aktif bila tangan modifier HANYA ibu jari terbuka (10000)."""
    return modifier is not None and _bits(modifier) == tuple(config.MINOR_TRIGGER)


def mode_text(minor_active: bool) -> str:
    """Teks status HUD."""
    return "[MODE: MINOR TOGGLE ACTIVE]" if minor_active else "[MODE: MAJOR]"


def resolve_pair(melody: Optional[Sequence[int]], modifier: Optional[Sequence[int]]) -> Optional[Note]:
    """Gestur tangan melodi (+ tangan modifier, bila ada) -> Note final.

    Tangan melodi menentukan nada; `is_minor_active(modifier)` menurunkannya 1 semitone.
    Tangan melodi tidak ada -> None (tangan modifier saja tidak membunyikan apa pun).
    """
    if melody is None:
        return None
    note = resolve_solfege(melody)
    if note is None:
        return None
    if is_minor_active(modifier):
        return Note(note.solfege, note.midi + config.MINOR_SHIFT, minor=True)
    return note


def resolve_hands(hands: Sequence[HandState]) -> Optional[Note]:
    by_side = {h.side: h for h in hands}
    melody, modifier = by_side.get(config.MELODY_HAND), by_side.get(config.MODIFIER_HAND)
    return resolve_pair(melody.fingers if melody else None, modifier.fingers if modifier else None)


FINGER_NAMES = ("thumb", "index", "middle", "ring", "pinky")


def describe_pattern(fingers: Sequence[int]) -> str:
    """Gesture description for the UI guide (built from the pattern, so it always matches config.SOLFEGE)."""
    bits = _bits(fingers)
    opened = [FINGER_NAMES[i] for i, b in enumerate(bits) if b]
    if not opened:
        return "Fist (all fingers closed)"
    if all(bits):
        return "All 5 fingers open (open palm)"
    text = f"{opened[0].capitalize()} only" if len(opened) == 1 else " + ".join(opened).capitalize()
    return text + ("" if bits[0] else " (thumb closed)")


def solfege_table() -> list:
    """C-B note table (untuk UI): name, midi, note (mayor), code, minor_midi/minor_note, description."""
    rows = []
    for pattern, (name, midi) in sorted(config.SOLFEGE.items(), key=lambda kv: kv[1][1]):
        rows.append({
            "name": name, "midi": midi, "note": midi_name(midi), "code": "".join(map(str, pattern)),
            "minor_midi": midi + config.MINOR_SHIFT, "minor_note": midi_name(midi + config.MINOR_SHIFT),
            "description": describe_pattern(pattern),
        })
    return rows


def _cli(argv: list) -> int:
    if not argv:
        print("pakai: python -m gesture_matrix 11000 [modifier=10000]   (tangan melodi, tangan modifier)")
        return 2
    melody = tuple(int(c) for c in argv[0])
    opts = dict(a.split("=", 1) for a in argv[1:] if "=" in a)
    modifier = tuple(int(c) for c in opts["modifier"]) if "modifier" in opts else None
    n = resolve_pair(melody, modifier)
    print(f"{n.label} -> {n.name} [{n.midi}]" if n else "diam / tidak dikenal")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
