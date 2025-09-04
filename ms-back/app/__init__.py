from fastapi import FastAPI
from threading import Thread
import time
from app.settings import settings
from app.storage import init_db
from app.ingestors import rss
from app.signal import compute_once

app = FastAPI()

def rss_loop():
    while True:
        rss.run_once()
        time.sleep(settings.poll_seconds)

def signal_loop():
    while True:
        compute_once()
        time.sleep(settings.poll_seconds)

@app.on_event("startup")
def on_startup():
    init_db()
    Thread(target=rss_loop, daemon=True).start()
    Thread(target=signal_loop, daemon=True).start()

@app.get("/health")
def health():
    return {"ok": True}
