"""Menjalankan test JavaScript engine (dashboard/assets/engine.js) dan membuktikan paritasnya dengan modul Python.

Python menghasilkan jawaban acuan dari gesture_matrix / vision_processor / pipeline / instrument_modes asli,
lalu `node --test tests/js` memutar ulang input yang sama lewat port JavaScript. Dilewati bila Node tidak terpasang.
"""
import json
import os
import random
import shutil
import subprocess
from pathlib import Path

import pytest

import config
import vision_processor as vp
from gesture_matrix import HandState, resolve_pair
from instrument_modes import ModeSwitch
from pipeline import GestureLogic

ROOT = Path(__file__).resolve().parent.parent
GESTURES = [tuple(map(int, k)) for k in ("10000", "11000", "11100", "11110", "11111", "01111", "01110", "01100", "00000")]


def _hand_record(side, fingers):
    return [side, list(fingers)]


def _event_dict(e):
    return {k: e[k] for k in sorted(e)}


def make_sequence(rng):
    debounce = rng.choice([0, 50, 100, 100, 300])
    logic = GestureLogic(debounce, config.LOST_GRACE_MS)
    sw = ModeSwitch()
    t, held, fist_hold = 100.0, {}, 0
    steps = []
    for _ in range(400):
        t += rng.choice([0.01, 0.02, 0.033, 0.033, 0.05, 0.12])
        hands = []
        for side in ("left", "right"):
            if rng.random() < 0.12:
                held.pop(side, None)            # tangan hilang beberapa frame
            if side not in held or rng.random() < 0.15:
                held[side] = rng.choice(GESTURES + [tuple(rng.randint(0, 1) for _ in range(5))])
            if rng.random() > 0.1:              # kadang tangan tidak terdeteksi pada frame ini
                hands.append(HandState(side=side, fingers=held[side]))
        if fist_hold == 0 and rng.random() < 0.02:
            fist_hold = rng.randint(25, 70)     # kepalan ganda ditahan ~0,8-2,5 dtk -> menguji ModeSwitch
        if fist_hold > 0:
            fist_hold -= 1
            hands = [HandState("left", (0,) * 5), HandState("right", (0,) * 5)]
            held = {"left": (0,) * 5, "right": (0,) * 5}
            if rng.random() < 0.05:             # sesekali satu tangan hilang sesaat (dropout)
                hands = hands[:1]
        by = {h.side: h for h in hands}
        left, right = by.get("left"), by.get("right")
        switched = sw.update(left.fingers if left else None, right.fingers if right else None, t)
        cmds, events = logic.update(hands, t)
        steps.append({
            "t": t,
            "hands": [_hand_record(h.side, h.fingers) for h in hands],
            "commands": [list(c) for c in cmds],
            "events": [_event_dict(e) for e in events],
            "current": logic.current.label if logic.current else None,
            "minor": logic.minor_active,
            "switched": switched,
            "progress": sw.progress,
        })
    return {"debounce_ms": debounce, "lost_grace_ms": config.LOST_GRACE_MS, "hold_s": sw.hold_s,
            "dropout_s": sw.dropout_s, "steps": steps}


def build_fixture(seed=20261025):
    rng = random.Random(seed)
    landmarks = []
    for _ in range(400):
        lm = [(rng.random(), rng.random()) for _ in range(21)]
        landmarks.append({"lm": lm, "fingers": list(vp.finger_states5(lm)), "thumb_ratio": vp.thumb_ratio(lm)})

    all_codes = [tuple(int(c) for c in format(i, "05b")) for i in range(32)]
    pairs = []
    for m in all_codes:
        for mod in all_codes:
            n = resolve_pair(m, mod)
            pairs.append({"melody": list(m), "modifier": list(mod), "note": [n.solfege, n.midi, n.minor, n.name, n.label] if n else None})
    for m in all_codes:                                   # tangan modifier tidak ada
        n = resolve_pair(m, None)
        pairs.append({"melody": list(m), "modifier": None, "note": [n.solfege, n.midi, n.minor, n.name, n.label] if n else None})
    for mod in all_codes:                                 # tangan melodi tidak ada
        pairs.append({"melody": None, "modifier": list(mod), "note": None})

    import server  # noqa: WPS433  (config API yang sama dengan yang dibaca browser)
    import asyncio
    api_config = asyncio.run(server.get_config())
    return {"landmarks": landmarks, "sequences": [make_sequence(rng) for _ in range(40)], "pairs": pairs, "api_config": api_config}


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js tidak terpasang")
def test_js_engine_unit_and_parity(tmp_path):
    fixture = tmp_path / "parity.json"
    fixture.write_text(json.dumps(build_fixture()))
    files = sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.js"))
    proc = subprocess.run(
        ["node", "--test", *files], cwd=ROOT, env={**os.environ, "PARITY_FIXTURE": str(fixture)},
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
    assert "# skipped 0" in proc.stdout, "test paritas tidak boleh terlewat"