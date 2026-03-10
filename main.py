import asyncio
import os
import logging
from functools import lru_cache
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

import yt_dlp

# ==============================
# Logging
# ==============================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yt-audio-backend")

# ==============================
# FastAPI App
# ==============================
app = FastAPI(title="YouTube Audio Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================
# Configuration
# ==============================
CACHE_DIR = os.environ.get("CACHE_DIR", "/tmp/cache")
os.makedirs(CACHE_DIR, exist_ok=True)

SEARCH_LIMIT = 10
MAX_CACHE_FILES = 50

# ==============================
# yt-dlp configurations
# ==============================
SEARCH_OPTS = {"quiet": True, "skip_download": True, "extract_flat": "in_playlist", "socket_timeout": 10}
INFO_OPTS = {"quiet": True, "socket_timeout": 10}
DOWNLOAD_OPTS = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "outtmpl": f"{CACHE_DIR}/%(id)s.%(ext)s",
    "quiet": True,
    "noplaylist": True,
    "socket_timeout": 10,
}

# ==============================
# Async utility
# ==============================
async def run_blocking(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)

# ==============================
# Cache cleanup
# ==============================
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
                    logger.info(f"Removed cached file: {f}")
                except OSError as e:
                    logger.warning(f"Failed to remove cache file {f}: {e}")
    except Exception as e:
        logger.error(f"Cache cleanup error: {e}")

# ==============================
# Search
# ==============================
def yt_search(query: str) -> List[Dict]:
    try:
        with yt_dlp.YoutubeDL(SEARCH_OPTS) as ydl:
            data = ydl.extract_info(f"ytsearch{SEARCH_LIMIT}:{query}", download=False)

        results = []
        for v in data.get("entries", []):
            thumb = v.get("thumbnails", [{}])[-1].get("url") if v.get("thumbnails") else None
            results.append({
                "id": v.get("id"),
                "title": v.get("title"),
                "thumbnail": thumb,
                "duration": v.get("duration"),
                "channel": v.get("uploader")
            })
        return results
    except Exception as e:
        logger.error(f"Search error for query '{query}': {e}")
        raise

# ==============================
# Extract Audio Stream URL
# ==============================
@lru_cache(maxsize=200)
def extract_audio_url(video_id: str):
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        with yt_dlp.YoutubeDL(INFO_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
        for f in info.get("formats", []):
            if f.get("vcodec") == "none" and f.get("acodec") != "none":
                return f["url"]
        raise Exception("Audio stream not found")
    except Exception as e:
        logger.error(f"Extract audio error for video_id '{video_id}': {e}")
        raise

# ==============================
# Download Audio
# ==============================
def download_audio(video_id: str) -> str:
    cleanup_cache()
    try:
        with yt_dlp.YoutubeDL(DOWNLOAD_OPTS) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
            filepath = ydl.prepare_filename(info)
        return filepath
    except Exception as e:
        logger.error(f"Download error for video_id '{video_id}': {e}")
        raise

# ==============================
# Routes
# ==============================
@app.get("/")
def home():
    return {"status": "running"}

@app.get("/search")
async def search(q: str):
    if not q:
        raise HTTPException(400, "Query required")
    try:
        results = await run_blocking(yt_search, q)
        return JSONResponse(results)
    except Exception as e:
        raise HTTPException(500, f"Search failed: {e}")

@app.get("/audio")
async def stream_audio(video_id: str):
    if not video_id:
        raise HTTPException(400, "video_id required")
    try:
        audio_url = await run_blocking(extract_audio_url, video_id)
        return {"audio_url": audio_url}
    except Exception as e:
        raise HTTPException(500, f"Audio stream failed: {e}")

@app.get("/download")
async def download(video_id: str):
    if not video_id:
        raise HTTPException(400, "video_id required")
    try:
        # Check cache first
        for f in os.listdir(CACHE_DIR):
            if f.startswith(video_id):
                path = os.path.join(CACHE_DIR, f)
                media_type = "audio/mpeg" if path.endswith(".mp3") else "audio/mp4"
                return FileResponse(path, media_type=media_type, filename=os.path.basename(path))

        # Download new audio
        filepath = await run_blocking(download_audio, video_id)
        media_type = "audio/mpeg" if filepath.endswith(".mp3") else "audio/mp4"
        return FileResponse(filepath, media_type=media_type, filename=os.path.basename(filepath))
    except Exception as e:
        raise HTTPException(500, f"Download failed: {e}")

# ==============================
# Run app
# ==============================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))  # Render Free dynamic port
    uvicorn.run(app, host="0.0.0.0", port=port)
