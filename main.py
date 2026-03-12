import asyncio
import time
import random
import logging
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import yt_dlp

# =========================
# Logging
# =========================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("rava")

# =========================
# FastAPI
# =========================
app = FastAPI(title="RAVA Audio API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Config
# =========================
STREAM_CACHE: Dict[str, Dict] = {}
STREAM_TTL = 7200
SEARCH_LIMIT = 12

# =========================
# yt-dlp config
# =========================
BASE_OPTS = {
    "quiet": True,
    "skip_download": True,
    "socket_timeout": 20,
    "retries": 3,
    "nocheckcertificate": True,
    "http_headers": {
        "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        " AppleWebKit/537.36 (KHTML, like Gecko)"
        " Chrome/121.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    },
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"],
            "skip": ["dash", "hls"]
        }
    }
}

SEARCH_OPTS = {
    **BASE_OPTS,
    "extract_flat": True
}

# =========================
# Async executor
# =========================
async def run_blocking(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)

# =========================
# Cache helpers
# =========================
def get_cached_stream(video_id):
    c = STREAM_CACHE.get(video_id)

    if not c:
        return None

    if time.time() > c["exp"]:
        STREAM_CACHE.pop(video_id, None)
        return None

    return c["url"]


def set_cached_stream(video_id, url):
    STREAM_CACHE[video_id] = {
        "url": url,
        "exp": time.time() + STREAM_TTL
    }

# =========================
# Extract audio stream
# =========================
def extract_stream(video_id):

    cached = get_cached_stream(video_id)
    if cached:
        return cached

    url = f"https://youtube.com/watch?v={video_id}"

    time.sleep(random.uniform(0.3, 1.0))

    with yt_dlp.YoutubeDL(BASE_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)

    for f in info["formats"]:
        if f.get("vcodec") == "none" and f.get("acodec") != "none":
            stream = f["url"]
            set_cached_stream(video_id, stream)
            return stream

    raise Exception("No audio stream found")

# =========================
# YouTube search
# =========================
def yt_search(query):

    time.sleep(random.uniform(0.3, 1.0))

    with yt_dlp.YoutubeDL(SEARCH_OPTS) as ydl:
        data = ydl.extract_info(
            f"ytsearch{SEARCH_LIMIT}:{query}",
            download=False
        )

    results = []

    for v in data.get("entries", []):

        thumb = None
        if v.get("thumbnails"):
            thumb = v["thumbnails"][-1]["url"]

        results.append({
            "id": v.get("id"),
            "title": v.get("title"),
            "thumbnail": thumb,
            "duration": v.get("duration"),
            "channel": v.get("uploader")
        })

    return results

# =========================
# Routes
# =========================
@app.get("/")
async def home():
    return {"status": "running"}

@app.get("/search")
async def search(q: str):

    if not q:
        raise HTTPException(400, "Query required")

    try:
        return await run_blocking(yt_search, q)

    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/stream")
async def stream(video_id: str):

    if not video_id:
        raise HTTPException(400, "video_id required")

    try:
        url = await run_blocking(extract_stream, video_id)
        return {"audio_url": url}

    except Exception as e:
        raise HTTPException(500, f"Stream failed: {e}")

# =========================
# Start server
# =========================
if __name__ == "__main__":

    import uvicorn

    port = int(os.environ.get("PORT",8000))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )
