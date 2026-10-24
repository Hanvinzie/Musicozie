import queue
import threading
import time

import config
from audio_engine import AudioEngine, AudioThread
from gesture_matrix import HandState
from pipeline import FramePacket, GestureLogic, LogicThread, SharedState, put_drop_old
from tests.test_audio_engine import FakeBackend, active


def M(code):
    """Tangan MELODI (config.MELODY_HAND)."""
    return HandState(config.MELODY_HAND, tuple(int(c) for c in code))


def X(code):
    """Tangan MODIFIER minor (config.MODIFIER_HAND)."""
    return HandState(config.MODIFIER_HAND, tuple(int(c) for c in code))


def L(code):
    return HandState("left", tuple(int(c) for c in code))


def R(code):
    return HandState("right", tuple(int(c) for c in code))


def run(logic, hands, t):
    return logic.update(hands, t)


def test_first_change_is_immediate_do():
    g = GestureLogic(debounce_ms=100)
    cmds, ev = run(g, [M("10000")], 0.0)
    assert cmds == [("note_on", 60)]
    assert ev[0]["solfege"] == "C" and ev[0]["minor"] is False and ev[0]["label"] == "C"


def test_right_hand_idle_or_other_gesture_stays_major():
    for other in ("00000", "11100", "11000", "01000"):
        g = GestureLogic()
        cmds, ev = run(g, [M("11000"), X(other)], 0.0)
        assert cmds == [("note_on", 62)] and g.minor_active is False, other


def test_right_hand_alone_is_silent():
    g = GestureLogic()
    assert run(g, [X("11000")], 0.0) == ([], [])


def test_right_thumb_only_flattens_note():
    g = GestureLogic()
    cmds, ev = run(g, [M("11100"), X("10000")], 0.0)
    assert cmds == [("note_on", 63)] and g.minor_active is True
    assert ev[0]["minor"] and ev[0]["label"] == "E\u266d (Minor)" and ev[0]["name"] == "D#4"


def test_same_gesture_on_both_hands_is_not_minor():
    g = GestureLogic()
    assert run(g, [M("11100"), X("11100")], 0.0)[0] == [("note_on", 64)]


def test_minor_toggle_engage_and_release_retriggers_after_cooldown():
    g = GestureLogic(debounce_ms=100)
    assert run(g, [M("11000"), X("00000")], 0.0)[0] == [("note_on", 62)]
    assert run(g, [M("11000"), X("10000")], 0.05)[0] == []  # masih cooldown
    assert g.minor_active  # status HUD langsung berubah
    assert run(g, [M("11000"), X("10000")], 0.12)[0] == [("note_off",), ("note_on", 61)]
    assert run(g, [M("11000"), X("00000")], 0.30)[0] == [("note_off",), ("note_on", 62)]
    assert not g.minor_active


def test_minor_active_flag_even_without_left_note():
    g = GestureLogic()
    run(g, [M("00000"), X("10000")], 0.0)
    assert g.minor_active and g.current is None


def test_fist_releases_note():
    g = GestureLogic(debounce_ms=100)
    run(g, [M("10000")], 0.0)
    assert run(g, [M("00000")], 0.2)[0] == [("note_off",)]


def test_two_fists_silent():
    g = GestureLogic()
    assert run(g, [M("00000"), X("00000")], 0.0) == ([], [])


def test_unknown_pattern_releases():
    g = GestureLogic(debounce_ms=100)
    run(g, [M("10000")], 0.0)
    assert run(g, [M("00100")], 0.5)[0] == [("note_off",)]


def test_cooldown_blocks_flicker_then_applies_pending():
    g = GestureLogic(debounce_ms=100)
    run(g, [M("10000")], 0.0)
    assert run(g, [M("11000")], 0.05)[0] == []
    assert run(g, [M("11000")], 0.11)[0] == [("note_off",), ("note_on", 62)]


def test_flicker_back_to_original_never_sounds():
    g = GestureLogic(debounce_ms=100)
    run(g, [M("10000")], 0.0)
    run(g, [M("11000")], 0.03)
    assert run(g, [M("10000")], 0.06)[0] == []
    assert run(g, [M("10000")], 0.2)[0] == []


def test_same_gesture_does_not_retrigger():
    g = GestureLogic()
    run(g, [M("10000")], 0.0)
    for i in range(1, 10):
        assert run(g, [M("10000")], i * 0.05)[0] == []


def test_left_hand_lost_off_after_grace():
    g = GestureLogic(lost_grace_ms=150)
    run(g, [M("10000")], 0.0)
    assert run(g, [], 0.10)[0] == []
    assert run(g, [], 0.30)[0] == [("note_off",)]


