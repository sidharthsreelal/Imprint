"""
Imprint — Real-Time File Watcher
Watches user-configured directories for changes and indexes new/modified files.
Uses PollingObserver for Windows reliability.
"""

import sys
import time
import logging
from pathlib import Path

from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from config import (
    ERROR_LOG,
    SUPPORTED_EXTENSIONS,
    MAX_FILE_BYTES,
    ensure_api_key,
    get_watch_dirs,
)
from embedder import embed_file, delete_file

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=str(ERROR_LOG),
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def _is_supported(filepath: str) -> bool:
    """Check if a file path has a supported extension and isn't too large."""
    fp = Path(filepath)
    if fp.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False
    try:
        if fp.exists() and fp.stat().st_size > MAX_FILE_BYTES:
            return False
    except OSError:
        return False
    return True


class ImprintHandler(FileSystemEventHandler):
    """Handles file system events: create, modify, delete."""

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if not _is_supported(event.src_path):
            return

        # Small delay to ensure file write is complete
        time.sleep(1)

        try:
            success = embed_file(event.src_path)
            if success:
                print(f"  [NEW] ✓ {Path(event.src_path).name}")
            else:
                print(f"  [NEW] ✗ {Path(event.src_path).name}")
        except Exception as e:
            logging.error(f"Watcher on_created failed for {event.src_path}: {e}")
            print(f"  [NEW] ✗ {Path(event.src_path).name} — {e}")

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if not _is_supported(event.src_path):
            return

        # Small delay to ensure file write is complete
        time.sleep(1)

        try:
            success = embed_file(event.src_path)
            if success:
                print(f"  [UPD] ✓ {Path(event.src_path).name}")
            else:
                print(f"  [UPD] ✗ {Path(event.src_path).name}")
        except Exception as e:
            logging.error(f"Watcher on_modified failed for {event.src_path}: {e}")
            print(f"  [UPD] ✗ {Path(event.src_path).name} — {e}")

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # Check extension from path (file no longer exists)
        if Path(event.src_path).suffix.lower() not in SUPPORTED_EXTENSIONS:
            return

        try:
            success = delete_file(event.src_path)
            if success:
                print(f"  [DEL] ✓ {Path(event.src_path).name}")
        except Exception as e:
            logging.error(f"Watcher on_deleted failed for {event.src_path}: {e}")


def start_watcher():
    """Start the file watcher on all configured directories."""
    # Ensure API key is set
    ensure_api_key()

    watch_dirs = get_watch_dirs()
    if not watch_dirs:
        print()
        print("  ╔══════════════════════════════════════════════════════╗")
        print("  ║  No watch directories configured!                    ║")
        print("  ║                                                      ║")
        print("  ║  Add directories first:                              ║")
        print("  ║    python config.py add \"C:\\Users\\You\\Pictures\" ║")
        print("  ╚══════════════════════════════════════════════════════╝")
        print()
        sys.exit(1)

    observer = PollingObserver(timeout=5)
    handler = ImprintHandler()

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║         IMPRINT — File Watcher           ║")
    print("  ╚══════════════════════════════════════════╝")
    print()

    for d in watch_dirs:
        observer.schedule(handler, str(d), recursive=True)
        print(f"  👁  Watching: {d}")

    print()
    print("  Watcher is running. Press Ctrl+C to stop.")
    print()

    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  Stopping watcher...")
        observer.stop()
    observer.join()
    print("  ✓ Watcher stopped.")


if __name__ == "__main__":
    start_watcher()
