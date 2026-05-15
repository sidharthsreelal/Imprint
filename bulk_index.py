"""
Imprint — Bulk Indexer
One-time full indexer that walks configured watch directories,
embeds all supported files, and tracks progress via SQLite cache.
"""

import sys
import time
import logging
from pathlib import Path

from config import (
    ERROR_LOG,
    SUPPORTED_EXTENSIONS,
    MAX_FILE_BYTES,
    ensure_api_key,
    get_watch_dirs,
    load_config,
)
from embedder import embed_file, is_file_indexed, DailyQuotaExceededError

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=str(ERROR_LOG),
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def collect_files(watch_dirs: list[Path]) -> list[Path]:
    """Recursively collect all supported files from watch directories."""
    files = []
    for d in watch_dirs:
        if not d.is_dir():
            print(f"  [SKIP] Directory not found: {d}")
            continue
        for fp in d.rglob("*"):
            if not fp.is_file():
                continue
            if fp.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if fp.stat().st_size > MAX_FILE_BYTES:
                continue
            files.append(fp)
    return files


def bulk_index():
    """Main bulk indexing routine."""
    # Ensure API key
    ensure_api_key()

    # Load config
    cfg = load_config()
    watch_dirs = get_watch_dirs()
    batch_size = cfg.get("batch_size", 50)
    batch_pause = cfg.get("batch_pause_seconds", 2)

    if not watch_dirs:
        print()
        print("  +------------------------------------------------------+ ")
        print("  |  No watch directories configured!                    | ")
        print("  |                                                      | ")
        print("  |  Add directories first:                              | ")
        print("  |    python config.py add \"C:\\Users\\You\\Pictures\" | ")
        print("  |    python config.py add \"D:\\Photos\"               | ")
        print("  +------------------------------------------------------+ ")
        print()
        sys.exit(1)

    print()
    print("  +------------------------------------------+")
    print("  |         IMPRINT - Bulk Indexer           |")
    print("  +------------------------------------------+")
    print()
    print("  Scanning directories...")
    for d in watch_dirs:
        print(f"    * {d}")
    print()

    # Collect files
    all_files = collect_files(watch_dirs)
    total = len(all_files)
    print(f"  Found {total} supported files.")

    # Filter out already-indexed
    to_index = [f for f in all_files if not is_file_indexed(f)]
    skipped = total - len(to_index)
    print(f"  Skipping {skipped} already-indexed files.")
    print(f"  Indexing {len(to_index)} new/modified files.")
    print()

    if not to_index:
        print("  Done: Everything is up to date!")
        return

    # Process in batches
    success = 0
    failed = 0
    start_time = time.time()

    for i, fp in enumerate(to_index, 1):
        print(f"  [{i}/{len(to_index)}] Processing: {fp.name}...", end="\r", flush=True)
        try:
            result = embed_file(str(fp))
            if result:
                success += 1
                print(f"  [{i}/{len(to_index)}] [+] {fp.name}              ")
            else:
                failed += 1
                print(f"  [{i}/{len(to_index)}] [-] {fp.name}              ")
        except DailyQuotaExceededError as e:
            print()
            print("  +----------------------------------------------------------+")
            print("  |  !  DAILY QUOTA EXHAUSTED - Stopping indexer            |")
            print("  |                                                          |")
            print("  |  Your API quota has been used up.                        |")
            print("  |  Quota resets at midnight Pacific Time.                  |")
            print("  |  Run 'python bulk_index.py' again after the reset.       |")
            print("  +----------------------------------------------------------+")
            print()
            print(f"  Progress saved: {success} indexed, {failed} failed, {len(to_index)-i} remaining.")
            logging.error(f"Bulk index aborted: {e}")
            break
        except Exception as e:
            failed += 1
            logging.error(f"Failed to embed {fp}: {e}")
            print(f"  [{i}/{len(to_index)}] ✗ {fp.name} — {e}")

        # Rate limit: pause between batches
        if i % batch_size == 0 and i < len(to_index):
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (len(to_index) - i) / rate if rate > 0 else 0
            print(f"\n  --- Batch pause ({batch_pause}s) | "
                  f"{i}/{len(to_index)} done | "
                  f"~{remaining:.0f}s remaining ---\n")
            time.sleep(batch_pause)

    elapsed = time.time() - start_time
    print()
    print(f"  ========================================")
    print(f"  Done in {elapsed:.1f}s")
    print(f"  Success: {success}")
    print(f"  Failed:  {failed}")
    print(f"  ========================================")


if __name__ == "__main__":
    bulk_index()
