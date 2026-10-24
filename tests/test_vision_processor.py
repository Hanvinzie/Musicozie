import numpy as np
import pytest

import vision_processor as vp
from gesture_matrix import resolve_hands, resolve_pair

# Tangan tegak sintetis: wrist (0.5, 0.9), skala tangan = 0.32
MCP = {5: (0.42, 0.60), 9: (0.50, 0.58), 13: (0.58, 0.60), 17: (0.65, 0.64)}
TIPS = {8: 5, 12: 9, 16: 13, 20: 17}  # tip -> mcp


def make_hand(fingers=(0, 0, 0, 0, 0)):
    """fingers = (ibu jari, telunjuk, tengah, manis, kelingking); 1 = terbuka."""
    lm = {0: (0.5, 0.9)}
    lm.update(MCP)
    for k, (tip, mcp) in enumerate(TIPS.items()):
        mx, my = MCP[mcp]
        tip_y = my - 0.24 if fingers[k + 1] else my + 0.05
        for j in (1, 2, 3):  # mcp+1..+3 = ruas jari; tip = mcp+3
            lm[mcp + j] = (mx, my + (tip_y - my) * j / 3)
    lm[1], lm[2], lm[3] = (0.42, 0.82), (0.36, 0.74), (0.31, 0.68)
    lm[4] = (0.27, 0.62) if fingers[0] else (0.54, 0.72)  # terbuka: menjauh; tertutup: menekuk ke telapak
    return [lm[i] for i in range(21)]


def b(s):
    return tuple(int(c) for c in s)


def test_fist_all_closed():
    assert vp.finger_states5(make_hand(b("00000"))) == b("00000")


def test_open_palm():
    assert vp.finger_states5(make_hand(b("11111"))) == b("11111")


@pytest.mark.parametrize("code", ["10000", "11000", "11100", "11110", "11111", "01111", "01110", "01100"])
def test_all_solfege_patterns_roundtrip(code):
    assert vp.finger_states5(make_hand(b(code))) == b(code)


def test_scale_invariant():
    lm = make_hand(b("11100"))
    far = [(0.5 + (x - 0.5) * 0.4, 0.5 + (y - 0.5) * 0.4) for x, y in lm]  # tangan lebih jauh/kecil
    assert vp.finger_states5(far) == b("11100")


def test_thumb_open_vs_closed():
    assert vp.is_thumb_open(make_hand(b("10000")))
    assert not vp.is_thumb_open(make_hand(b("01111")))
    assert vp.thumb_ratio(make_hand(b("10000"))) > vp.thumb_ratio(make_hand(b("00000")))


def test_thumb_threshold_is_configurable():
    lm = make_hand(b("10000"))
    r = vp.thumb_ratio(lm)
    assert vp.is_thumb_open(lm, ratio=r - 0.01) and not vp.is_thumb_open(lm, ratio=r + 0.01)


def test_build_hand_state_end_to_end():
    hs = vp.build_hand_state("right", make_hand(b("11000")))
    assert hs.code == "11000" and hs.side == "right" and len(hs.landmarks) == 21
    assert resolve_hands([hs]).solfege == "D"


def test_fist_end_to_end_is_silent():
    hs = vp.build_hand_state("right", make_hand(b("00000")))
    assert hs.code == "00000" and resolve_hands([hs]) is None


def test_right_thumb_only_is_minor_toggle_end_to_end():
    melody = vp.build_hand_state("right", make_hand(b("11100")))
    modifier = vp.build_hand_state("left", make_hand(b("10000")))
    n = resolve_pair(melody.fingers, modifier.fingers)
    assert n.minor and n.midi == 63
    assert resolve_hands([melody, modifier]).midi == 63
    other = vp.build_hand_state("left", make_hand(b("11100")))
    assert not resolve_pair(melody.fingers, other.fingers).minor


def test_handedness_mapping_is_swapped_for_selfie_view():
    # terukur di webcam nyata: label "Left" muncul di sisi kanan gambar (tangan KANAN pemain)
    assert vp.side_from_label("Left") == "right"
    assert vp.side_from_label("Right") == "left"
    assert vp.side_from_label("Left", swap=False) == "left"
    assert vp.side_from_label("Right", swap=False) == "right"


def test_pick_best_per_side():
    a = vp.build_hand_state("left", make_hand(b("10000")))
    c = vp.build_hand_state("left", make_hand(b("11000")))
    d = vp.build_hand_state("right", make_hand(b("11000")))
    out = vp.pick_best_per_side([(0.6, a), (0.9, c), (0.8, d)])
    assert {h.side for h in out} == {"left", "right"}
    assert [h for h in out if h.side == "left"][0] is c


def test_hud_draws_without_error_and_changes_pixels():
    from gesture_matrix import resolve_pair as rp

    frame = np.zeros((480, 640, 3), np.uint8)
    vp.draw_hud(frame, rp(b("11100"), b("10000")), "VIOLIN", 0.5, True)
    assert frame.any()
    major = np.zeros((480, 640, 3), np.uint8)
    vp.draw_hud(major, rp(b("11100"), None), "VIOLIN", 0.5, False)
    assert (frame != major).any()  # status MINOR vs MAJOR terlihat berbeda
    blank = np.zeros((480, 640, 3), np.uint8)
    vp.draw_hud(blank, None, "PIANO", 0.0)  # tanpa nada & tanpa progres
    assert blank.any()


def test_processor_loads_model_and_handles_blank_frame():
    proc = vp.VisionProcessor()
    try:
        frame, hands = proc.process(np.zeros((480, 640, 3), np.uint8))
        assert frame.shape == (480, 640, 3) and hands == []
        proc.process(np.zeros((480, 640, 3), np.uint8))  # timestamp tetap monoton
    finally:
        proc.close()
