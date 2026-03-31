"""
Imprint — Search API Server
FastAPI server exposing /search and /health endpoints on localhost:8000.
"""

import logging

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from config import ERROR_LOG, ensure_api_key, get_watch_dirs, load_config
from embedder import search, get_indexed_count

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=str(ERROR_LOG),
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ─── FastAPI App ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="Imprint Search API",
    description="Local semantic memory search engine",
    version="1.0.0",
)

# Allow local connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/search")
async def search_endpoint(
    q: str = Query(..., description="Search query string"),
    n: int = Query(12, ge=1, le=100, description="Number of results"),
):
    """
    Search indexed files by semantic similarity.
    Returns JSON array of {path, name, score}.
    """
    try:
        results = search(q, n=n)
        return JSONResponse(content=results)
    except Exception as e:
        logging.error(f"Search endpoint error: {e}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500,
        )


@app.get("/health")
async def health_endpoint():
    """Health check with indexed file count."""
    try:
        count = get_indexed_count()
        return {"status": "ok", "indexed": count}
    except Exception as e:
        logging.error(f"Health endpoint error: {e}")
        return {"status": "error", "message": str(e), "indexed": 0}


@app.get("/config")
async def config_endpoint():
    """Return current configuration (watch dirs, etc.)."""
    try:
        cfg = load_config()
        dirs = [str(d) for d in get_watch_dirs()]
        return {
            "watch_dirs": dirs,
            "indexed_count": get_indexed_count(),
            "batch_size": cfg.get("batch_size", 50),
        }
    except Exception as e:
        return {"error": str(e)}



