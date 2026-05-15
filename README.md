# Imprint — Semantic Memory Search for Windows 🧠

Find any file on your computer by **meaning**, not just by its name. Powered by NVIDIA Nemotron (via OpenRouter) and integrated directly into Flow Launcher.

---

## What is this?
Ever tried to find a photo from a "sunset at the beach" or a specific "meeting notes about project X" but can't remember what you named the file? 

**Imprint** solves this by indexing your local files using semantic embeddings. It uses OpenRouter models to "look" at your images and "read" your PDFs/Text to understand their content. All descriptions are then stored in a local vector database (ChromaDB) for instant searching via Flow Launcher.

## Key Features
*   **📷 Image Understanding**: OpenRouter vision models generate rich descriptions for your media files.
*   **📄 Document Parsing**: Deep scanning of PDFs, Markdown, and Text files.
*   **🔍 Semantic Search**: Search for "aesthetic mountain view" even if the file is named `IMG_9213.jpg`.
*   **⚡ Real-time Updates**: Automatically indexes new files or changes as they happen.
*   **🔒 Privacy First**: Your files stay on your machine. Only extracted data is sent to the OpenRouter API for embedding.
*   **🔑 Secure**: API keys are stored in Windows Credential Manager, not in clear text files.

---

## 🛠️ Quick Start Guide

### 1. The Essentials
*   **Python 3.11+** installed and added to your system PATH.
*   **Flow Launcher** (the UI for searching).
*   **OpenRouter API Key**: Grab one at [OpenRouter](https://openrouter.ai/).

### 2. Installation
Clone the repo and install the Python dependencies:
```powershell
pip install -r requirements.txt
pip install pyflowlauncher
```

### 3. Link to Flow Launcher
To make Imprint searchable in Flow Launcher, you need to copy the plugin files:
1.  Navigate to `D:\Projects\Imprint\plugin\` (or wherever you cloned this).
2.  Copy all files inside and paste them into `%APPDATA%\FlowLauncher\Plugins\Imprint`.
3.  **Restart Flow Launcher** (Right-click tray icon → Restart).

### 4. Setup & Indexing
Run these commands to tell Imprint what to watch and get your first index going:

```powershell
# 1. Set your API key (will prompt you)
python config.py set-key

# 2. Add folders you want to search
python config.py add "C:\Users\YourName\Pictures"
python config.py add "C:\Users\YourName\Documents"

# 3. Initial scan of existing files (grab a coffee, might take a bit)
python bulk_index.py
```

### 5. Running the Service
Imprint needs a background service to handle search queries and monitor file changes.
```powershell
python start.py
```
*(Tip: Add a shortcut to this script in your Windows Startup folder to have it always ready.)*

---

## 🚀 Usage
Once it's running, just open Flow Launcher (`Alt + Space`) and use the **`im`** prefix:

*   `im aesthetic sunset with orange clouds`
*   `im meeting notes about the new dashboard`
*   `im picture of a cat sitting on a laptop`

---

## 🔧 Commands
| Command | Purpose |
| :--- | :--- |
| `python start.py` | Starts the Search API + File Watcher (Run this to use Imprint). |
| `python config.py add "path"` | Adds a new directory to the search index. |
| `python config.py list` | Shows all currently watched folders. |
| `python bulk_index.py` | Re-scans all folders for missed or new files. |

## How it works (The Dev stuff)
1.  **Watcher**: Uses `watchdog` to monitor your folders.
2.  **Embedder**: Uses OpenRouter (NVIDIA Nemotron models) to generate captions for images and text embeddings for everything else.
3.  **Local DB**: Stores everything in **ChromaDB** with a small SQLite cache for file tracking.
4.  **Flow API**: A tiny FastAPI server that Flow Launcher queries for lightning-fast results.

---

*Made with love for people who can't remember where they saved their stuff.*
