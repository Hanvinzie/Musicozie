"""Server dashboard lokal (FastAPI + uvicorn).

KEAMANAN: server ini TANPA autentikasi dan menyiarkan video kamera. Karena itu:
  * bind HANYA ke 127.0.0.1 (config.SERVER_HOST) - jangan diubah ke 0.0.0.0;
  * header Host & Origin diperiksa (anti DNS-rebinding / cross-site WebSocket dari halaman web lain).

Endpoint:
  GET /            dashboard (dashboard/index.html) + aset statis di /assets/*
  GET /video       stream MJPEG (frame sudah di-mirror, sejajar dengan landmark); berhenti saat kamera dimatikan
  GET /healthz     {"status":"ok"} untuk pemeriksaan kesehatan
  GET /api/state   snapshot JSON
  GET /api/config  tabel nada, instrumen, parameter (UI membaca ini; sinkron dengan config.py)
  WS  /ws          server -> {"type":"state", ...snapshot} ~30 Hz (instrument, note, minor_active, camera_enabled, hands, ...)
                   client -> {"type":"config","debounce_ms":..,"resolution":"640x480","instrument":"piano|violin","camera":true|false}

Semua respons diberi header keamanan (CSP ketat tanpa inline script/style, nosniff, frame-ancestors none, no-referrer).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import config
from pipeline import SharedState

log = logging.getLogger("musicozie.server")

ALLOWED_HOSTNAMES = {"127.0.0.1", "localhost", "[::1]", "::1"}


def host_allowed(host_header: str | None) -> bool:
    if not host_header:
        return False
    return host_header.rsplit(":", 1)[0].lower() in ALLOWED_HOSTNAMES if ":" in host_header else host_header.lower() in ALLOWED_HOSTNAMES


def origin_allowed(origin: str | None) -> bool:
    """Tanpa Origin (klien non-browser) diizinkan; dengan Origin harus loopback."""
    if not origin:
        return True
    return (urlparse(origin).hostname or "").lower() in ALLOWED_HOSTNAMES


SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
        "connect-src 'self' ws://127.0.0.1:* ws://localhost:*; "
        "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",  # kamera dibaca server Python, bukan browser
    "Cross-Origin-Opener-Policy": "same-origin",
}


def apply_client_message(state: SharedState, msg: dict) -> str | None:
    """Terapkan pesan dari dashboard. Return pesan error atau None."""
    kind = msg.get("type")
    if kind == "config":
        if "camera" in msg and not isinstance(msg["camera"], bool):
            return "invalid config: camera must be true or false"
        try:
            state.configure(
                debounce_ms=msg.get("debounce_ms"),
                resolution=msg.get("resolution"),
                instrument=msg.get("instrument"),
                camera=msg.get("camera"),
            )
        except (TypeError, ValueError):
            return "invalid config"
        return None
    return "unknown message type"


def create_app(state: SharedState) -> FastAPI:
    app = FastAPI(title="Musicozie", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard_host(request, call_next):
        if not host_allowed(request.headers.get("host")):
            return JSONResponse({"error": "host not allowed"}, status_code=403, headers=SECURITY_HEADERS)
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-cache"  # selalu revalidasi (ETag), aman saat update
        return response

    assets_dir = config.DASHBOARD_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/")
    async def index():
        page = config.DASHBOARD_DIR / "index.html"
        if not page.exists():
            return Response("dashboard/index.html not found", status_code=404)
        return FileResponse(page, headers={"Cache-Control": "no-store"})

    @app.get("/api/config")
    async def api_config():
        """Sumber kebenaran untuk UI: panduan gestur, instrumen, dan parameter dibaca dari file Python."""
        from gesture_matrix import solfege_table
        from instrument_modes import MODES
        from pipeline import RESOLUTIONS

        return {
            "solfege": solfege_table(),
            "minor_shift": config.MINOR_SHIFT,
            "minor_trigger": "".join(str(b) for b in config.MINOR_TRIGGER),
            "melody_hand": config.MELODY_HAND,
            "modifier_hand": config.MODIFIER_HAND,
            "finger_labels": ["T", "I", "M", "R", "P"],
            "instruments": [
                {"key": m.key, "label": m.label, "program": m.program, "sustained": m.sustained, "vibrato": m.vibrato}
                for m in MODES.values()
            ],
            "default_instrument": config.DEFAULT_INSTRUMENT,
            "mode_switch_hold_s": config.MODE_SWITCH_HOLD_S,
            "vibrato": {"rate_hz": config.VIBRATO_RATE_HZ, "depth_cents": config.VIBRATO_DEPTH_CENTS, "delay_s": config.VIBRATO_DELAY_S},
            "debounce_ms": config.DEBOUNCE_MS,
            "resolutions": list(RESOLUTIONS),
            "app": {"name": "Musicozie", "version": config.VERSION},
        }

    @app.get("/api/state")
    async def api_state():
        return state.snapshot()

    @app.get("/video")
    async def video():
        async def gen():
            last = -1
            while not state.stop_event.is_set() and state.camera_enabled:  # kamera dimatikan -> stream berakhir
                fid, jpeg = state.get_jpeg()
                if jpeg is None or fid == last:
                    await asyncio.sleep(0.01)
                    continue
                last = fid
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"

        return StreamingResponse(
            gen(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store"},
        )

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        if not origin_allowed(websocket.headers.get("origin")) or not host_allowed(websocket.headers.get("host")):
            await websocket.close(code=1008)
            return
        await websocket.accept()

        async def sender():
            period = 1.0 / config.WS_HZ
            while not state.stop_event.is_set():
                await websocket.send_text(json.dumps({"type": "state", **state.snapshot()}))
                await asyncio.sleep(period)

        send_task = asyncio.create_task(sender())
        try:
            while True:
                try:
                    msg = json.loads(await websocket.receive_text())
                except json.JSONDecodeError:
                    await websocket.send_text(json.dumps({"type": "error", "message": "invalid JSON"}))
                    continue
                if not isinstance(msg, dict):
                    continue
                err = apply_client_message(state, msg)
                if err:
                    await websocket.send_text(json.dumps({"type": "error", "message": err}))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            send_task.cancel()

    return app


class ServerThread(threading.Thread):
    def __init__(self, state: SharedState, port: int = config.SERVER_PORT):
        super().__init__(name="server", daemon=True)
        import uvicorn

        self.state = state
        self.server = uvicorn.Server(
            uvicorn.Config(
                create_app(state),
                host=config.SERVER_HOST,  # loopback saja
                port=port,
                log_level="warning",
                ws_ping_interval=None,
                timeout_graceful_shutdown=2,
            )
        )

    def run(self) -> None:
        try:
            self.server.run()
        except SystemExit:
            self.state.set_status("error", "Server gagal start (port dipakai?)")
            log.error("Server gagal start; coba --port lain")

    def stop(self) -> None:
        self.server.should_exit = True
        self.join(timeout=4)
