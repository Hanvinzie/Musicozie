from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

app = FastAPI()

# Izinkan Host dari Domain Render & Localhost
app.add_middleware(
    TrustedHostMiddleware, 
    allowed_hosts=["*"]
)

# Izinkan CORS penuh untuk WebSocket & API request dari Browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)