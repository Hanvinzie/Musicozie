import queue
import threading
import time

import config
from audio_engine import AudioEngine, AudioThread


class FakeBackend:
    def __init__(self):
        self.events = []
        self.programs = []
        self.bends = []
        self.ranges = []
        self.closed = False

    def program_select(self, ch, bank, program):
        self.programs.append((ch, bank, program))

    def set_bend_range(self, ch, semitones):
        self.ranges.append((ch, semitones))

    def pitch_bend(self, ch, value):
        self.bends.append(value)

    def noteon(self, ch, note, vel):
        self.events.append(("on", ch, note))

    def noteoff(self, ch, note):
        self.events.append(("off", ch, note))

    def all_notes_off(self, ch):
        self.events.append(("all_off", ch))

    def close(self):
        self.closed = True


def active(events):
    """Set (ch, note) yang masih menyala setelah rangkaian event."""
    s = set()
    for e in events:
        if e[0] == "on":
            s.add(e[1:])
        elif e[0] == "off":
            s.discard(e[1:])
        elif e[0] == "all_off":
            s = {x for x in s if x[0] != e[1]}
    return s


def test_default_is_piano_program_0_with_bend_range():
    b = FakeBackend()
    AudioEngine(b)
    assert b.programs[-1] == (0, 0, 0)
    assert b.ranges[-1] == (0, config.BEND_RANGE_SEMITONES)


def test_monophonic_new_note_replaces_old():
    b = FakeBackend()
    eng = AudioEngine(b)
    eng.note_on(60)
    eng.note_on(62)
    assert active(b.events) == {(0, 62)}
    assert eng.active_note == 62


def test_note_off_and_double_off_safe():
    b = FakeBackend()
    eng = AudioEngine(b)
    eng.note_on(60)
    eng.note_off()
    eng.note_off()
    assert active(b.events) == set() and eng.active_note is None


def test_set_instrument_violin_is_program_40_and_silences():
    b = FakeBackend()
    eng = AudioEngine(b)
    eng.note_on(60)
    eng.set_instrument("violin")
    assert active(b.events) == set()
    assert b.programs[-1] == (0, 0, 40) and eng.instrument == "violin"
    eng.set_instrument("piano")
    assert b.programs[-1] == (0, 0, 0)


def test_unknown_instrument_ignored():
    b = FakeBackend()
    eng = AudioEngine(b)
    eng.set_instrument("kazoo")
    assert eng.instrument == "piano"


def test_piano_never_bends():
    b = FakeBackend()
    eng = AudioEngine(b)
    base = len(b.bends)
    eng.note_on(60, now=0.0)
    for i in range(100):
        eng.tick(now=i * 0.01)
    assert b.bends[base:] == []  # tidak ada perubahan bend selama piano


def test_violin_vibrato_bends_after_delay_and_oscillates():
    b = FakeBackend()
    eng = AudioEngine(b)
    eng.set_instrument("violin")
    base = len(b.bends)
    eng.note_on(60, now=0.0)
    for i in range(0, 120):
        eng.tick(now=i * 0.01)  # 0 .. 1.19 s
    vals = b.bends[base:]
    assert vals and max(vals) > 0 > min(vals)
    # sebelum delay tidak ada bend
    b2 = FakeBackend()
    e2 = AudioEngine(b2, instrument="violin")
    n = len(b2.bends)
    e2.note_on(60, now=0.0)
    for i in range(10):
        e2.tick(now=i * 0.01)
    assert b2.bends[n:] == []


def test_violin_bend_resets_on_release_and_idle_does_nothing():
    b = FakeBackend()
    eng = AudioEngine(b, instrument="violin")
    eng.note_on(60, now=0.0)
    for i in range(60):
        eng.tick(now=i * 0.01)
    assert any(v != 0 for v in b.bends)
    eng.note_off()
    assert b.bends[-1] == 0
    n = len(b.bends)
    eng.tick(now=1.0)  # tidak ada nada -> tidak ada bend baru
    assert len(b.bends) == n


def test_handle_commands():
    b = FakeBackend()
    eng = AudioEngine(b)
    eng.handle(("note_on", 64))
    assert active(b.events) == {(0, 64)}
    eng.handle(("instrument", "violin"))
    assert active(b.events) == set()
    eng.handle(("note_on", 64))
    eng.handle(("note_off",))
    eng.handle(("note_on", 65))
    eng.handle(("all_off",))
    assert active(b.events) == set()


def test_stop_silences_and_closes():
    b = FakeBackend()
    eng = AudioEngine(b)
    eng.note_on(60)
    eng.stop()
    assert active(b.events) == set() and b.closed
    assert ("all_off", config.MELODY_CHANNEL) in b.events


def test_audio_thread_consumes_queue_ticks_and_stops_clean():
    b = FakeBackend()
    eng = AudioEngine(b, instrument="violin")
    q, stop = queue.Queue(), threading.Event()
    t = AudioThread(eng, q, stop)
    t.start()
    q.put(("note_on", 60))
    time.sleep(0.6)  # > delay vibrato -> thread harus menge-tick
    assert active(b.events) == {(0, 60)}
    assert any(v != 0 for v in b.bends)
    stop.set()
    t.join(timeout=2)
    assert not t.is_alive()
    assert active(b.events) == set()
