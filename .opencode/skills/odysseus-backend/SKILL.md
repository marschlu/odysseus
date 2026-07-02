---
name: odysseus-backend
description: Use when working on the Odysseus backend. Covers the Python/FastAPI project layout, key modules (app.py, core/, src/, routes/), SQLAlchemy in core/database.py, route handler patterns, path constants from src/constants.py, internal_api_base() rule, dependencies, Docker layering, and architecture invariants (SSRF guards, path confinement, owner-scoped isolation, auth defaults).
---

# Odysseus backend

A Python 3.11+ **FastAPI** self-hosted AI workspace. Primary deployment is Docker; manual Python
setup is supported. This file covers everything about the server side.

- Project root: `/home/ryu/Documents/odysseus/` (run all commands from here).
- Git branch: work branches off **`dev`**; **`main`** is stable releases only. Never branch from
  or commit to `master`.

## Entry point and app structure

- **`app.py`** (~1,192 lines) — FastAPI application entrypoint. Uses `@asynccontextmanager`
  lifespan for startup/shutdown hooks. Run via:
  ```
  python -m uvicorn app:app --host 127.0.0.1 --port 7000
  ```
- **`setup.py`** — first-time setup (creates dirs, DB, admin user). Run once after clone.

## Source layout

| Directory | Contents |
|---|---|
| `core/` (10 files) | Database models (`core/database.py` ~2,265 lines, 28 SQLAlchemy classes), auth (`core/auth.py`), middleware (`core/middleware.py`), session management (`core/session_manager.py`), exceptions, platform compat |
| `src/` (99+ files) | Main application logic — flat modules. Key files: `llm_core.py` (LLM dispatch), `agent_loop.py` (agent orchestration), `tool_implementations.py` (agent tools), `builtin_actions.py`, `task_scheduler.py`, `ai_interaction.py`, `embeddings.py`, `memory.py`, `rag.py`, `constants.py` |
| `routes/` (54+ files) | HTTP route handlers — flat modules. Key files: `email_routes.py`, `cookbook_routes.py`, `model_routes.py`, `chat_routes.py`, `document_routes.py`, `gallery_routes.py`, `agent_routes.py` |
| `services/` | Service subdirectories: `docs/`, `faces/`, `hwfit/`, `memory/`, `research/`, `search/`, `shell/`, `stt/`, `tts/`, `youtube/` |
| `mcp_servers/` | MCP server implementations: `email_server.py`, `image_gen_server.py`, `memory_server.py`, `rag_server.py` |
| `integrations/` | Third-party integrations: Claude Code skill, Codex integration |
| `companion/` | Companion app pairing (`pairing.py`, `routes.py`) |
| `docker/` | Docker support: `entrypoint.sh`, GPU overlays (`gpu.nvidia.yml`, `gpu.amd.yml`) |

### Layering
```
core/ (db models, auth, middleware)
  └── src/ (business logic: LLM, agents, tools, search, memory, RAG)
        └── routes/ (HTTP handlers — thin, delegates to src/)
              └── services/ (subprocess-based service integrations)
                    └── integrations/ (third-party adapters)
```

## Key architecture patterns

- **FastAPI lifespan**: `@asynccontextmanager` lifespan for startup/shutdown hooks.
- **SQLAlchemy ORM**: All database models in `core/database.py` (28 classes, SQLite default).
  Route handlers in `routes/`. Business logic in `src/`.
- **LLM providers**: Abstracted via provider detection, endpoint probing, and model discovery.
  Supports local (Ollama, vLLM, llama.cpp, LM Studio) and remote (OpenAI, Anthropic, Gemini).
- **Agent system**: `src/agent_loop.py` core loop with MCP tools, skills, memory, and filesystem.
- **MCP (Model Context Protocol)**: Built-in MCP servers for email, memory, RAG, image generation.
- **Docker-first**: Docker Compose with odysseus + ChromaDB + SearXNG + ntfy.
- **Cookbook**: Hardware-aware model recommendations, downloads, and serving (tmux background procs).
- **PyInstaller**: Standalone builds for Windows/macOS via `Odysseus.spec` and `launcher.py`.

## Dependencies

- **Core**: `requirements.txt` (54 deps): FastAPI, Uvicorn, SQLAlchemy, httpx, Pydantic, bcrypt,
  chromadb-client, fastembed, aiofiles, python-multipart, etc.
- **Optional**: `requirements-optional.txt`: faster-whisper, PyMuPDF, markitdown, ddgs.
- **Python 3.11+** required (targeting 3.14 in Docker).

## Path and URL constants (critical — always use these)

File: `src/constants.py` — the single source of truth for paths and config.

- **Never hardcode writable paths.** Every persisted file/dir has a named constant:
  `AUTH_FILE`, `USER_PREFS_FILE`, `SETTINGS_FILE`, `TTS_CACHE_DIR`, `CHROMA_DIR`, `DATA_DIR`.
  Import and use the constant; don't re-derive with `os.path.join(DATA_DIR, "x.json")`.
  `DATA_DIR` reads `ODYSSEUS_DATA_DIR` env var. If a path has no constant yet, add one.
- **`internal_api_base()`** from `src.constants` — honors `ODYSSEUS_INTERNAL_BASE` / `APP_PORT`.
  Never hardcode `http://localhost:7000`.
- **`APP_VERSION`** from `src/constants.py` — single source for version string.
- **`core/constants.py`** is a backward-compat shim re-exporting from `src.constants`.

## Security posture (invariants — never break)

- **AUTH_ENABLED** by default; bcrypt password hashing; 2FA (TOTP) support.
- **SecurityHeadersMiddleware** for HTTP security headers.
- **API tokens** with user-scoped access.
- **Owner-scoped isolation** for all user data (sessions, documents, email, gallery, etc.).
- **SSRF guards** in outgoing HTTP requests.
- **Path confinement** — no writes outside allowed directories.
- **Rate limiting** built in.

## Build / test / run commands (run from project root)

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 7000          # dev server
python -m pytest                                                  # full test suite
python -m pytest tests/path/to/test_file.py --fast               # focused run
python -m py_compile app.py routes/*.py src/*.py                 # Python syntax check
node --check static/js/<file>.js                                  # JS syntax check
python setup.py                                                   # first-time setup
```

## Docker deployment

```bash
docker compose up -d --build        # full stack (odysseus + ChromaDB + SearXNG + ntfy)
docker compose logs --tail=120 odysseus
docker compose config               # validate compose file
```

GPU overlays:
```bash
docker compose -f docker-compose.yml -f docker/gpu.nvidia.yml up -d --build
```

## Known gotchas

- Source tree is **read-only in Docker** — guard directory creation so unwritable paths
  degrade gracefully instead of crashing at import.
- Windows is **not actively tested.** Docker on Linux or Linux/macOS manual install is safer.
- The `__init__.py` in `core/` re-exports from `src/` for backward compatibility.
- `core/constants.py` is a shim — prefer `src.constants` for new code.
