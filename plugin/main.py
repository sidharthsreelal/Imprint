"""
Imprint — Flow Launcher Plugin
Semantic memory search from Flow Launcher.
Keyword: "im" (configurable in plugin.json)
"""

import subprocess
import urllib.request
import urllib.parse
import json
import os
import sys

# Add lib directory to path to use bundled dependencies
plugin_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(plugin_dir, "lib"))
sys.path.insert(0, os.path.dirname(plugin_dir))

from pyflowlauncher import Plugin, Result, send_results
from pyflowlauncher.result import ResultResponse

plugin = Plugin()

API_BASE = "http://localhost:8000"
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")


def _search_api(query: str, n: int = 12) -> list[dict] | None:
    """Call the Imprint search API."""
    try:
        params = urllib.parse.urlencode({"q": query, "n": n})
        url = f"{API_BASE}/search?{params}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data
    except Exception:
        return None


def _get_file_icon(path: str) -> str:
    """Return an appropriate icon path based on file extension."""
    # Flow Launcher can display file thumbnails via the file path itself
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        return path  # Show image thumbnail
    return ICON_PATH


def _open_containing_folder(path: str) -> None:
    """Open Explorer and select the file."""
    subprocess.Popen(f'explorer /select,"{path}"', shell=True)


def _open_file(path: str) -> None:
    """Open the file with its default application."""
    os.startfile(path)


@plugin.on_method
def query(query: str) -> ResultResponse:
    """Handle search queries from Flow Launcher."""
    if not query or not query.strip():
        return send_results([
            Result(
                Title="Imprint — Semantic Memory Search",
                SubTitle="Type a query to search your indexed files...",
                IcoPath=ICON_PATH,
            )
        ])

    results = _search_api(query.strip())

    if results is None:
        return send_results([
            Result(
                Title="⚠ Imprint server is not running",
                SubTitle="Start the server: python search_api.py",
                IcoPath=ICON_PATH,
            )
        ])

    if not results:
        return send_results([
            Result(
                Title="No results found",
                SubTitle=f"No matches for: {query}",
                IcoPath=ICON_PATH,
            )
        ])

    flow_results = []
    for r in results:
        path = r.get("path", "")
        name = r.get("name", "")
        score = r.get("score", 0)

        flow_results.append(Result(
            Title=f"{name}",
            SubTitle=f"{score:.1f}% match  •  {path}",
            IcoPath=_get_file_icon(path),
            JsonRPCAction={
                "method": "open_file",
                "parameters": [path],
            },
            ContextData=[path],
        ))

    return send_results(flow_results)


@plugin.on_method
def open_file(path: str) -> None:
    """Open the file with default application."""
    try:
        _open_file(path)
    except Exception:
        _open_containing_folder(path)


@plugin.on_method
def context_menu(data: list) -> ResultResponse:
    """Show context menu options for a result."""
    if not data:
        return send_results([])

    path = data[0]
    name = os.path.basename(path)

    return send_results([
        Result(
            Title=f"Open {name}",
            SubTitle="Open with default application",
            IcoPath=ICON_PATH,
            JsonRPCAction={
                "method": "open_file",
                "parameters": [path],
            },
        ),
        Result(
            Title="Show in Explorer",
            SubTitle=f"Open containing folder: {os.path.dirname(path)}",
            IcoPath=ICON_PATH,
            JsonRPCAction={
                "method": "open_in_explorer",
                "parameters": [path],
            },
        ),
    ])


@plugin.on_method
def open_in_explorer(path: str) -> None:
    """Open containing folder in Explorer with file selected."""
    _open_containing_folder(path)


if __name__ == "__main__":
    plugin.run()
