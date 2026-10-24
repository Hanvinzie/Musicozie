import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import config
import server
from pipeline import SharedState

LOCAL = {"host": "127.0.0.1:8000"}


@pytest.fixture
def state():
    s = SharedState()
    yield s
    s.stop_event.set()


@pytest.fixture
def client(state):
    return TestClient(server.create_app(state), base_url="http://127.0.0.1:8000")


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


def test_default_host_is_loopback():
    assert config.SERVER_HOST == "127.0.0.1"
    st = SharedState()
    t = server.ServerThread(st, 8765)
    assert t.server.config.host == "127.0.0.1"


def test_ws_state_schema(client):
    with client.websocket_connect("/ws", headers=LOCAL) as ws:
        msg = recv_state(ws)
    for key in ("status", "fps", "latency_ms", "hands", "note", "instrument", "mode_label", "switch_progress",
                "minor_active", "camera_enabled", "debounce_ms", "resolution"):
        assert key in msg
    # fitur yang sudah dihapus tidak boleh bocor lagi
    assert "history" not in msg and "source" not in msg
    assert msg["instrument"] == "piano" and msg["mode_label"] == "PIANO" and msg["camera_enabled"] is True


def test_ws_config_applied(client, state):
    with client.websocket_connect("/ws", headers=LOCAL) as ws:
        ws.send_text(json.dumps({"type": "config", "debounce_ms": 150, "resolution": "320x240"}))
        until_state(ws, lambda m: m["debounce_ms"] == 150)
    assert (state.debounce_ms, state.resolution) == (150, "320x240")


def test_ws_instrument_switch(client, state):
    with client.websocket_connect("/ws", headers=LOCAL) as ws:
        ws.send_text(json.dumps({"type": "config", "instrument": "violin"}))
        until_state(ws, lambda m: m["instrument"] == "violin")
    assert state.instrument == "violin"


def test_ws_camera_toggle(client, state):
    with client.websocket_connect("/ws", headers=LOCAL) as ws:
        ws.send_text(json.dumps({"type": "config", "camera": False}))
        until_state(ws, lambda m: m["camera_enabled"] is False)
        assert state.camera_enabled is False
        ws.send_text(json.dumps({"type": "config", "camera": True}))
        until_state(ws, lambda m: m["camera_enabled"] is True)
    assert state.camera_enabled is True


def test_ws_camera_must_be_bool(client, state):
    with client.websocket_connect("/ws", headers=LOCAL) as ws:
        ws.send_text(json.dumps({"type": "config", "camera": "off"}))
        for _ in range(40):
            m = json.loads(ws.receive_text())
            if m["type"] == "error":
                break
        else:
            raise AssertionError("tidak ada error")
    assert state.camera_enabled is True


def test_simulator_message_is_gone(client, state):
    with client.websocket_connect("/ws", headers=LOCAL) as ws:
        ws.send_text(json.dumps({"type": "sim", "hand": "left", "fingers": [1, 0, 0, 0, 0]}))
        for _ in range(40):
            m = json.loads(ws.receive_text())
            if m["type"] == "error":
                assert "unknown" in m["message"]
                break
        else:
            raise AssertionError("pesan sim seharusnya ditolak")
    assert not hasattr(state, "sim_hands") and not hasattr(state, "source")


def test_ws_rejects_foreign_origin(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={**LOCAL, "origin": "https://evil.example"}) as ws:
            ws.receive_text()


def test_ws_accepts_local_origin(client):
    with client.websocket_connect("/ws", headers={**LOCAL, "origin": "http://localhost:8000"}) as ws:
        assert recv_state(ws)["type"] == "state"


def test_http_rejects_foreign_host(client):
    assert client.get("/api/state", headers={"host": "evil.example"}).status_code == 403
    assert client.get("/api/state").status_code == 200


def test_ws_bad_json_and_unknown_type_return_error(client):
    with client.websocket_connect("/ws", headers=LOCAL) as ws:
        ws.send_text("{bukan json")
        ws.send_text(json.dumps({"type": "zzz"}))
        errs = []
        for _ in range(40):
            m = json.loads(ws.receive_text())
            if m["type"] == "error":
                errs.append(m)
            if len(errs) == 2:
                break
    assert len(errs) == 2


def test_video_is_multipart_mjpeg(state):
    state.set_frame(b"\xff\xd8fakejpeg\xff\xd9", [], 30.0)
    app = server.create_app(state)
    route = next(r for r in app.routes if getattr(r, "path", "") == "/video")

    async def first_chunk():
        resp = await route.endpoint()
        assert resp.media_type.startswith("multipart/x-mixed-replace")
        return await resp.body_iterator.__anext__()

    chunk = asyncio.run(first_chunk())
    assert chunk.startswith(b"--frame") and b"image/jpeg" in chunk and b"fakejpeg" in chunk


def test_video_stream_ends_when_camera_off(state):
    state.set_frame(b"\xff\xd8x\xff\xd9", [], 30.0)
    state.configure(camera=False)
    app = server.create_app(state)
    route = next(r for r in app.routes if getattr(r, "path", "") == "/video")

    async def run():
        resp = await route.endpoint()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(resp.body_iterator.__anext__(), 1)

    asyncio.run(run())


