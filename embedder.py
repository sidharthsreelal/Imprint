"""
Imprint — Core Embedding & Search Engine
Handles file embedding via OpenRouter API and semantic search via ChromaDB.
"""

import base64
import hashlib
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
import json
import requests

import chromadb

from config import (
    CHROMA_DIR,
    ERROR_LOG,
    MAX_FILE_BYTES,
    SQLITE_CACHE,
    SUPPORTED_EXTENSIONS,
    ensure_api_key,
    get_api_key,
    get_embedding_provider,
    load_config,
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

# ─── ChromaDB (lazy-initialized) ────────────────────────────────────────────
_chroma_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None


def _get_collection() -> chromadb.Collection:
    """Get or initialize the ChromaDB collection."""
    global _chroma_client, _collection

    cfg = load_config()
    model_name = cfg.get("embedding_model", "nemotron")
    safe_name = "".join([c if c.isalnum() else "_" for c in model_name]).strip("_")
    collection_name = f"imprint_{safe_name}"

    if _collection is not None:
        if _collection.name == collection_name:
            return _collection

    if _chroma_client is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    _collection = _chroma_client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


# ─── SQLite Index Cache ─────────────────────────────────────────────────────

def _get_cache_conn_and_table() -> tuple[sqlite3.Connection, str]:
    """Return an SQLite connection and table name for the index cache."""
    conn = sqlite3.connect(str(SQLITE_CACHE))
    cfg = load_config()
    model_name = cfg.get("embedding_model", "nemotron")
    safe_name = "".join([c if c.isalnum() else "_" for c in model_name]).strip("_")
    table = f"cache_{safe_name}"

    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            path TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            indexed_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn, table


def is_file_indexed(filepath: str | Path) -> bool:
    """Check if a file is already indexed with its current mtime."""
    fp = Path(filepath).resolve()
    if not fp.exists():
        return False
    conn, table = _get_cache_conn_and_table()
    try:
        row = conn.execute(
            f"SELECT mtime FROM {table} WHERE path = ?", (str(fp),)
        ).fetchone()
        if row is None:
            return False
        return row[0] == fp.stat().st_mtime
    finally:
        conn.close()


def _mark_indexed(filepath: str | Path) -> None:
    """Record that a file has been successfully indexed."""
    fp = Path(filepath).resolve()
    conn, table = _get_cache_conn_and_table()
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO {table} (path, mtime, indexed_at) VALUES (?, ?, ?)",
            (str(fp), fp.stat().st_mtime, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _remove_from_cache(filepath: str | Path) -> None:
    """Remove a file from the index cache."""
    fp = str(Path(filepath).resolve())
    conn, table = _get_cache_conn_and_table()
    try:
        conn.execute(f"DELETE FROM {table} WHERE path = ?", (fp,))
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
    """Raised when the API daily quota is exhausted. Must wait for reset."""
    pass


def _is_daily_quota_error(err_str: str) -> bool:
    """Return True if the error indicates a daily quota exhaustion."""
    err_lower = err_str.lower()
    return (
        "perday" in err_lower
        or "per-day" in err_lower
        or "per day" in err_lower
        or "limit: 0" in err_lower
        or "insufficient_quota" in err_lower
        or "daily" in err_lower
        or "free tier limit" in err_lower
        or "credits" in err_lower
        or "balance" in err_lower
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
                                "Daily API quota exhausted. "
                                "Quota resets at midnight. "
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
    """Use AI to generate a textual description of an image for embedding."""
    provider = get_embedding_provider()
    cfg = load_config()
    vision_model = cfg.get("vision_model", "")
    api_key = ensure_api_key()

    with open(filepath, "rb") as f:
        image_data = f.read()

    suffix = filepath.suffix.lower()
    mime = MIME_MAP.get(suffix, "image/jpeg")
    base64_image = base64.b64encode(image_data).decode('utf-8')

    prompt = 'Describe this image in detail for semantic search indexing. Include objects, people, text, colors, setting, mood, and any notable details. Be comprehensive but concise.'

    if provider == "openrouter":
        image_url = f"data:{mime};base64,{base64_image}"
        url = 'https://openrouter.ai/api/v1/chat/completions'
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        data = {
            'model': vision_model,
            'messages': [{
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url', 'image_url': {'url': image_url}}
                ]
            }]
        }
        response = requests.post(url, headers=headers, json=data, timeout=120)
        if response.status_code == 429: raise Exception(f"429 Rate Limit: {response.text}")
        if response.status_code != 200:
            logging.error(f"Image description failed: {response.text}")
            return None
        return response.json()['choices'][0]['message']['content']

    elif provider == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{vision_model}:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        data = {
            'contents': [{
                'parts': [
                    {'text': prompt},
                    {'inlineData': {'mimeType': mime, 'data': base64_image}}
                ]
            }]
        }
        response = requests.post(url, headers=headers, json=data, timeout=120)
        if response.status_code == 429: raise Exception(f"429 Rate Limit: {response.text}")
        if response.status_code != 200:
            logging.error(f"Image description failed: {response.text}")
            return None
        return response.json()['candidates'][0]['content']['parts'][0]['text']

    elif provider == "ollama":
        ollama_url = cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")
        url = f"{ollama_url}/api/generate"
        data = {
            'model': vision_model,
            'prompt': prompt,
            'images': [base64_image],
            'stream': False
        }
        print(f"    (Ollama: Describing {filepath.name} with {vision_model}...)")
        response = requests.post(url, json=data, timeout=300) # 5 min timeout for slow CPUs
        if response.status_code != 200:
            logging.error(f"Image description failed: {response.text}")
            return None
        return response.json().get('response')

    return None


@with_retry()
def _describe_media_for_embedding(filepath: Path) -> str | None:
    """Return none for media since OpenRouter vision models don't support audio/video natively securely."""
    logging.warning(f"Media extraction (audio/video) is currently unsupported via OpenRouter: {filepath}")
    return None


@with_retry()
def _get_embedding(text: str) -> list[float] | None:
    """Get text embedding using the configured provider."""
    if len(text) > 30000:
        text = text[:30000]

    provider = get_embedding_provider()
    cfg = load_config()
    embed_model = cfg.get("embedding_model", "")
    api_key = ensure_api_key()

    if provider == "openrouter":
        url = 'https://openrouter.ai/api/v1/embeddings'
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        data = {'model': embed_model, 'input': text}
        response = requests.post(url, headers=headers, json=data, timeout=60)
        if response.status_code == 429: raise Exception(f"429 Rate Limit: {response.text}")
        if response.status_code != 200:
            logging.error(f"Embedding failed: {response.text}")
            return None
        result = response.json()
        if 'data' in result and len(result['data']) > 0:
            return result['data'][0]['embedding']

    elif provider == "gemini":
        model_name = embed_model if embed_model.startswith("models/") else f"models/{embed_model}"
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:embedContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        data = {
            'model': model_name,
            'content': {'parts': [{'text': text}]}
        }
        response = requests.post(url, headers=headers, json=data, timeout=60)
        if response.status_code == 429: raise Exception(f"429 Rate Limit: {response.text}")
        if response.status_code != 200:
            logging.error(f"Embedding failed: {response.text}")
            return None
        result = response.json()
        if 'embedding' in result and 'values' in result['embedding']:
            return result['embedding']['values']

    elif provider == "ollama":
        ollama_url = cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")
        url = f"{ollama_url}/api/embeddings"
        data = {'model': embed_model, 'prompt': text}
        response = requests.post(url, json=data, timeout=60)
        if response.status_code != 200:
            logging.error(f"Embedding failed: {response.text}")
            return None
        result = response.json()
        if 'embedding' in result:
            return result['embedding']

    return None


def _prepare_text_for_embedding(filepath: Path) -> str | None:
    """
    Prepare text content for embedding based on file type.
    For text files: read directly.
    For PDFs: extract text.
    For images: generate description via OpenRouter.
    For audio/video: skip for now as not supported.
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
# For openrouter embeddings, genuine matches cluster in [0.20, 0.55] distance,
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
