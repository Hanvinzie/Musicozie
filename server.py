"""Server web FastAPI/Uvicorn untuk Musicozie dashboard dan WebSocket."""
import asyncio
import json
import struct
import threading
import zlib

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import config
from gesture_matrix import solfege_table

app = FastAPI(title="Musicozie API")

# Keamanan Host & CORS untuk Deployment Cloud (Render)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serving static dashboard files
if config.DASHBOARD_DIR.exists():
    assets_dir = config.DASHBOARD_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

# Model HandLandmarker untuk MediaPipe di browser (hanya folder models/ yang dibuka, berisi file .task).
if config.HAND_MODEL_PATH.parent.exists():
    app.mount("/models", StaticFiles(directory=config.HAND_MODEL_PATH.parent), name="models")


# --------------------------------------------------------------------------- Helper
def _build_transparent_png() -> bytes:
    """Bangun PNG RGBA 1x1 piksel sepenuhnya transparan (tanpa dependensi tambahan)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)  # 1x1, 8-bit, RGBA
    pixel_row = b"\x00" + b"\x00\x00\x00\x00"              # filter byte + RGBA(0,0,0,0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(pixel_row))
        + chunk(b"IEND", b"")
    )


TRANSPARENT_PNG = _build_transparent_png()
NO_CACHE = {"Cache-Control": "no-store, max-age=0"}
MJPEG_BOUNDARY = "frame"


def _get_state():
    """SharedState milik pipeline (None jika server dijalankan tanpa pipeline)."""
    server_thread = getattr(app.state, "server_thread", None)
    return server_thread.state if server_thread else None


def _fallback_snapshot() -> dict:
    """Snapshot lengkap saat pipeline belum terpasang, supaya dashboard tidak menampilkan 'undefined'."""
    return {
        "type": "state",
        "status": "ok",
        "message": "",
        "camera_enabled": True,
        "client_camera": True,
        "has_video": False,
        "fps": 0.0,
        "latency_ms": 0.0,
        "debounce_ms": config.DEBOUNCE_MS,
        "resolution": "640x480",
        "hands": [],
        "instrument": config.DEFAULT_INSTRUMENT,
        "mode_label": config.DEFAULT_INSTRUMENT.upper(),
        "switch_progress": 0.0,
        "minor_active": False,
        "note": None,
    }


def _snapshot(state) -> dict:
    if state is None:
        return _fallback_snapshot()
    snap = state.snapshot()
    snap["type"] = "state"
    return snap


async def _mjpeg_stream(state, first_id: int, first_jpeg: bytes):
    """Stream multipart/x-mixed-replace: kirim frame baru setiap frame_id berubah."""
    frame_id, jpeg = first_id, first_jpeg
    interval = 1.0 / max(config.WS_HZ, 1)
    while True:
        yield (
            b"--" + MJPEG_BOUNDARY.encode() + b"\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
            + jpeg + b"\r\n"
        )
        while True:
            await asyncio.sleep(interval)
            if state.stop_event.is_set() or not state.camera_enabled:
                return  # kamera dimatikan / server berhenti -> akhiri stream
            new_id, new_jpeg = state.get_jpeg()
            if new_jpeg and new_id != frame_id:
                frame_id, jpeg = new_id, new_jpeg
                break


# --------------------------------------------------------------------------- HTTP
@app.get("/")
async def read_root():
    """Melayani halaman utama dashboard."""
    index_file = config.DASHBOARD_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Musicozie Backend is running!"}


@app.get("/health")
async def health_check():
    """Endpoint pengecekan status server."""
    return {"status": "ok", "version": config.VERSION}


@app.get("/video")
async def video_feed():
    """Feed video dari kamera SERVER (hanya ada saat server punya kamera fisik).

    - Ada frame di SharedState -> stream MJPEG (multipart/x-mixed-replace).
    - Tidak ada frame (mis. di Render, kamera ada di browser) -> PNG transparan 1x1, status 200,
      sehingga browser tidak mencetak error 204 No Content berulang kali.
    """
    state = _get_state()
    if state is not None and state.camera_enabled:
        frame_id, jpeg = state.get_jpeg()
        if jpeg:
            return StreamingResponse(
                _mjpeg_stream(state, frame_id, jpeg),
                media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
                headers=NO_CACHE,
            )
    return Response(content=TRANSPARENT_PNG, media_type="image/png", headers=NO_CACHE)


@app.get("/api/config")
async def get_config():
    """Mengembalikan konfigurasi global ke frontend dashboard."""
    return {
        "minor_shift": config.MINOR_SHIFT,
        "minor_trigger": "".join(map(str, config.MINOR_TRIGGER)),
        "melody_hand": config.MELODY_HAND,
        "modifier_hand": config.MODIFIER_HAND,
        "mode_switch_hold_s": config.MODE_SWITCH_HOLD_S,
        "vibrato": {
            "rate_hz": config.VIBRATO_RATE_HZ,
            "depth_cents": config.VIBRATO_DEPTH_CENTS,
            "delay_s": config.VIBRATO_DELAY_S,
            "ramp_s": config.VIBRATO_RAMP_S,
        },
        # Ambang deteksi untuk engine di browser (dashboard/assets/engine.js), supaya sama dengan Python.
        "vision": {
            "open_ratio": config.OPEN_RATIO,
            "thumb_tuck_ratio": config.THUMB_TUCK_RATIO,
            "min_hand_score": config.MIN_HAND_SCORE,
            "debounce_ms": config.DEBOUNCE_MS,
            "lost_grace_ms": config.LOST_GRACE_MS,
            "melody_velocity": config.MELODY_VELOCITY,
        },
        "instruments": [
            {"key": "piano", "label": "PIANO", "program": config.PIANO_PROGRAM, "sustained": False, "vibrato": False},
            {"key": "violin", "label": "VIOLIN", "program": config.VIOLIN_PROGRAM, "sustained": True, "vibrato": True},
        ],
        "default_instrument": config.DEFAULT_INSTRUMENT,
        "solfege": solfege_table(),
        "app": {"version": config.VERSION},
    }


# --------------------------------------------------------------------------- WebSocket
async def _receive_loop(websocket: WebSocket, state, outbox: "asyncio.Queue") -> None:
    """Terima pesan {"type": "config", ...} dari dashboard (kamera, instrumen, debounce, resolusi)."""
    while True:
        raw = await websocket.receive_text()  # WebSocketDisconnect -> loop berhenti
        try:
            msg = json.loads(raw)
        except ValueError:
            outbox.put_nowait({"type": "error", "message": "invalid json"})
            continue
        if not isinstance(msg, dict) or msg.get("type") != "config":
            outbox.put_nowait({"type": "error", "message": "unknown message type"})
            continue
        if state is None:
            continue
        try:
            state.configure(
                debounce_ms=msg.get("debounce_ms"),
                resolution=msg.get("resolution"),
                instrument=msg.get("instrument"),
                camera=msg.get("camera"),
            )
        except (TypeError, ValueError):
            outbox.put_nowait({"type": "error", "message": "invalid config value"})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Kirim snapshot status realtime (WS_HZ per detik) dan terima perintah config dari dashboard."""
    await websocket.accept()
    state = _get_state()
    outbox: asyncio.Queue = asyncio.Queue()
    receiver = asyncio.create_task(_receive_loop(websocket, state, outbox))

    try:
        while not receiver.done():
            while not outbox.empty():
                await websocket.send_json(outbox.get_nowait())
            await websocket.send_json(_snapshot(state))
            await asyncio.sleep(1.0 / config.WS_HZ)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"WebSocket Client Error: {e}")
    finally:
        receiver.cancel()


class ServerThread(threading.Thread):
    """Thread khusus untuk menjalankan server Uvicorn tanpa mengunci main thread."""
    def __init__(self, state, port: int):
        super().__init__(daemon=True)
        self.state = state
        self.port = port
        self.server = None
        app.state.server_thread = self

    def run(self):
        uvicorn_config = uvicorn.Config(
            app=app,
            host=config.HOST,
            port=self.port,
            ws_per_message_deflate=False,
            log_level="info"
        )
        self.server = uvicorn.Server(uvicorn_config)
        self.server.run()

    def stop(self):
        if self.server:
            self.server.should_exit = True