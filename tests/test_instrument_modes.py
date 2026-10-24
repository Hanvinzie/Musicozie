import pytest

import config
from instrument_modes import MODES, ModeSwitch, bend_units_per_cent, next_mode, vibrato_bend

FIST = (0, 0, 0, 0, 0)
OPEN = (1, 1, 1, 1, 1)


def test_modes_programs_and_behaviour():
    assert MODES["piano"].program == 0 and not MODES["piano"].sustained and not MODES["piano"].vibrato
    assert MODES["violin"].program == 40 and MODES["violin"].sustained and MODES["violin"].vibrato


def test_next_mode_toggles():
    assert next_mode("piano") == "violin" and next_mode("violin") == "piano"


def test_vibrato_silent_during_delay():
    assert vibrato_bend(0.0) == 0
    assert vibrato_bend(config.VIBRATO_DELAY_S) == 0


def test_vibrato_oscillates_within_depth():
    limit = config.VIBRATO_DEPTH_CENTS * bend_units_per_cent() + 1
    vals = [vibrato_bend(0.15 + i * 0.005) for i in range(400)]
    assert max(vals) > 0 > min(vals)  # naik dan turun di sekitar nol
    assert max(abs(v) for v in vals) <= limit
    # setelah ramp selesai, puncak mendekati kedalaman penuh
    late = [abs(vibrato_bend(1.0 + i * 0.002)) for i in range(200)]
    assert max(late) > 0.9 * config.VIBRATO_DEPTH_CENTS * bend_units_per_cent()


def test_vibrato_ramps_in_smoothly():
    early = max(abs(vibrato_bend(config.VIBRATO_DELAY_S + 0.02 + i * 0.002)) for i in range(40))
    late = max(abs(vibrato_bend(1.0 + i * 0.002)) for i in range(200))
    assert early < late / 2


def test_switch_fires_once_after_hold():
    s = ModeSwitch(hold_s=1.5)
    fired = [s.update(FIST, FIST, t / 10) for t in range(0, 40)]  # 0 .. 3.9 s
    assert fired.count(True) == 1
    assert fired.index(True) == 15  # t = 1.5 s


def test_switch_not_before_hold():
    s = ModeSwitch(hold_s=1.5)
    assert not any(s.update(FIST, FIST, t / 10) for t in range(0, 15))  # sampai 1.4 s


def test_switch_progress_hud():
    s = ModeSwitch(hold_s=1.5)
    s.update(FIST, FIST, 0.0)
    s.update(FIST, FIST, 0.75)
    assert s.progress == pytest.approx(0.5)
    s.update(OPEN, FIST, 2.0)
    s.update(OPEN, FIST, 2.5)  # dilepas melewati dropout
    assert s.progress == 0.0


def test_switch_needs_both_hands_and_both_fists():
    s = ModeSwitch(hold_s=1.5)
    assert not any(s.update(FIST, None, t / 10) for t in range(40))
    s = ModeSwitch(hold_s=1.5)
    assert not any(s.update(FIST, OPEN, t / 10) for t in range(40))


def test_switch_released_early_resets():
    s = ModeSwitch(hold_s=1.5)
    for t in range(0, 10):
        s.update(FIST, FIST, t / 10)
    for t in range(10, 14):  # dilepas > dropout (0.2 s)
        s.update(OPEN, FIST, t / 10)
    # mulai lagi: butuh tahan penuh dari awal
    assert not any(s.update(FIST, FIST, 1.4 + t / 10) for t in range(0, 14))
    assert s.update(FIST, FIST, 1.4 + 1.5)


def test_switch_short_dropout_does_not_reset():
    s = ModeSwitch(hold_s=1.5, dropout_s=0.2)
    fired = False
    for t in range(0, 17):
        tt = t / 10
        hands = (None, None) if t == 8 else (FIST, FIST)  # 1 frame hilang
        fired |= s.update(hands[0], hands[1], tt)
    assert fired


def test_switch_does_not_repeat_while_still_holding_then_rearms():
    s = ModeSwitch(hold_s=1.5)
    n = sum(s.update(FIST, FIST, t / 10) for t in range(0, 100))  # 10 detik tahan terus
    assert n == 1
    s.update(OPEN, OPEN, 10.0)
    s.update(OPEN, OPEN, 10.5)
    n2 = sum(s.update(FIST, FIST, 11 + t / 10) for t in range(0, 20))
    assert n2 == 1
