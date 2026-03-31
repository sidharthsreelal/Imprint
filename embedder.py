"""
Imprint — Core Embedding & Search Engine
Handles file embedding via Gemini API and semantic search via ChromaDB.
"""

import base64
import hashlib
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from google import genai
from google.genai import types

from config import (
    CHROMA_DIR,
    ERROR_LOG,
    MAX_FILE_BYTES,
    SQLITE_CACHE,
    SUPPORTED_EXTENSIONS,
    ensure_api_key,
    get_api_key,
)

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=str(ERROR_LOG),
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ─── MIME mapping ────────────────────────────────────────────────────────────
MIME_MAP: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".txt": "text/plain",
    ".md": "text/plain",
}

# Text-only extensions (can be embedded directly as text)
TEXT_EXTENSIONS = {".txt", ".md"}

# ─── Gemini client (lazy-initialized) ────────────────────────────────────────
_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Get or initialize the Gemini API client."""
    global _client
    if _client is None:
        api_key = get_api_key()
        if not api_key:
            raise RuntimeError(
                "No Gemini API key configured. "
                "Run 'python config.py set-key' or 'python start.py' to set it up."
            )
        _client = genai.Client(api_key=api_key)
    return _client


def reset_client() -> None:
    """Reset the client (e.g. after API key change)."""
    global _client
    _client = None


# ─── ChromaDB (lazy-initialized) ────────────────────────────────────────────
_chroma_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None


def _get_collection() -> chromadb.Collection:
    """Get or initialize the ChromaDB collection."""
    global _chroma_client, _collection
    if _collection is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = _chroma_client.get_or_create_collection(
            name="memories",
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


# ─── SQLite Index Cache ─────────────────────────────────────────────────────

def _get_cache_conn() -> sqlite3.Connection:
    """Return an SQLite connection for the index cache."""
    conn = sqlite3.connect(str(SQLITE_CACHE))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indexed_files (
            path TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            indexed_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def is_file_indexed(filepath: str | Path) -> bool:
    """Check if a file is already indexed with its current mtime."""
    fp = Path(filepath).resolve()
    if not fp.exists():
        return False
    conn = _get_cache_conn()
    try:
        row = conn.execute(
            "SELECT mtime FROM indexed_files WHERE path = ?", (str(fp),)
        ).fetchone()
        if row is None:
            return False
        return row[0] == fp.stat().st_mtime
    finally:
        conn.close()


def _mark_indexed(filepath: str | Path) -> None:
    """Record that a file has been successfully indexed."""
    fp = Path(filepath).resolve()
    conn = _get_cache_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO indexed_files (path, mtime, indexed_at) VALUES (?, ?, ?)",
            (str(fp), fp.stat().st_mtime, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _remove_from_cache(filepath: str | Path) -> None:
    """Remove a file from the index cache."""
    fp = str(Path(filepath).resolve())
    conn = _get_cache_conn()
    try:
        conn.execute("DELETE FROM indexed_files WHERE path = ?", (fp,))
        conn.commit()
    finally:
        conn.close()


# ─── File ID helper ─────────────────────────────────────────────────────────

def _file_id(filepath: str | Path) -> str:
    """Generate a stable ChromaDB document ID from a file path."""
    fp = str(Path(filepath).resolve())
    return hashlib.sha256(fp.encode("utf-8")).hexdigest()


# ─── Rate Limit Helpers ─────────────────────────────────────────────────────

class DailyQuotaExceededError(Exception):
    """Raised when the Gemini API daily quota is exhausted. Must wait for reset."""
    pass


def _is_daily_quota_error(err_str: str) -> bool:
    """Return True if the error indicates a daily (not per-minute) quota exhaustion."""
    return (
        "PerDay" in err_str
        or "limit: 0" in err_str
        or "GenerateRequestsPerDayPerProjectPerModel" in err_str
    )


def with_retry(max_attempts: int = 3, base_delay: int = 65):
    """
    Retry decorator:
    - On per-minute rate limit (429): wait base_delay seconds and retry.
    - On daily quota exhaustion: raise DailyQuotaExceededError immediately.
    - On any other error: raise immediately.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except DailyQuotaExceededError:
                    raise  # Propagate immediately — no point retrying
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "quota" in err_str.lower():
                        if _is_daily_quota_error(err_str):
                            raise DailyQuotaExceededError(
                                "Daily Gemini API quota exhausted. "
                                "Quota resets at midnight Pacific Time (~1:30 PM IST). "
                                "Please wait and try again tomorrow."
                            ) from e
                        # Per-minute rate limit — wait and retry
                        if attempt < max_attempts - 1:
                            delay = base_delay * (2 ** attempt)
                            print(f"  [RATE LIMIT] Waiting {delay}s before retry {attempt + 2}/{max_attempts}...")
                            time.sleep(delay)
                            continue
                    raise e
            return None
        return wrapper
    return decorator


