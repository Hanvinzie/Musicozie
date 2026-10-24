"""Server web FastAPI/Uvicorn untuk Musicozie dashboard dan WebSocket."""
import threading
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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

class ServerThread(threading.Thread):
    """Thread khusus untuk menjalankan server Uvicorn tanpa mengunci main thread."""
    def __init__(self, state, port: int):
        super().__init__(daemon=True)
        self.state = state
        self.port = port
        self.server = None

    def run(self):
        uvicorn_config = uvicorn.Config(
            app=app,
            host=config.HOST,
            port=self.port,
            log_level="info"
        )
        self.server = uvicorn.Server(uvicorn_config)
        self.server.run()

    def stop(self):
        if self.server:
            self.server.should_exit = True