def test_hand_flicker_within_grace_keeps_sound():
    g = GestureLogic(lost_grace_ms=150)
    run(g, [M("10000")], 0.0)
    run(g, [], 0.05)
    assert run(g, [M("10000")], 0.1)[0] == []
    assert g.current is not None


def test_right_hand_flicker_within_grace_keeps_minor():
    g = GestureLogic(debounce_ms=100, lost_grace_ms=150)
    run(g, [M("11000"), X("10000")], 0.0)
    assert g.current.minor
    assert run(g, [M("11000")], 0.05)[0] == []  # kanan hilang sesaat -> tetap minor
    assert run(g, [M("11000")], 0.5)[0] == [("note_off",), ("note_on", 62)]  # hilang lama -> mayor


def test_reset_silences():
    g = GestureLogic()
    run(g, [M("10000")], 0.0)
    assert g.reset() == [("note_off",)] and g.current is None
    assert g.reset() == []


def test_put_drop_old_keeps_latest():
    q = queue.Queue(maxsize=2)
    for i in range(5):
        put_drop_old(q, i)
    assert [q.get_nowait(), q.get_nowait()] == [3, 4]


def test_logic_thread_end_to_end_with_fake_audio_and_clean_shutdown():
    state = SharedState()
    frame_q, audio_q = queue.Queue(maxsize=2), queue.Queue()
    backend = FakeBackend()
    engine = AudioEngine(backend)
    audio = AudioThread(engine, audio_q, state.stop_event)
    logic = LogicThread(state, frame_q, audio_q)
    audio.start()
    logic.start()

    frame_q.put(FramePacket(time.monotonic(), [M("11110"), X("10000")]))
    time.sleep(0.3)
    assert active(backend.events) == {(0, 64)}  # Fa (65) + thumb toggle = 64
    snap = state.snapshot()
    assert snap["note"]["label"] == "F\u266d (Minor)" and snap["note"]["midi"] == 64 and snap["minor_active"] is True
    assert snap["instrument"] == "piano" and snap["mode_label"] == "PIANO"
    assert snap["latency_ms"] > 0
    assert snap["camera_enabled"] is True and "history" not in snap and "source" not in snap

    state.stop_event.set()
    logic.join(2)
    audio.join(2)
    assert not logic.is_alive() and not audio.is_alive()
    engine.stop()
    assert active(backend.events) == set()
    assert not [t for t in threading.enumerate() if t.name in ("logic", "audio")]


def _drain(audio_q, engine):
    while not audio_q.empty():
        engine.handle(audio_q.get_nowait())


def test_double_fist_hold_switches_piano_to_violin_and_back():
    state = SharedState()
    audio_q = queue.Queue()
    backend = FakeBackend()
    engine = AudioEngine(backend)
    lt = LogicThread(state, queue.Queue(), audio_q)
    t = 0.0
    lt.step(FramePacket(t, [M("10000"), X("10000")]), t)  # Do + jempol kanan = minor (B3) sedang bunyi
    _drain(audio_q, engine)
    assert active(backend.events) == {(0, 59)}
    # kepalan ganda ditahan 1,6 dtk
    for i in range(0, 17):
        t = 1.0 + i / 10
        lt.step(FramePacket(t, [M("00000"), X("00000")]), t)
        _drain(audio_q, engine)
        if i == 7:
            assert state.snapshot()["switch_progress"] > 0.3 and state.instrument == "piano"  # belum 1,5 dtk
    assert state.instrument == "violin" and engine.instrument == "violin"
    assert backend.programs[-1] == (0, 0, 40)
    assert active(backend.events) == set()
    # tetap menahan kepalan -> tidak berpindah lagi
    for i in range(0, 30):
        t = 3.0 + i / 10
        lt.step(FramePacket(t, [M("00000"), X("00000")]), t)
    assert state.instrument == "violin"
    # lepas lalu tahan lagi -> kembali ke piano
    for i in range(0, 5):
        t = 6.0 + i / 10
        lt.step(FramePacket(t, [M("11000"), X("00000")]), t)
    for i in range(0, 17):
        t = 7.0 + i / 10
        lt.step(FramePacket(t, [M("00000"), X("00000")]), t)
    assert state.instrument == "piano"


def test_short_double_fist_does_not_switch():
    state = SharedState()
    lt = LogicThread(state, queue.Queue(), queue.Queue())
    for i in range(0, 10):  # 0.9 dtk
        t = i / 10
        lt.step(FramePacket(t, [M("00000"), X("00000")]), t)
    for i in range(10, 20):
        t = i / 10
        lt.step(FramePacket(t, [M("11000"), X("00000")]), t)
    assert state.instrument == "piano" and state.snapshot()["switch_progress"] == 0