# ---------------------------------------------------------------- siap deploy: health, header, aset statis
def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_security_headers_on_all_responses(client):
    for path in ("/", "/api/state", "/healthz", "/assets/app.js"):
        r = client.get(path)
        h = r.headers
        assert "script-src 'self'" in h["content-security-policy"], path
        assert "unsafe-inline" not in h["content-security-policy"], path
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
    # termasuk respons 403 dari penjaga host
    assert "content-security-policy" in client.get("/api/state", headers={"host": "evil.example"}).headers


def test_index_and_assets_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    html = r.text
    assert 'src="/assets/app.js"' in html and 'href="/assets/app.css"' in html and "favicon.svg" in html
    assert "<script>" not in html and " style=" not in html  # kompatibel dengan CSP tanpa unsafe-inline
    for asset, ctype in (("app.js", "javascript"), ("theme.js", "javascript"), ("app.css", "css"), ("favicon.svg", "svg")):
        a = client.get(f"/assets/{asset}")
        assert a.status_code == 200 and ctype in a.headers["content-type"], asset
        assert a.headers["cache-control"] == "no-cache"
    assert client.get("/assets/../server.py").status_code in (400, 404)
    assert client.get("/assets/nope.js").status_code == 404


def test_dashboard_has_no_removed_features(client):
    html = client.get("/").text.lower()
    js = client.get("/assets/app.js").text.lower()
    for word in ("simulator", "note history", "no hand", "offline sim"):
        assert word not in html, word
        assert word not in js, word


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


def test_api_config_follows_config_changes(client, monkeypatch):
    monkeypatch.setitem(config.SOLFEGE, (1, 0, 0, 0, 1), ("Test", 50))
    monkeypatch.setattr(config, "MINOR_SHIFT", -2)
    cfg = client.get("/api/config").json()
    row = [r for r in cfg["solfege"] if r["name"] == "Test"][0]
    assert row["code"] == "10001" and row["minor_midi"] == 48 and cfg["minor_shift"] == -2


def test_footer_copyright_and_version(client):
    html = client.get("/").text
    assert "&copy; 2026 Hanvinzie. All rights reserved. Musicozie" in html
    assert 'id="appVersion">v1.0<' in html
    assert config.VERSION == "1.0" and client.get("/api/config").json()["app"]["version"] == "1.0"


def test_theme_toggle_next_to_local_text_in_footer(client):
    html = client.get("/").text
    foot = html[html.index('<footer class="foot">'):html.index("</footer>")]
    assert "Runs locally" in foot and 'id="themeToggle"' in foot
    assert foot.index("Runs locally") < foot.index('id="themeToggle"')  # toggle sits to the right of the "locally" text
    # theme.js dimuat sinkron di <head> (sebelum CSS) agar tidak berkedip; bukan inline
    head = html[:html.index("</head>")]
    assert '<script src="/assets/theme.js"></script>' in head


def test_css_has_light_and_dark_themes_and_card_like_badge(client):
    css = client.get("/assets/app.css").text
    assert ':root[data-theme="light"]' in css and "--on-text" in css
    badge = css[css.index(".badge {"):css.index("}", css.index(".badge {"))]
    assert "border-radius: var(--radius)" in badge and "background: var(--card)" in badge and "border: 1px solid var(--border)" in badge
    card = css[css.index(".card {"):css.index("}", css.index(".card {"))]
    assert "border-radius: var(--radius)" in card  # sudut sama dengan container lain
    js = client.get("/assets/app.js").text
    assert "musicozie-theme" in js and client.get("/assets/theme.js").text.count("musicozie-theme") == 1


def test_ui_is_english_only(client):
    import re

    html = client.get("/").text
    js = client.get("/assets/app.js").text
    assert '<html lang="en">' in html
    banned = ["kamera", "tangan", "jempol", "telunjuk", "panduan", "resolusi", "instrumen", "berjalan", "kepalan", "latensi",
              "mayor", "nada ", "tidak ", "dimatikan", "nyalakan", "menghubungkan"]
    low_html, low_js = html.lower(), js.lower()
    for w in banned:
        pat = r"\b" + re.escape(w.strip()) + r"\b"
        assert not re.search(pat, low_html), f"Indonesian word in HTML: {w}"
        assert not re.search(pat, low_js), f"Indonesian word in JS: {w}"
    cfg = client.get("/api/config").json()
    for row in cfg["solfege"]:
        assert not re.search(r"jempol|telunjuk|tengah|manis|kelingking|kepalan", row["description"].lower()), row


def test_api_config_descriptions_english(client):
    rows = {r["name"]: r["description"] for r in client.get("/api/config").json()["solfege"]}
    assert rows["C"] == "Thumb only" and rows["D"] == "Thumb + index"
    assert rows["G"] == "All 5 fingers open (open palm)"
    assert rows["A"] == "Index + middle + ring + pinky (thumb closed)"
    assert rows["C High"] == "Index + middle (thumb closed)"
