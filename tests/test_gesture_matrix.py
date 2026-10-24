import pytest

import config
from gesture_matrix import HandState, midi_name, resolve_hands, resolve_pair, resolve_solfege

TABLE = [
    ("10000", "C", 60, "C4"),
    ("11000", "D", 62, "D4"),
    ("11100", "E", 64, "E4"),
    ("11110", "F", 65, "F4"),
    ("11111", "G", 67, "G4"),
    ("01111", "A", 69, "A4"),
    ("01110", "B", 71, "B4"),
    ("01100", "C High", 72, "C5"),
]


def bits(s):
    return tuple(int(c) for c in s)


@pytest.mark.parametrize("code,solfege,midi,name", TABLE)
def test_solfege_table_exact(code, solfege, midi, name):
    n = resolve_solfege(bits(code))
    assert (n.solfege, n.midi, n.name, n.minor) == (solfege, midi, name, False)


def test_all_patterns_unique():
    assert len(config.SOLFEGE) == 8


def test_fist_and_unknown_are_silent():
    assert resolve_solfege(bits("00000")) is None
    for code in ("00001", "00100", "10100", "01000", "00110", "10001", "01010"):
        assert resolve_solfege(bits(code)) is None


THUMB = bits("10000")


def test_right_hand_absent_or_other_gesture_stays_major():
    assert resolve_pair(bits("11000"), None).midi == 62
    for other in ("11100", "00000", "11111", "01000", "11000", "00001", "01111"):
        n = resolve_pair(bits("11000"), bits(other))
        assert n.midi == 62 and not n.minor, other


def test_right_hand_same_gesture_is_NOT_minor_anymore():
    # aturan lama (Minor Sync = gestur sama) sudah dihapus
    assert not resolve_pair(bits("11100"), bits("11100")).minor
    assert resolve_pair(bits("11100"), bits("11100")).midi == 64


@pytest.mark.parametrize("code,solfege,midi,name", TABLE)
def test_right_thumb_only_flattens_one_semitone(code, solfege, midi, name):
    n = resolve_pair(bits(code), THUMB)
    assert n.minor and n.midi == midi - 1 and n.solfege == solfege


@pytest.mark.parametrize(
    "code,expected_midi",
    [("10000", 59), ("11000", 61), ("11100", 63), ("11110", 64), ("11111", 66), ("01111", 68), ("01110", 70), ("01100", 71)],
)
def test_minor_table_matches_spec_midi(code, expected_midi):
    assert resolve_pair(bits(code), THUMB).midi == expected_midi


def test_minor_names():
    assert resolve_pair(bits("10000"), THUMB).name == "B3"
    assert resolve_pair(bits("11000"), THUMB).name == "C#4"
    assert resolve_pair(bits("11100"), THUMB).name == "D#4"
    assert resolve_pair(bits("01100"), THUMB).name == "B4"


def test_is_minor_active_only_for_thumb_only():
    from gesture_matrix import is_minor_active

    assert is_minor_active(THUMB) and is_minor_active([1, 0, 0, 0, 0]) and is_minor_active((True, False, 0, 0, 0))
    assert not is_minor_active(None) and not is_minor_active(bits("00000"))
    for other in ("11000", "10001", "01000", "11111", "00001"):
        assert not is_minor_active(bits(other))


def test_mode_text():
    from gesture_matrix import mode_text

    assert mode_text(False) == "[MODE: MAJOR]"
    assert mode_text(True) == "[MODE: MINOR TOGGLE ACTIVE]"


def test_minor_with_fist_or_unknown_left_is_silent():
    assert resolve_pair(bits("00000"), THUMB) is None
    assert resolve_pair(bits("00100"), THUMB) is None


def test_left_absent_is_silent_even_if_right_thumb():
    assert resolve_pair(None, THUMB) is None


def test_labels():
    assert resolve_pair(bits("11100"), None).label == "E"
    assert resolve_pair(bits("11100"), THUMB).label == "E\u266d (Minor)"
    assert resolve_pair(bits("11100"), THUMB).label_ascii == "Eb (Minor)"


def test_resolve_hands_uses_sides():
    # peran bawaan: KANAN = melodi, KIRI = modifier minor (jempol saja)
    assert config.MELODY_HAND == "right" and config.MODIFIER_HAND == "left"
    hands = [HandState("left", THUMB), HandState("right", bits("11000"))]
    n = resolve_hands(hands)
    assert n.minor and n.midi == 61
    assert resolve_hands([HandState("left", THUMB)]) is None  # modifier saja tidak berbunyi
    assert resolve_hands([HandState("right", bits("11000"))]).midi == 62
    # kiri BUKAN tangan melodi: kiri 11000 tidak mengubah nada; kanan jempol saja = C mayor (bukan minor)
    n2 = resolve_hands([HandState("left", bits("11000")), HandState("right", THUMB)])
    assert n2.midi == 60 and not n2.minor


def test_roles_can_be_swapped_via_config(monkeypatch):
    monkeypatch.setattr(config, "MELODY_HAND", "left")
    monkeypatch.setattr(config, "MODIFIER_HAND", "right")
    n = resolve_hands([HandState("left", bits("11000")), HandState("right", THUMB)])
    assert n.minor and n.midi == 61
    assert resolve_hands([HandState("right", bits("11000"))]) is None


def test_midi_name():
    assert midi_name(60) == "C4" and midi_name(59) == "B3" and midi_name(72) == "C5"


def test_describe_pattern():
    from gesture_matrix import describe_pattern

    assert describe_pattern(bits("10000")) == "Thumb only"
    assert describe_pattern(bits("01000")) == "Index only (thumb closed)"
    assert describe_pattern(bits("11000")) == "Thumb + index"
    assert describe_pattern(bits("11111")) == "All 5 fingers open (open palm)"
    assert describe_pattern(bits("01111")) == "Index + middle + ring + pinky (thumb closed)"
    assert describe_pattern(bits("00000")).startswith("Fist")
