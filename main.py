import asyncio
import os
import logging
import time
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

import yt_dlp

# ===============================
# Logging
# ===============================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("yt-audio-server")

# ===============================
# FastAPI App
# ===============================
app = FastAPI(title="YouTube Audio Streaming API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===============================
# Config
# ===============================
CACHE_DIR = os.environ.get("CACHE_DIR", "/tmp/audio-cache")
os.makedirs(CACHE_DIR, exist_ok=True)

SEARCH_LIMIT = 10
PREFETCH_COUNT = 3
MAX_CACHE_FILES = 40

# Stream URL cache (video_id → data)
STREAM_CACHE: Dict[str, Dict] = {}

STREAM_TTL = 60 * 60 * 3  # 3 hours

# ===============================
# yt-dlp Options
# ===============================
BASE_YTDLP_OPTS = {
    "quiet": True,
    "socket_timeout": 15,
    "extractor_args": {
        "youtube": {
            "player_client": ["android"]
        }
    }
}

SEARCH_OPTS = {
    **BASE_YTDLP_OPTS,
    "skip_download": True,
    "extract_flat": "in_playlist"
}

INFO_OPTS = {
    **BASE_YTDLP_OPTS
}

DOWNLOAD_OPTS = {
    **BASE_YTDLP_OPTS,
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "outtmpl": f"{CACHE_DIR}/%(id)s.%(ext)s",
    "noplaylist": True
}

# ===============================
# Async helper
# ===============================
async def run_blocking(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)

# ===============================
# Cache cleanup
# ===============================
def cleanup_cache():
    try:
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
    except Exception as e:
        log.warning(f"Cache cleanup error: {e}")

# ===============================
# Stream Cache Helpers
# ===============================
def get_cached_stream(video_id):

    data = STREAM_CACHE.get(video_id)

    if not data:
        return None

    if time.time() > data["expires"]:
        del STREAM_CACHE[video_id]
        return None

    return data["url"]


def set_cached_stream(video_id, url):

    STREAM_CACHE[video_id] = {
        "url": url,
        "expires": time.time() + STREAM_TTL
    }

# ===============================
# Extract audio stream
# ===============================
def extract_audio_stream(video_id):

    cached = get_cached_stream(video_id)
    if cached:
        return cached

    url = f"https://www.youtube.com/watch?v={video_id}"

    with yt_dlp.YoutubeDL(INFO_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)

    for f in info.get("formats", []):
        if f.get("vcodec") == "none" and f.get("acodec") != "none":
            stream_url = f["url"]
            set_cached_stream(video_id, stream_url)
            return stream_url

    raise Exception("Audio stream not found")

# ===============================
# Prefetch streams
# ===============================
async def prefetch_streams(results):

    for v in results[:PREFETCH_COUNT]:

        vid = v.get("id")

        if vid in STREAM_CACHE:
            continue

        try:
            await run_blocking(extract_audio_stream, vid)
        except:
            pass

# ===============================
# YouTube Search
# ===============================
def yt_search(query: str) -> List[Dict]:

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

# ===============================
# Download audio
# ===============================
def download_audio(video_id):

    cleanup_cache()

    with yt_dlp.YoutubeDL(DOWNLOAD_OPTS) as ydl:

        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}",
            download=True
        )

        path = ydl.prepare_filename(info)

    return path

# ===============================
# Routes
# ===============================

@app.get("/")
def home():
    return {"status": "running"}

# -------------------------------

@app.get("/search")
async def search(q: str):

    if not q:
        raise HTTPException(400, "Query required")

    try:
        results = await run_blocking(yt_search, q)

        # Prefetch streams asynchronously
        asyncio.create_task(prefetch_streams(results))

        return JSONResponse(results)

    except Exception as e:
        raise HTTPException(500, f"Search failed: {e}")

# -------------------------------

@app.get("/stream")
async def stream(video_id: str):

    if not video_id:
        raise HTTPException(400, "video_id required")

    try:

        url = await run_blocking(extract_audio_stream, video_id)

        return {
            "audio_url": url,
            "cached": True
        }

    except Exception as e:
        raise HTTPException(500, f"Stream extraction failed: {e}")

# -------------------------------

@app.get("/download")
async def download(video_id: str):

    if not video_id:
        raise HTTPException(400, "video_id required")

    try:

        for f in os.listdir(CACHE_DIR):

            if f.startswith(video_id):

                path = os.path.join(CACHE_DIR, f)

                return FileResponse(
                    path,
                    filename=os.path.basename(path),
                    media_type="audio/mpeg"
                )

        path = await run_blocking(download_audio, video_id)

        return FileResponse(
            path,
            filename=os.path.basename(path),
            media_type="audio/mpeg"
        )

    except Exception as e:
        raise HTTPException(500, f"Download failed: {e}")

# ===============================
# Run Server
# ===============================
if __name__ == "__main__":

    import uvicorn

    port = int(os.environ.get("PORT", 8000))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
