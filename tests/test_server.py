"""Test server FastAPI (versi deploy cloud/Render).

Catatan desain: server ini sengaja memakai CORS "*", TrustedHost "*" dan HOST 0.0.0.0 agar bisa dipakai di Render,
sehingga test lama untuk loopback, penolakan Origin/Host asing, dan header CSP tidak lagi berlaku dan dihapus.
Perilaku yang diuji di sini: WebSocket realtime + config, /video (MJPEG atau PNG transparan), dashboard statis,
model MediaPipe untuk browser, dan /api/config.
"""
import asyncio
import io
import json
import re

import pytest
from fastapi.testclient import TestClient

import config
import server
from pipeline import SharedState


@pytest.fixture
def state():
    s = SharedState()
    server.ServerThread(s, 0)            # memasang state ke app (tanpa menjalankan uvicorn)
    yield s
    s.stop_event.set()
    server.app.state.server_thread = None


@pytest.fixture
def client(state):
    return TestClient(server.app)


def recv_state(ws):
    for _ in range(20):
        msg = json.loads(ws.receive_text())
        if msg["type"] == "state":
            return msg
    raise AssertionError("tidak ada pesan state")


def until_state(ws, pred, tries=40):
    for _ in range(tries):
        msg = recv_state(ws)
        if pred(msg):
            return msg
    raise AssertionError("kondisi state tidak tercapai")


def until_error(ws, tries=60):
    for _ in range(tries):
        msg = json.loads(ws.receive_text())
        if msg["type"] == "error":
            return msg
    raise AssertionError("tidak ada pesan error")


# --------------------------------------------------------------------------- WebSocket
def test_ws_state_schema(client):
    with client.websocket_connect("/ws") as ws:
        msg = recv_state(ws)
    for key in ("status", "fps", "latency_ms", "hands", "note", "instrument", "mode_label", "switch_progress",
                "minor_active", "camera_enabled", "debounce_ms", "resolution", "client_camera", "has_video"):
        assert key in msg
    assert msg["instrument"] == "piano" and msg["mode_label"] == "PIANO" and msg["camera_enabled"] is True
    assert "history" not in msg and "source" not in msg


def test_ws_streams_snapshots_realtime(client):
    import time

    with client.websocket_connect("/ws") as ws:
        t0, n = time.time(), 0
        while time.time() - t0 < 0.5:
            recv_state(ws)
            n += 1
    assert n >= 8


def test_ws_reports_client_camera_flag(client, state):
    state.set_client_camera(True)
    with client.websocket_connect("/ws") as ws:
        assert recv_state(ws)["client_camera"] is True
    state.set_client_camera(False)
    with client.websocket_connect("/ws") as ws:
        assert recv_state(ws)["client_camera"] is False


def test_ws_config_applied(client, state):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "config", "debounce_ms": 150, "resolution": "320x240"}))
        until_state(ws, lambda m: m["debounce_ms"] == 150)
    assert (state.debounce_ms, state.resolution) == (150, "320x240")


def test_ws_instrument_switch(client, state):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "config", "instrument": "violin"}))
        until_state(ws, lambda m: m["instrument"] == "violin")
    assert state.instrument == "violin"


def test_ws_camera_toggle(client, state):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "config", "camera": False}))
        until_state(ws, lambda m: m["camera_enabled"] is False)
        ws.send_text(json.dumps({"type": "config", "camera": True}))
        until_state(ws, lambda m: m["camera_enabled"] is True)
    assert state.camera_enabled is True


def test_ws_camera_must_be_bool(client, state):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "config", "camera": "off"}))
        for _ in range(10):
            recv_state(ws)
    assert state.camera_enabled is True


def test_ws_bad_json_unknown_type_and_removed_simulator(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text("{bukan json")
        assert until_error(ws)["message"] == "invalid json"
        ws.send_text(json.dumps({"type": "zzz"}))
        assert until_error(ws)["message"] == "unknown message type"
        ws.send_text(json.dumps({"type": "sim", "hand": "left", "fingers": [1, 0, 0, 0, 0]}))
        assert until_error(ws)["message"] == "unknown message type"
        ws.send_text(json.dumps({"type": "config", "debounce_ms": "abc"}))
        assert until_error(ws)["message"] == "invalid config value"


def test_ws_without_pipeline_sends_complete_fallback_snapshot():
    server.app.state.server_thread = None
    with TestClient(server.app).websocket_connect("/ws") as ws:
        msg = recv_state(ws)
    assert msg["status"] == "ok" and msg["camera_enabled"] is True and msg["fps"] == 0.0
    assert msg["client_camera"] is True and msg["hands"] == [] and msg["instrument"] == config.DEFAULT_INSTRUMENT


# --------------------------------------------------------------------------- /video
def test_video_png_fallback_is_200_not_204(client):
    from PIL import Image

    r = client.get("/video")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(r.content))
    img.load()
    assert img.size == (1, 1) and img.mode == "RGBA" and img.getpixel((0, 0))[3] == 0   # 1x1 transparan


def test_video_png_fallback_without_pipeline():
    server.app.state.server_thread = None
    r = TestClient(server.app).get("/video")
    assert r.status_code == 200 and r.content == server.TRANSPARENT_PNG


def test_video_png_when_camera_off_even_with_old_frame(client, state):
    state.set_frame(b"\xff\xd8x\xff\xd9", [], 30.0)
    state.configure(camera=False)
    assert client.get("/video").headers["content-type"] == "image/png"


def _video_route():
    return next(r for r in server.app.routes if getattr(r, "path", "") == "/video")


def test_video_is_multipart_mjpeg_and_ends_when_camera_off(state):
    state.set_frame(b"\xff\xd8fakejpeg\xff\xd9", [], 30.0)

    async def go():
        resp = await _video_route().endpoint()
        assert resp.media_type.startswith("multipart/x-mixed-replace")
        first = await resp.body_iterator.__anext__()
        assert first.startswith(b"--frame") and b"image/jpeg" in first and b"fakejpeg" in first
        state.set_frame(b"\xff\xd8second\xff\xd9", [], 30.0)          # frame baru ikut terkirim
        second = await asyncio.wait_for(resp.body_iterator.__anext__(), 2)
        assert b"second" in second
        state.configure(camera=False)                                  # kamera mati -> stream berakhir
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(resp.body_iterator.__anext__(), 2)

    asyncio.run(go())


# --------------------------------------------------------------------------- statis + model
def test_healthz_and_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "version": config.VERSION}


def test_index_and_assets_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    html = r.text
    assert 'src="/assets/app.js"' in html and 'src="/assets/engine.js"' in html
    assert html.index("/assets/engine.js") < html.index("/assets/app.js")     # engine dimuat lebih dulu
    for path in ("/assets/app.js", "/assets/engine.js", "/assets/app.css", "/assets/theme.js"):
        assert client.get(path).status_code == 200, path


def test_hand_model_is_served_for_the_browser(client):
    if not config.HAND_MODEL_PATH.exists():
        pytest.skip("models/hand_landmarker.task tidak ada")
    r = client.head("/models/hand_landmarker.task")
    assert r.status_code == 200
    assert int(r.headers["content-length"]) == config.HAND_MODEL_PATH.stat().st_size
    assert client.get("/models/../server.py").status_code in (400, 404)       # hanya folder models yang terbuka


def test_dashboard_has_no_removed_features(client):
    html = client.get("/").text.lower()
    for path in ("/assets/app.js", "/assets/engine.js"):
        js = client.get(path).text.lower()
        for word in ("simulator", "note history", "no hand", "offline sim"):
            assert word not in html, word
            assert word not in js, (path, word)


# --------------------------------------------------------------------------- /api/config
def test_api_config_mirrors_python_files(client):
    from gesture_matrix import describe_pattern

    cfg = client.get("/api/config").json()
    assert cfg["minor_shift"] == config.MINOR_SHIFT
    assert cfg["mode_switch_hold_s"] == config.MODE_SWITCH_HOLD_S
    assert cfg["minor_trigger"] == "10000"
    assert cfg["melody_hand"] == "right" and cfg["modifier_hand"] == "left"
    assert cfg["app"]["version"] == config.VERSION
    assert [(r["name"], r["midi"], r["code"]) for r in cfg["solfege"]] == [
        ("C", 60, "10000"), ("D", 62, "11000"), ("E", 64, "11100"), ("F", 65, "11110"),
        ("G", 67, "11111"), ("A", 69, "01111"), ("B", 71, "01110"), ("C High", 72, "01100"),
    ]
    assert cfg["solfege"][0]["minor_midi"] == 59 and cfg["solfege"][0]["minor_note"] == "B3"
    assert {i["key"]: i["program"] for i in cfg["instruments"]} == {"piano": 0, "violin": 40}
    assert cfg["solfege"][0]["description"] == describe_pattern((1, 0, 0, 0, 0))