def test_instrument_switch_changes_program_and_silences_then_replays_with_hand_held():
    state = SharedState()
    audio_q = queue.Queue()
    backend = FakeBackend()
    engine = AudioEngine(backend)
    lt = LogicThread(state, queue.Queue(), audio_q)
    lt.step(FramePacket(0.0, [M("10000")]), 0.0)
    _drain(audio_q, engine)
    assert active(backend.events) == {(0, 60)}
    state.configure(instrument="violin")
    lt.step(FramePacket(1.0, []), 1.0)
    _drain(audio_q, engine)
    assert active(backend.events) == set() and backend.programs[-1] == (0, 0, 40)
    lt.step(FramePacket(2.0, [M("10000")]), 2.0)
    _drain(audio_q, engine)
    assert active(backend.events) == {(0, 60)}  # pemetaan identik di mode biola


def test_camera_off_silences_instantly_and_ignores_gestures():
    state = SharedState()
    audio_q = queue.Queue()
    lt = LogicThread(state, queue.Queue(), audio_q)
    lt.step(FramePacket(0.0, [M("10000"), X("10000")]), 0.0)
    assert audio_q.get_nowait() == ("note_on", 59)
    state.configure(camera=False)
    lt.step(FramePacket(0.05, []), 0.05)  # tanpa menunggu grace 150 ms
    assert audio_q.get_nowait() == ("note_off",)
    snap = state.snapshot()
    assert snap["camera_enabled"] is False and snap["note"] is None and snap["minor_active"] is False
    # paket basi berisi tangan pun diabaikan selama kamera mati
    lt.step(FramePacket(0.1, [M("11000")]), 0.1)
    assert audio_q.empty() and state.snapshot()["note"] is None
    state.configure(camera=True)
    lt.step(FramePacket(1.0, [M("11000")]), 1.0)
    assert audio_q.get_nowait() == ("note_on", 62)


def test_camera_off_resets_double_fist_progress():
    state = SharedState()
    lt = LogicThread(state, queue.Queue(), queue.Queue())
    for i in range(0, 8):
        lt.step(FramePacket(i / 10, [M("00000"), X("00000")]), i / 10)
    assert state.snapshot()["switch_progress"] > 0
    state.configure(camera=False)
    lt.step(FramePacket(1.0, []), 1.0)
    assert state.snapshot()["switch_progress"] == 0


def test_clear_frame_drops_stale_image_and_hands():
    state = SharedState()
    state.set_frame(b"jpegdata", [M("10000")], 30.0)
    fid, jpeg = state.get_jpeg()
    assert jpeg == b"jpegdata" and state.snapshot()["hands"]
    state.clear_frame()
    fid2, jpeg2 = state.get_jpeg()
    assert jpeg2 is None and fid2 > fid
    snap = state.snapshot()
    assert snap["hands"] == [] and snap["fps"] == 0


def test_configure_camera_only_accepts_bool():
    s = SharedState()
    s.configure(camera="no")
    assert s.camera_enabled is True
    s.configure(camera=False)
    assert s.camera_enabled is False


def test_state_configure_clamps_and_validates():
    s = SharedState()
    s.configure(debounce_ms=5000, resolution="bogus", instrument="kazoo")
    assert s.debounce_ms == 1000 and s.resolution == "640x480" and s.instrument == "piano"
    s.configure(debounce_ms=50, resolution="320x240", instrument="violin")
    assert (s.debounce_ms, s.resolution, s.instrument) == (50, "320x240", "violin")


def test_default_roles_right_hand_is_melody_left_is_minor():
    g = GestureLogic()
    # kanan = melodi -> bunyi; kiri jempol saja -> minor
    assert run(g, [R("11000"), L("10000")], 0.0)[0] == [("note_on", 61)] and g.minor_active
    g2 = GestureLogic()
    # kiri BUKAN tangan melodi: gestur 11000 di kiri tidak mengubah nada; kanan jempol saja = C (mayor)
    assert run(g2, [L("11000"), R("10000")], 0.0)[0] == [("note_on", 60)]
    assert g2.minor_active is False
    g3 = GestureLogic()
    assert run(g3, [L("11000")], 0.0) == ([], [])  # tangan kiri saja (modifier) tidak berbunyi


def test_roles_follow_config_when_swapped(monkeypatch):
    monkeypatch.setattr(config, "MELODY_HAND", "left")
    monkeypatch.setattr(config, "MODIFIER_HAND", "right")
    g = GestureLogic()
    assert run(g, [L("11000"), R("10000")], 0.0)[0] == [("note_on", 61)]
