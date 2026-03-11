import asyncio
import os
import time
import random
import logging
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
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
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Config
# =========================
CACHE_DIR = "/tmp/audio-cache"
os.makedirs(CACHE_DIR, exist_ok=True)

STREAM_CACHE: Dict[str, Dict] = {}

STREAM_TTL = 7200
MAX_CACHE_FILES = 40
SEARCH_LIMIT = 12

# =========================
# yt-dlp Anti Bot Setup
# =========================
BASE_OPTS = {
    "quiet": True,
    "nocheckcertificate": True,
    "socket_timeout": 20,
    "retries": 5,

    "http_headers": {
        "User-Agent":
        "Mozilla/5.0 (Linux; Android 13; Pixel 7)"
        " AppleWebKit/537.36 (KHTML, like Gecko)"
        " Chrome/121 Mobile Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    },

    "extractor_args": {
        "youtube": {
            "player_client": [
                "android",
                "tv_embedded",
                "web"
            ],
            "player_skip": ["configs"],
            "skip": ["dash", "hls"]
        }
    }
}

SEARCH_OPTS = {
    **BASE_OPTS,
    "extract_flat": True,
    "skip_download": True
}

DOWNLOAD_OPTS = {
    **BASE_OPTS,
    "format": "bestaudio/best",
    "noplaylist": True,
    "outtmpl": f"{CACHE_DIR}/%(id)s.%(ext)s"
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
# Cleanup audio cache
# =========================
def cleanup_cache():

    files = sorted(
        [os.path.join(CACHE_DIR, f) for f in os.listdir(CACHE_DIR)],
        key=os.path.getmtime
    )

    if len(files) > MAX_CACHE_FILES:

        for f in files[:len(files) - MAX_CACHE_FILES]:

            try:
                os.remove(f)
            except:
                pass

# =========================
# Extract stream
# =========================
def extract_stream(video_id):

    cached = get_cached_stream(video_id)

    if cached:
        return cached

    url = f"https://youtube.com/watch?v={video_id}"

    time.sleep(random.uniform(0.6, 1.6))

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

    time.sleep(random.uniform(0.5, 1.3))

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
# Download audio
# =========================
def download_audio(video_id):

    cleanup_cache()

    url = f"https://youtube.com/watch?v={video_id}"

    time.sleep(random.uniform(0.7, 1.8))

    with yt_dlp.YoutubeDL(DOWNLOAD_OPTS) as ydl:

        info = ydl.extract_info(url, download=True)

        return ydl.prepare_filename(info)

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

@app.get("/download")
async def download(video_id: str):

    if not video_id:
        raise HTTPException(400, "video_id required")

    try:

        for f in os.listdir(CACHE_DIR):

            if f.startswith(video_id):

                path = os.path.join(CACHE_DIR, f)

                return FileResponse(path, filename=f)

        path = await run_blocking(download_audio, video_id)

        return FileResponse(
            path,
            filename=os.path.basename(path)
        )

    except Exception as e:
        raise HTTPException(500, f"Download failed: {e}")

# =========================
# Prefetch next audio
# =========================
@app.post("/prefetch")
async def prefetch(video_ids: List[str]):

    tasks = [
        run_blocking(extract_stream, vid)
        for vid in video_ids[:5]
    ]

    asyncio.create_task(asyncio.gather(*tasks))

    return {"status": "prefetch started"}

# =========================
# Start server
# =========================
if __name__ == "__main__":

    import uvicorn

    port = int(os.environ.get("PORT", 8000))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )
