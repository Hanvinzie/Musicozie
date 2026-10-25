"""Mode cloud/headless (Render): server tidak membuka kamera dan tidak membuka mesin audio.

Kamera, deteksi tangan, dan suara berjalan di browser (dashboard/assets/engine.js); server cukup menjaga
status "ok" supaya badge dashboard tetap ONLINE.
"""
import sys
import time
import types

import pytest

import config
import pipeline
import vision_processor
from pipeline import SharedState


def _no_camera(*a, **k):
    raise AssertionError("open_camera() tidak boleh dipanggil di mode cloud")


def _stop(state, threads):
    state.stop_event.set()
    for t in threads:
        t.join(timeout=3)


@pytest.fixture
def fail_if_audio_engine_loaded(monkeypatch):
    """Mode kamera-browser tidak boleh mengimpor audio_engine (FluidSynth/sound card)."""
    monkeypatch.delitem(sys.modules, "audio_engine", raising=False)
    monkeypatch.setitem(sys.modules, "audio_engine", None)   # import apa pun akan gagal (ImportError)


def test_cloud_env_detection(monkeypatch):
    monkeypatch.delenv("MUSICOZIE_CLIENT_CAMERA", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    assert config.is_cloud_environment() is False
    monkeypatch.setenv("RENDER", "true")
    assert config.is_cloud_environment() is True and pipeline.is_cloud_environment() is True
    monkeypatch.setenv("MUSICOZIE_CLIENT_CAMERA", "0")
    assert config.is_cloud_environment() is False
    monkeypatch.setenv("MUSICOZIE_CLIENT_CAMERA", "1")
    monkeypatch.delenv("RENDER")
    assert config.is_cloud_environment() is True


def test_cloud_mode_skips_camera_and_audio_engine_and_stays_ok(monkeypatch, fail_if_audio_engine_loaded):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr(vision_processor, "open_camera", _no_camera)
    st = SharedState()
    threads, engine = pipeline.start_pipeline(st, require_camera=False, soundfont=None)
    try:
        assert engine is None                                    # tidak ada FluidSynth / file driver
        assert {t.name for t in threads} == {"logic", "vision"}
        time.sleep(0.4)
        snap = st.snapshot()
        assert snap["status"] == "ok" and snap["client_camera"] is True and snap["has_video"] is False
        st.set_status("starting")                                # VisionThread memulihkan "ok"
        time.sleep(0.6)
        assert st.snapshot()["status"] == "ok"
        assert next(t for t in threads if t.name == "vision").is_alive()
    finally:
        _stop(st, threads)


def test_no_physical_camera_falls_back_to_browser_without_error(monkeypatch, fail_if_audio_engine_loaded):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("MUSICOZIE_CLIENT_CAMERA", raising=False)

    def fail(*a, **k):
        raise RuntimeError("Camera index 0 could not be opened")

    monkeypatch.setattr(vision_processor, "open_camera", fail)
    st = SharedState()
    threads, engine = pipeline.start_pipeline(st, require_camera=False)
    try:
        time.sleep(0.3)
        assert st.snapshot()["status"] == "ok" and st.snapshot()["client_camera"] is True and engine is None
    finally:
        _stop(st, threads)


def test_require_camera_true_still_raises(monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("Camera index 0 could not be opened")

    monkeypatch.setattr(vision_processor, "open_camera", fail)
    with pytest.raises(RuntimeError):
        pipeline.start_pipeline(SharedState(), require_camera=True)


def test_local_camera_present_keeps_server_mode_and_audio(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("MUSICOZIE_CLIENT_CAMERA", raising=False)

    class FakeCap:
        def set(self, *a): pass
        def read(self): return False, None
        def release(self): pass

    ae = types.ModuleType("audio_engine")

    class FakeEngine:
        def __init__(self, **k): pass
        def stop(self): pass

    class FakeAudioThread:
        name = "audio"
        def __init__(self, engine, q, ev):
            import threading
            self._t = threading.Thread(target=ev.wait, daemon=True)
        def start(self): self._t.start()
        def join(self, timeout=None): self._t.join(timeout)
        def is_alive(self): return self._t.is_alive()

    ae.AudioEngine, ae.AudioThread = FakeEngine, FakeAudioThread
    monkeypatch.setitem(sys.modules, "audio_engine", ae)
    monkeypatch.setattr(vision_processor, "open_camera", lambda *a, **k: FakeCap())
    monkeypatch.setattr(vision_processor, "VisionProcessor", lambda: types.SimpleNamespace(close=lambda: None, process=lambda f: (f, [])))
    st = SharedState()
    threads, engine = pipeline.start_pipeline(st, require_camera=False)
    try:
        time.sleep(0.3)
        assert engine is not None and st.snapshot()["client_camera"] is False and st.snapshot()["status"] == "ok"
    finally:
        _stop(st, threads)


def test_main_does_not_require_soundfont_in_cloud(monkeypatch, tmp_path):
    import main

    monkeypatch.setenv("RENDER", "true")
    started = {}
    monkeypatch.setattr(main, "start_pipeline", lambda *a, **k: started.setdefault("ok", True) and ([], None))
    monkeypatch.setattr(sys.modules["time"], "sleep", lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    rc = main.main(["--headless", "--soundfont", str(tmp_path / "missing.sf2")])
    assert started.get("ok") is True and rc in (0, 1)