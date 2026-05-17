"""
Imprint — Configuration Manager
Handles user configuration (watch directories, settings) stored in a JSON file.
API keys are stored via:
  - Windows Credential Manager (keyring) for Gemini / OpenRouter
  - .env.local file in the project root for Mistral
"""

import json
import sys
import keyring
import shutil
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "config.json"
CHROMA_DIR = APP_DIR / "chroma_db"
SQLITE_CACHE = APP_DIR / "index_cache.db"
ERROR_LOG = APP_DIR / "errors.log"

# ─── Keyring constants ──────────────────────────────────────────────────────
KEYRING_SERVICE = "Imprint-MemorySearch"

# ─── Providers that store keys via .env.local (not keyring) ─────────────────
ENV_LOCAL_PROVIDERS = {"mistral"}
ENV_LOCAL_FILE = APP_DIR / ".env.local"


def _load_env_local() -> dict[str, str]:
    """Parse .env.local and return a dict of key→value pairs."""
    env: dict[str, str] = {}
    if not ENV_LOCAL_FILE.exists():
        return env
    with open(ENV_LOCAL_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env

# ─── Supported extensions ───────────────────────────────────────────────────
SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp",
    ".pdf",
    ".mp4", ".m4a", ".mp3",
    ".txt", ".md",
}

MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB


# ─── API Key Management (Windows Credential Manager) ────────────────────────

def get_api_key(provider: str | None = None) -> str | None:
    """Retrieve the API key for the given provider.

    Mistral keys are read from .env.local (MISTRAL_API_KEY).
    All other provider keys come from Windows Credential Manager.
    """
    provider = provider or get_embedding_provider()
    if provider == "ollama":
        return None
    if provider in ENV_LOCAL_PROVIDERS:
        return _load_env_local().get("MISTRAL_API_KEY")
    return keyring.get_password(KEYRING_SERVICE, f"{provider}_api_key")


