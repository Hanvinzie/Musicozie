"""Server web FastAPI/Uvicorn untuk Musicozie dashboard dan WebSocket."""   
import threading   
import asyncio  
import json  
import uvicorn   
from fastapi import FastAPI, WebSocket, WebSocketDisconnect  
from fastapi.middleware.cors import CORSMiddleware   
from fastapi.middleware.trustedhost import TrustedHostMiddleware   
from fastapi.staticfiles import StaticFiles   
from fastapi.responses import FileResponse, Response
import config

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
    """Endpoint feed video camera (mengembalikan frame dari SharedState jika ada)."""
    server_thread = getattr(app.state, "server_thread", None)
    if server_thread and server_thread.state:
        _, jpeg = server_thread.state.get_jpeg()
        if jpeg:
            return Response(content=jpeg, media_type="image/jpeg")
    return Response(status_code=204)

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
        },  
        "instruments": [  
            {"key": "piano", "label": "PIANO", "program": config.PIANO_PROGRAM, "sustained": False, "vibrato": False},  
            {"key": "violin", "label": "VIOLIN", "program": config.VIOLIN_PROGRAM, "sustained": True, "vibrato": True},  
        ],  
        "default_instrument": config.DEFAULT_INSTRUMENT,  
        "solfege": [  
            {"name": name, "midi": midi, "code": "".join(map(str, code)), "description": name}  
            for code, (name, midi) in config.SOLFEGE.items()  
        ],  
        "app": {"version": config.VERSION}  
    }

# Fix WebSocket 403 Forbidden dengan WebSocket Endpoint Handler
@app.websocket("/ws")  
async def websocket_endpoint(websocket: WebSocket):  
    await websocket.accept()  
    
    server_thread = getattr(app.state, "server_thread", None)  
    state = server_thread.state if server_thread else None

    try:  
        while True:  
            if state:  
                snapshot = state.snapshot()  
                snapshot["type"] = "state"  
                await websocket.send_json(snapshot)  
            else:  
                await websocket.send_json({"type": "state", "status": "ok", "hands": [], "camera_enabled": True})  
            
            await asyncio.sleep(1.0 / config.WS_HZ)  
            
    except WebSocketDisconnect:  
        pass  
    except Exception as e:  
        print(f"WebSocket Client Error: {e}")

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