"""
Imprint — Unified Launcher
Starts both the search API server and file watcher in a single process.
"""

import sys
import threading
import time
import logging
from pathlib import Path

from config import ERROR_LOG, ensure_api_key, get_watch_dirs

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=str(ERROR_LOG),
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def run_api_server():
    """Run the FastAPI search server."""
    import uvicorn
    from search_api import app

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


def run_watcher():
    """Run the file watcher."""
    from watchdog.observers.polling import PollingObserver
    from watcher import ImprintHandler

    watch_dirs = get_watch_dirs()
    if not watch_dirs:
        print("  [WARN] No watch directories configured. Watcher idle.")
        return

    observer = PollingObserver(timeout=5)
    handler = ImprintHandler()

    for d in watch_dirs:
        observer.schedule(handler, str(d), recursive=True)
        print(f"  👁  Watching: {d}")

    observer.start()
    try:
        while True:
            time.sleep(1)
    except Exception:
        observer.stop()
    observer.join()


def main():
    """Launch Imprint services."""
    # Ensure API key on startup
    ensure_api_key()

    print()
    print("  ╔══════════════════════════════════════════════════════════╗")
    print("  ║   ██╗███╗   ███╗██████╗ ██████╗ ██╗███╗   ██╗████████╗   ║")
    print("  ║   ██║████╗ ████║██╔══██╗██╔══██╗██║████╗  ██║╚══██╔══╝   ║")
    print("  ║   ██║██╔████╔██║██████╔╝██████╔╝██║██╔██╗ ██║   ██║      ║")
    print("  ║   ██║██║╚██╔╝██║██╔═══╝ ██╔══██╗██║██║╚██╗██║   ██║      ║")
    print("  ║   ██║██║ ╚═╝ ██║██║     ██║  ██║██║██║ ╚████║   ██║      ║")
    print("  ║   ╚═╝╚═╝     ╚═╝╚═╝     ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝   ╚═╝      ║")
    print("  ║                                                  -by sid ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print()

    from embedder import get_indexed_count
    print(f"  📊 Indexed files: {get_indexed_count()}")
    print(f"  🌐 API Server:   http://localhost:8000")
    print(f"  📖 API Docs:     http://localhost:8000/docs")
    print()

    # Start watcher in background thread
    watcher_thread = threading.Thread(target=run_watcher, daemon=True)
    watcher_thread.start()

    print("  Press Ctrl+C to stop all services.")
    print()

    # Run API server (blocking, in main thread)
    try:
        run_api_server()
    except KeyboardInterrupt:
        print("\n  Shutting down Imprint...")
        sys.exit(0)


if __name__ == "__main__":
    main()