def set_api_key(api_key: str, provider: str | None = None) -> None:
    """Store the API key for the given provider.

    Mistral keys are written to .env.local; all others go to Credential Manager.
    """
    provider = provider or get_embedding_provider()
    if provider == "ollama":
        return
    if provider in ENV_LOCAL_PROVIDERS:
        # Write / update MISTRAL_API_KEY in .env.local
        env = _load_env_local()
        env["MISTRAL_API_KEY"] = api_key
        lines = [f"{k}={v}\n" for k, v in env.items()]
        with open(ENV_LOCAL_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return
    keyring.set_password(KEYRING_SERVICE, f"{provider}_api_key", api_key)


def delete_api_key(provider: str | None = None) -> None:
    """Remove the stored API key."""
    provider = provider or get_embedding_provider()
    if provider in ENV_LOCAL_PROVIDERS:
        env = _load_env_local()
        env.pop("MISTRAL_API_KEY", None)
        lines = [f"{k}={v}\n" for k, v in env.items()]
        with open(ENV_LOCAL_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, f"{provider}_api_key")
    except keyring.errors.PasswordDeleteError:
        pass


def ensure_api_key() -> str | None:
    """
    Ensure the API key is available for the active provider.
    - Mistral: reads from .env.local (MISTRAL_API_KEY). Prompts and writes file if missing.
    - Ollama: no key needed, returns None.
    - Others: reads from / writes to Windows Credential Manager.
    """
    provider = get_embedding_provider()
    if provider == "ollama":
        return None

    key = get_api_key(provider)
    if key:
        return key

    print("=" * 60)
    print(f"  IMPRINT — First-Time Setup ({provider})")
    print("=" * 60)
    print()
    print(f"  An API key is required for {provider}.")
    if provider == "openrouter":
        print("  Get one at: https://openrouter.ai/")
    elif provider == "gemini":
        print("  Get one at: https://aistudio.google.com/app/apikey")
    elif provider == "mistral":
        print("  Get one at: https://console.mistral.ai/")
        print(f"  The key will be saved to {ENV_LOCAL_FILE.name} in the project root.")
    print()

    key = input(f"  Enter your {provider.capitalize()} API key: ").strip()
    if not key:
        print("  [ERROR] No API key provided. Exiting.")
        sys.exit(1)

    set_api_key(key, provider)
    if provider in ENV_LOCAL_PROVIDERS:
        print(f"  [+] API key saved to {ENV_LOCAL_FILE.name}.")
    else:
        print("  [+] API key stored securely in Windows Credential Manager.")
    print()
    return key


# ─── Watch Directories Config ───────────────────────────────────────────────

def _default_config() -> dict:
    return {
        "watch_dirs": [],
        "batch_size": 14,
        "batch_pause_seconds": 65,
        "search_results_default": 12,
        "embedding_provider": "openrouter",
        "embedding_model": "nvidia/llama-nemotron-embed-vl-1b-v2:free",
        "vision_model": "nvidia/nemotron-nano-12b-v2-vl:free",
        "ollama_url": "http://127.0.0.1:11434",
        "mistral_embed_model": "codestral-embed-2505",
        "mistral_vision_model": "mistral-medium-latest",
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


def get_embedding_provider() -> str:
    """Return the currently configured embedding provider."""
    cfg = load_config()
    return cfg.get("embedding_provider", "openrouter")


def set_embedding_provider(provider: str) -> None:
    """Update the provider and set up smart standard defaults for its models."""
    if provider not in {"openrouter", "gemini", "ollama", "mistral"}:
        print(f"  [ERROR] Unsupported provider: {provider}")
        return
    cfg = load_config()
    cfg["embedding_provider"] = provider

    if provider == "gemini":
        cfg["embedding_model"] = "models/text-embedding-004"
        cfg["vision_model"] = "gemini-1.5-flash"
        cfg["batch_size"] = 14
        cfg["batch_pause_seconds"] = 65
    elif provider == "openrouter":
        cfg["embedding_model"] = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
        cfg["vision_model"] = "nvidia/nemotron-nano-12b-v2-vl:free"
        cfg["batch_size"] = 14
        cfg["batch_pause_seconds"] = 65
    elif provider == "ollama":
        cfg["embedding_model"] = "nomic-embed-text"
        cfg["vision_model"] = "llava"
        cfg["batch_size"] = 50
        cfg["batch_pause_seconds"] = 1
    elif provider == "mistral":
        cfg["embedding_model"] = "codestral-embed-2505"
        cfg["vision_model"] = "mistral-medium-latest"
        cfg["batch_size"] = 20
        cfg["batch_pause_seconds"] = 5

    save_config(cfg)
    print(f"  [+] Provider set to {provider}")
    print(f"    Embedding model: {cfg['embedding_model']}")
    print(f"    Vision model:    {cfg['vision_model']}")
    print(f"    Batch Size:      {cfg['batch_size']}")
    print(f"    Batch Pause:     {cfg['batch_pause_seconds']}s")
    if provider == "mistral":
        print(f"    API key source:  {ENV_LOCAL_FILE.name} (MISTRAL_API_KEY)")


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
        print(f"  [+] Added: {d}")
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
        print(f"  [-] Removed: {d}")
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
            exists = "[+]" if Path(d).is_dir() else "[-] (missing)"
            print(f"    {i}. {d}  {exists}")


def reset_database() -> None:
    """Clear all embedded information by deleting ChromaDB and SQLite cache."""
    print()
    print("  ⚠️  WARNING: This will delete ALL indexed memories and vectors.")
    confirm = input("  Are you sure you want to reset the database? (y/N): ").strip().lower()
    
    if confirm != 'y':
        print("  [INFO] Reset cancelled.")
        return

    # Delete SQLite cache
    if SQLITE_CACHE.exists():
        try:
            SQLITE_CACHE.unlink()
            print("  [+] Deleted index cache (index_cache.db).")
        except Exception as e:
            print(f"  [ERROR] Could not delete index cache: {e}")

    # Delete ChromaDB
    if CHROMA_DIR.exists():
        try:
            shutil.rmtree(CHROMA_DIR)
            print("  [+] Deleted vector database (chroma_db/).")
        except Exception as e:
            print(f"  [ERROR] Could not delete vector database: {e}")

    print()
    print("  ✓ Database reset complete. Run `python bulk_index.py` to start fresh.")


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
  python config.py set-provider gemini    Set provider (gemini|openrouter|ollama|mistral)
  python config.py set-key                Set/update your active provider's API key
  python config.py delete-key             Remove your stored API key
  python config.py reset                  Reset the vector database and cache
        """,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List watch directories")

    p_provider = sub.add_parser("set-provider", help="Set the embedding provider (gemini, openrouter, ollama, mistral)")
    p_provider.add_argument("provider", choices=["gemini", "openrouter", "ollama", "mistral"], help="The provider to use")

    p_add = sub.add_parser("add", help="Add a watch directory")
    p_add.add_argument("path", help="Directory path to add")

    p_rm = sub.add_parser("remove", help="Remove a watch directory")
    p_rm.add_argument("path", help="Directory path to remove")

    sub.add_parser("set-key", help="Set/update active provider's API key")
    sub.add_parser("delete-key", help="Delete active provider's stored API key")
    sub.add_parser("reset", help="Clear the vector database and index cache to start fresh")

    args = parser.parse_args()

    if args.command == "list":
        list_watch_dirs()
    elif args.command == "set-provider":
        set_embedding_provider(args.provider)
    elif args.command == "add":
        add_watch_dir(args.path)
    elif args.command == "remove":
        remove_watch_dir(args.path)
    elif args.command == "set-key":
        provider = get_embedding_provider()
        if provider == "ollama":
            print("  [INFO] Ollama relies on your local daemon—no API key needed.")
        else:
            key = input(f"  Enter your {provider.capitalize()} API key: ").strip()
            if key:
                set_api_key(key, provider)
                print("  ✓ API key updated.")
            else:
                print("  [ERROR] No key entered.")
    elif args.command == "delete-key":
        delete_api_key()
        print("  [+] API key removed from Credential Manager.")
    elif args.command == "reset":
        reset_database()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
