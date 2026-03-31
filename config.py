"""
Imprint — Configuration Manager
Handles user configuration (watch directories, settings) stored in a JSON file.
API key is stored securely via Windows Credential Manager (keyring).
"""

import json
import sys
import keyring
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "config.json"
CHROMA_DIR = APP_DIR / "chroma_db"
SQLITE_CACHE = APP_DIR / "index_cache.db"
ERROR_LOG = APP_DIR / "errors.log"

# ─── Keyring constants ──────────────────────────────────────────────────────
KEYRING_SERVICE = "Imprint-MemorySearch"
KEYRING_USERNAME = "gemini_api_key"

# ─── Supported extensions ───────────────────────────────────────────────────
SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp",
    ".pdf",
    ".mp4", ".m4a", ".mp3",
    ".txt", ".md",
}

MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB


# ─── API Key Management (Windows Credential Manager) ────────────────────────

def get_api_key() -> str | None:
    """Retrieve the Gemini API key from Windows Credential Manager."""
    return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)


def set_api_key(api_key: str) -> None:
    """Store the Gemini API key in Windows Credential Manager."""
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, api_key)


def delete_api_key() -> None:
    """Remove the stored API key."""
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass


def ensure_api_key() -> str:
    """
    Ensure the API key is available.
    If not stored, prompt the user interactively.
    Returns the API key string.
    """
    key = get_api_key()
    if key:
        return key

    print("=" * 60)
    print("  IMPRINT — First-Time Setup")
    print("=" * 60)
    print()
    print("  A Gemini API key is required for semantic embeddings.")
    print("  Get one free at: https://aistudio.google.com/apikey")
    print()
    key = input("  Enter your Gemini API key: ").strip()
    if not key:
        print("  [ERROR] No API key provided. Exiting.")
        sys.exit(1)

    set_api_key(key)
    print("  ✓ API key stored securely in Windows Credential Manager.")
    print()
    return key


# ─── Watch Directories Config ───────────────────────────────────────────────

def _default_config() -> dict:
    return {
        "watch_dirs": [],
        "batch_size": 14,
        "batch_pause_seconds": 65,
        "search_results_default": 12,
    }


def load_config() -> dict:
    """Load configuration from config.json. Creates defaults if missing."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults for any missing keys
        defaults = _default_config()
        for k, v in defaults.items():
            data.setdefault(k, v)
        return data
    else:
        cfg = _default_config()
        save_config(cfg)
        return cfg


def save_config(cfg: dict) -> None:
    """Persist configuration to config.json."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def get_watch_dirs() -> list[Path]:
    """Return the list of directories the user wants to index/watch."""
    cfg = load_config()
    return [Path(d) for d in cfg.get("watch_dirs", []) if Path(d).is_dir()]


def add_watch_dir(directory: str | Path) -> bool:
    """Add a directory to the watch list. Returns True if added."""
    d = Path(directory).resolve()
    if not d.is_dir():
        print(f"  [ERROR] Not a valid directory: {d}")
        return False
    cfg = load_config()
    dir_str = str(d)
    if dir_str not in cfg["watch_dirs"]:
        cfg["watch_dirs"].append(dir_str)
        save_config(cfg)
        print(f"  ✓ Added: {d}")
        return True
    else:
        print(f"  [INFO] Already in watch list: {d}")
        return False


def remove_watch_dir(directory: str | Path) -> bool:
    """Remove a directory from the watch list."""
    d = str(Path(directory).resolve())
    cfg = load_config()
    if d in cfg["watch_dirs"]:
        cfg["watch_dirs"].remove(d)
        save_config(cfg)
        print(f"  ✓ Removed: {d}")
        return True
    else:
        print(f"  [INFO] Not in watch list: {d}")
        return False


def list_watch_dirs() -> None:
    """Print current watch directories."""
    cfg = load_config()
    dirs = cfg.get("watch_dirs", [])
    if not dirs:
        print("  No watch directories configured.")
        print("  Use: python config.py add <path>")
    else:
        print("  Watch directories:")
        for i, d in enumerate(dirs, 1):
            exists = "✓" if Path(d).is_dir() else "✗ (missing)"
            print(f"    {i}. {d}  {exists}")


# ─── CLI for managing config ────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Imprint Configuration Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python config.py list                   Show watch directories
  python config.py add "D:\\Photos"       Add a directory to index
  python config.py add "%USERPROFILE%\\Documents"
  python config.py remove "D:\\Photos"    Remove a directory
  python config.py set-key                Set/update your Gemini API key
  python config.py delete-key             Remove your stored API key
        """,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List watch directories")

    p_add = sub.add_parser("add", help="Add a watch directory")
    p_add.add_argument("path", help="Directory path to add")

    p_rm = sub.add_parser("remove", help="Remove a watch directory")
    p_rm.add_argument("path", help="Directory path to remove")

    sub.add_parser("set-key", help="Set/update Gemini API key")
    sub.add_parser("delete-key", help="Delete stored Gemini API key")

    args = parser.parse_args()

    if args.command == "list":
        list_watch_dirs()
    elif args.command == "add":
        add_watch_dir(args.path)
    elif args.command == "remove":
        remove_watch_dir(args.path)
    elif args.command == "set-key":
        key = input("  Enter your Gemini API key: ").strip()
        if key:
            set_api_key(key)
            print("  ✓ API key updated.")
        else:
            print("  [ERROR] No key entered.")
    elif args.command == "delete-key":
        delete_api_key()
        print("  ✓ API key removed from Credential Manager.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
