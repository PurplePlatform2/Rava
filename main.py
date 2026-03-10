import asyncio
import os
from functools import lru_cache
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

import yt_dlp

app = FastAPI(title="YouTube Audio Backend")

# ==============================
# CORS
# ==============================

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

CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

SEARCH_LIMIT = 10
MAX_CACHE_FILES = 50

# ==============================
# yt-dlp configurations
# ==============================

SEARCH_OPTS = {
    "quiet": True,
    "skip_download": True,
    "extract_flat": "in_playlist",
    "socket_timeout": 10
}

INFO_OPTS = {
    "quiet": True,
    "socket_timeout": 10
}

DOWNLOAD_OPTS = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "outtmpl": f"{CACHE_DIR}/%(id)s.%(ext)s",
    "quiet": True,
    "noplaylist": True,
    "socket_timeout": 10
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

# ==============================
# Search
# ==============================

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

# ==============================
# Extract Audio Stream URL
# ==============================

@lru_cache(maxsize=200)
def extract_audio_url(video_id: str):

    url = f"https://www.youtube.com/watch?v={video_id}"

    with yt_dlp.YoutubeDL(INFO_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)

    formats = info.get("formats", [])

    for f in formats:
        if f.get("vcodec") == "none" and f.get("acodec") != "none":
            return f["url"]

    raise Exception("Audio stream not found")

# ==============================
# Download Audio
# ==============================

def download_audio(video_id: str):

    cleanup_cache()

    with yt_dlp.YoutubeDL(DOWNLOAD_OPTS) as ydl:

        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}",
            download=True
        )

        filepath = ydl.prepare_filename(info)

    return filepath

# ==============================
# Routes
# ==============================

@app.get("/")
def home():
    return {"status": "running"}

# ------------------------------

@app.get("/search")
async def search(q: str):

    if not q:
        raise HTTPException(400, "Query required")

    try:
        results = await run_blocking(yt_search, q)
        return JSONResponse(results)

    except Exception as e:
        raise HTTPException(500, str(e))

# ------------------------------

@app.get("/audio")
async def stream_audio(video_id: str):

    if not video_id:
        raise HTTPException(400, "video_id required")

    try:
        audio_url = await run_blocking(extract_audio_url, video_id)
        return {"audio_url": audio_url}

    except Exception as e:
        raise HTTPException(500, str(e))

# ------------------------------

@app.get("/download")
async def download(video_id: str):

    if not video_id:
        raise HTTPException(400, "video_id required")

    try:

        # check cache first
        for f in os.listdir(CACHE_DIR):
            if f.startswith(video_id):
                path = os.path.join(CACHE_DIR, f)
                return FileResponse(
                    path,
                    media_type="audio/mpeg",
                    filename=f
                )

        filepath = await run_blocking(download_audio, video_id)

        return FileResponse(
            filepath,
            media_type="audio/mpeg",
            filename=os.path.basename(filepath)
        )

    except Exception as e:
        raise HTTPException(500, str(e))