def test_api_config_has_vision_thresholds_for_browser_engine(client):
    v = client.get("/api/config").json()["vision"]
    assert v == {
        "open_ratio": config.OPEN_RATIO, "thumb_tuck_ratio": config.THUMB_TUCK_RATIO,
        "min_hand_score": config.MIN_HAND_SCORE, "debounce_ms": config.DEBOUNCE_MS,
        "lost_grace_ms": config.LOST_GRACE_MS, "melody_velocity": config.MELODY_VELOCITY,
    }
    assert client.get("/api/config").json()["vibrato"]["ramp_s"] == config.VIBRATO_RAMP_S


def test_api_config_follows_config_changes(client, monkeypatch):
    monkeypatch.setitem(config.SOLFEGE, (1, 0, 0, 0, 1), ("Test", 50))
    monkeypatch.setattr(config, "MINOR_SHIFT", -2)
    cfg = client.get("/api/config").json()
    row = [r for r in cfg["solfege"] if r["name"] == "Test"][0]
    assert row["code"] == "10001" and row["minor_midi"] == 48 and cfg["minor_shift"] == -2


def test_api_config_descriptions_english(client):
    rows = {r["name"]: r["description"] for r in client.get("/api/config").json()["solfege"]}
    assert rows["C"] == "Thumb only" and rows["D"] == "Thumb + index"
    assert rows["G"] == "All 5 fingers open (open palm)"
    assert rows["A"] == "Index + middle + ring + pinky (thumb closed)"
    assert rows["C High"] == "Index + middle (thumb closed)"


# --------------------------------------------------------------------------- tampilan
def test_footer_copyright_and_version(client):
    html = client.get("/").text
    assert "&copy; 2026 Hanvinzie. All rights reserved. Musicozie" in html
    assert 'id="appVersion">v1.0<' in html
    assert config.VERSION == "1.0" and client.get("/api/config").json()["app"]["version"] == "1.0"


def test_theme_toggle_next_to_local_text_in_footer(client):
    html = client.get("/").text
    foot = html[html.index('<footer class="foot">'):html.index("</footer>")]
    assert "Runs locally" in foot and 'id="themeToggle"' in foot
    assert foot.index("Runs locally") < foot.index('id="themeToggle"')
    assert '<script src="/assets/theme.js"></script>' in html[:html.index("</head>")]


def test_css_has_light_and_dark_themes_and_card_like_badge(client):
    css = client.get("/assets/app.css").text
    assert ':root[data-theme="light"]' in css and "--on-text" in css
    badge = css[css.index(".badge {"):css.index("}", css.index(".badge {"))]
    assert "border-radius: var(--radius)" in badge and "background: var(--card)" in badge
    assert "musicozie-theme" in client.get("/assets/app.js").text
    assert client.get("/assets/theme.js").text.count("musicozie-theme") == 1


def test_ui_is_english_only(client):
    html = client.get("/").text
    assert '<html lang="en">' in html
    banned = ["kamera", "tangan", "jempol", "telunjuk", "panduan", "resolusi", "instrumen", "berjalan", "kepalan", "latensi",
              "mayor", "nada", "tidak", "dimatikan", "nyalakan", "menghubungkan", "suara", "izin"]
    for name, text in (("HTML", html), ("app.js", client.get("/assets/app.js").text),
                       ("engine.js", client.get("/assets/engine.js").text)):
        low = text.lower()
        for w in banned:
            assert not re.search(r"\b" + re.escape(w) + r"\b", low), f"Indonesian word in {name}: {w}"
    for row in client.get("/api/config").json()["solfege"]:
        assert not re.search(r"jempol|telunjuk|tengah|manis|kelingking|kepalan", row["description"].lower()), row