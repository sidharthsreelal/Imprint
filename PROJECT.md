# Imprint
> Semantic search utility

**Stack:** Python, ChromaDB
**Repo:** sidharthsreelal/Imprint

---

## State

### In Progress
[Removed rate limit retry timeouts for Mistral models. A 429 now fails the file immediately instead of blocking the indexing queue.]

### Next
1. Run `python bulk_index.py` to start indexing with Mistral.
2. (Optional) `python config.py set-provider <provider>` to switch; Mistral fallback is always active via `.env.local`.

### Known Issues
- OpenRouter imposes a strict 50 request-per-day limit on `free-models-per-day` for un-funded accounts. This restricts bulk indexing large directories.

### Decisions
- [2026-04-13] Initialized PROJECT.md log
- [2026-04-13] Transitioned embedding provider from Gemini to OpenRouter mapping to Llama Nemotron Embed VL 1B V2 (free) and Nemotron Nano 12B Vision.
- [2026-04-13] Extended `embedder.py` error handling to correctly parse and abort on OpenRouter's 429 quota exhaustion messages to avoid confusing retry loops.
- [2026-04-13] Established tool-specific log headers: This agent uses `Antigravity`, while external tools (like Gemini CLI) continue using `Gemini CLI`.
- [2026-04-13] Extended `config.py` and `embedder.py` to support dynamic routing between Gemini, OpenRouter, and Ollama.
- [2026-04-13] Allowed dynamic naming of ChromaDB collections and SQLite caches based on active embedding models to prevent dimension mismatch errors across different providers.
- [2026-05-15] Added Mistral as a 4th provider. Mistral API key is intentionally sourced from `.env.local` (not Windows Credential Manager) per user requirement.
- [2026-05-15] Fixed: old `config.json` had `ollama` as provider, causing Ollama to be used even though Ollama wasn't running. Added `_resolve_active_provider()` to `embedder.py` — Mistral/.env.local is the always-on default; other providers only activate when the user explicitly sets them AND a valid key exists.
- [2026-05-15] Added `python config.py reset` command to simplify deleting the vector database and SQLite cache.
- [2026-05-15] Updated Mistral vision model default to `mistral-medium-latest` to provide better image descriptions.
- [2026-05-15] Removed rate limit wait (429 exception) for Mistral endpoints. Rate-limited files now silently fail and get skipped rather than pausing the entire indexer.

---

## Log
<!-- Newest entries at the top. Never edit old entries. -->

### [2026-04-13] · Antigravity
**Done this session:**
- Modified `config.py` to manage `embedding_provider` ("gemini", "openrouter", "ollama") dynamically via `python config.py set-provider <provider>`.
- Modified credential management to use a unique API key for each provider in Windows Credential Manager.
- Refactored `embedder.py`'s `_get_embedding` and `_describe_image_for_embedding` to interface with Gemini via HTTP `requests`, mapped OpenRouter endpoints dynamically, and added local backend support for Ollama.
- Ensured that ChromaDB collections and SQLite cache tables derive their names strictly from the active configured embedding model to avoid dimension mismatches and invalid cache hits when switching providers.

**Decisions:**
- Made the default model set dynamic based on the provider selection to reduce configuration friction for the user.
- Bound cache database names and ChromaDB collection names to the clean string representation of the currently active model.

**Left off at:**
Task complete. Imprint allows selecting OpenRouter, Gemini, or Ollama, with configuration via `config.py set-provider`.

**Next up from here:**
1. User testing of the selected API or local Ollama endpoint.
2. Perform index over the directories.

---

### [2026-04-13] · Antigravity
**Done this session:**
- Fixed a critical bug in `embedder.py` where OpenRouter 429 errors were being swallowed, preventing the script from detecting daily quota exhaustion.
- Expanded `_is_daily_quota_error` to catch OpenRouter-specific strings (`per-day`, `credits`, `balance`).
- Documented tool-specific identity convention in `PROJECT.md` to ensure `Antigravity` and `Gemini CLI` logs are distinct.
- Confirmed total progress: 87/420 files indexed.

**Decisions:**
- Decided to hard-abort on 429 quota messages to save CPU/Network instead of retrying 65s into a dead limit.
- Named this tool `Antigravity` in all future log headers to differentiate from other CLI tools.

**Left off at:**
`bulk_index.py` aborted because OpenRouter's 50-req/day limit is exhausted (Remaining: 0).

**Next up from here:**
1. Wait for quota reset or top up credits.
2. Complete indexing of the remaining 333 files.

---

### [2026-04-13] · Antigravity
**Done this session:**
- Investigated `bulk_index.py` failures via `errors.log` identifying a ChromaDB collection dimension mismatch (`Collection expecting embedding with dimension of 3072, got 2048`).
- Cleared the stale `index_cache.db` tracker.
- Renamed the ChromaDB collection in `embedder.py` from `memories` to `imprint_nemotron` to force a clean instantiation in `chroma_db` skipping locked SQLite files.

**Decisions:**
- Decided to rename ChromaDB collection instead of writing Windows forced-deletion scripts for existing indices, providing an instant unblock without battling locked memory states.

**Left off at:**
Task complete. `bulk_index.py` is safely processing OpenRouter embeddings without dimension mismatches.

**Next up from here:**
1. Let the `bulk_index.py` job finish in the background.
2. Consider adding dynamic DB trimming for old collections down the road if they mount up in storage size.

---

### [2026-04-13] · Antigravity
**Done this session:**
- Migrated code from `google-genai` to pure HTTP `requests` securely for the API pipeline.
- Stored OpenRouter API Key `sk-or...` into Windows Credential Manager under `openrouter_api_key` and deleted old `gemini_api_key`.
- Updated `embedder.py` implementations to embed using `nvidia/llama-nemotron-embed-vl-1b-v2:free`.
- Updated `embedder.py` descriptions to use `nvidia/nemotron-nano-12b-v2-vl:free` for compatible image parsing.
- Refactored `config.py`, `bulk_index.py`, `requirements.txt`, and `README.md` to replace mentions of Gemini with OpenRouter.

**Decisions:**
- Deprecated media parsing (video/audio) temporarily because OpenRouter standard `/chat/completions` explicitly handles only text and imagery on vision models.
- Set embedding model specifically to the Llama Nemotron Embed VL 1B V2 per user requirements and image analysis strictly to Nemotron Vision 12B mapping.

**Left off at:**
Task complete. Imprint is now operating out of OpenRouter with the Nemotron models.

**Next up from here:**
1. User testing of `bulk_index.py` using new OpenRouter config.
2. Implement additional support for tracking Audio/Video mapping if a suitable open model allows later on OpenRouter.

---