def _get_text_content(filepath: Path) -> str | None:
    """Read text content from a text file."""
    try:
        return filepath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            return filepath.read_text(encoding="latin-1", errors="replace")
        except Exception:
            return None


def _extract_pdf_text(filepath: Path) -> str | None:
    """Extract text from a PDF using PyMuPDF."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(filepath))
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        text = "\n".join(text_parts).strip()
        return text if text else None
    except Exception:
        return None


@with_retry()
def _describe_image_for_embedding(filepath: Path) -> str | None:
    """Use Gemini to generate a textual description of an image for embedding."""
    client = _get_client()
    with open(filepath, "rb") as f:
        image_data = f.read()

    suffix = filepath.suffix.lower()
    mime = MIME_MAP.get(suffix, "image/jpeg")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=image_data, mime_type=mime),
            "Describe this image in detail for semantic search indexing. "
            "Include objects, people, text, colors, setting, mood, and any notable details. "
            "Be comprehensive but concise.",
        ],
    )
    return response.text if response.text else None


@with_retry()
def _describe_media_for_embedding(filepath: Path) -> str | None:
    """Use Gemini to describe audio/video content for embedding."""
    client = _get_client()
    with open(filepath, "rb") as f:
        media_data = f.read()

    suffix = filepath.suffix.lower()
    mime = MIME_MAP.get(suffix, "video/mp4")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=media_data, mime_type=mime),
            "Describe this media content in detail for semantic search indexing. "
            "Include what is happening, any speech or text, sounds, visual details, "
            "and any notable information. Be comprehensive but concise.",
        ],
    )
    return response.text if response.text else None


@with_retry()
def _get_embedding(text: str) -> list[float] | None:
    """Get text embedding using Gemini embedding model."""
    client = _get_client()
    # Truncate very long text to avoid API limits
    if len(text) > 30000:
        text = text[:30000]
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
    )
    # The response contains an embeddings attribute
    if response.embeddings and len(response.embeddings) > 0:
        return list(response.embeddings[0].values)
    return None


def _prepare_text_for_embedding(filepath: Path) -> str | None:
    """
    Prepare text content for embedding based on file type.
    For text files: read directly.
    For PDFs: extract text.
    For images: generate description via Gemini.
    For audio/video: generate description via Gemini.
    """
    suffix = filepath.suffix.lower()

    if suffix in TEXT_EXTENSIONS:
        return _get_text_content(filepath)
    elif suffix == ".pdf":
        return _extract_pdf_text(filepath)
    elif suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return _describe_image_for_embedding(filepath)
    elif suffix in {".mp4", ".m4a", ".mp3"}:
        return _describe_media_for_embedding(filepath)
    return None


# ─── Public API ──────────────────────────────────────────────────────────────

def embed_file(filepath: str) -> bool:
    """
    Embed a file and store it in ChromaDB.
    Returns True on success, False on failure/skip.
    """
    fp = Path(filepath).resolve()

    # Validation
    if not fp.exists():
        logging.error(f"File not found: {fp}")
        return False

    if fp.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False

    if fp.stat().st_size > MAX_FILE_BYTES:
        logging.error(f"File too large (>{MAX_FILE_BYTES // (1024*1024)}MB): {fp}")
        return False

    try:
        # Get text representation
        text = _prepare_text_for_embedding(fp)
        if not text or not text.strip():
            logging.error(f"No content extracted from: {fp}")
            return False

        # Get embedding vector
        embedding = _get_embedding(text)
        if embedding is None:
            logging.error(f"Failed to get embedding for: {fp}")
            return False

        # Store in ChromaDB
        collection = _get_collection()
        doc_id = _file_id(fp)

        collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            metadatas=[{
                "path": str(fp),
                "name": fp.name,
                "extension": fp.suffix.lower(),
                "size": fp.stat().st_size,
                "mtime": fp.stat().st_mtime,
            }],
            documents=[text[:5000]],  # Store truncated text as document
        )

        # Mark in SQLite cache
        _mark_indexed(fp)
        return True

    except DailyQuotaExceededError:
        raise
    except Exception as e:
        logging.error(f"Failed to embed {fp}: {e}")
        return False


def delete_file(filepath: str) -> bool:
    """
    Remove a file's embedding from ChromaDB.
    Returns True on success.
    """
    fp = Path(filepath).resolve()
    doc_id = _file_id(fp)
    try:
        collection = _get_collection()
        collection.delete(ids=[doc_id])
        _remove_from_cache(fp)
        return True
    except Exception as e:
        logging.error(f"Failed to delete {fp} from index: {e}")
        return False


# ─── Score Calibration ──────────────────────────────────────────────────────
# ChromaDB returns cosine distance in [0, 2]: 0 = identical, 1 = orthogonal.
# For gemini-embedding-001, genuine matches cluster in [0.20, 0.55] distance,
# meaning raw similarity (1 - dist) always hovers near 50% — no differentiation.
# We calibrate by defining what "unrelated" and "strong match" actually look like
# for this model, then apply a square-root curve to spread the scores further.
_SIM_FLOOR = 0.45    # similarity at or below this = effectively unrelated
_SIM_CEILING = 0.80  # similarity at or above this = strong match → 100%


def _calibrate_score(dist: float) -> float:
    """Convert raw ChromaDB cosine distance to a calibrated score (0–100)."""
    raw_sim = 1.0 - dist
    normalized = (raw_sim - _SIM_FLOOR) / (_SIM_CEILING - _SIM_FLOOR)
    normalized = max(0.0, min(1.0, normalized))
    # Square-root curve: amplifies differences near the top of the range
    return round(normalized ** 0.5 * 100, 1)


def search(query: str, n: int = 12) -> list[dict]:
    """
    Search indexed files by semantic similarity.
    Returns top-n results as: [{'path': str, 'name': str, 'score': float}]
    Score is a calibrated percentage 0–100 (higher = more similar).
    """
    if not query or not query.strip():
        return []

    try:
        # Get query embedding
        embedding = _get_embedding(query)
        if embedding is None:
            return []

        collection = _get_collection()
        if collection.count() == 0:
            return []

        # Query ChromaDB
        actual_n = min(n, collection.count())
        results = collection.query(
            query_embeddings=[embedding],
            n_results=actual_n,
            include=["metadatas", "distances"],
        )

        # Format results
        output = []
        if results and results["metadatas"] and results["distances"]:
            for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
                score = _calibrate_score(dist)
                output.append({
                    "path": meta.get("path", ""),
                    "name": meta.get("name", ""),
                    "score": score,
                })

        return output

    except Exception as e:
        logging.error(f"Search failed for query '{query}': {e}")
        return []


def get_indexed_count() -> int:
    """Return the number of indexed documents."""
    try:
        return _get_collection().count()
    except Exception:
        return 0
