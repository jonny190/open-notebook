# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open Notebook is an open-source, privacy-focused alternative to Google's Notebook LM. AI-powered research assistant: upload multi-modal content (PDFs, audio, video, web pages), generate notes, search semantically, chat with AI, and produce multi-speaker podcasts. Self-hosted, multi-provider AI (16+ providers via Esperanto library).

## Development Commands

### Backend (Python/FastAPI)

```bash
# Install dependencies
uv sync

# Start SurrealDB (required first)
make database

# Start API server (port 5055, auto-reload enabled)
make api
# or: uv run --env-file .env run_api.py

# Start background worker (for async jobs: podcasts, embeddings)
make worker

# Start everything at once (DB + API + Worker + Frontend)
make start-all

# Stop all services
make stop-all

# Check service status
make status
```

### Frontend (Next.js/React)

```bash
cd frontend
npm install        # first time only
npm run dev        # dev server on port 3000
npm run build      # production build
npm run lint       # ESLint
npm run test       # Vitest (run once)
npm run test:watch # Vitest (watch mode)
```

### Testing & Linting

```bash
# Python tests
uv run pytest tests/                    # all tests
uv run pytest tests/test_domain.py      # single file
uv run pytest tests/test_domain.py -k "test_name"  # single test
uv run pytest --cov                     # with coverage

# Python linting
make ruff          # ruff check + fix
make lint          # mypy type checking
uv run ruff format .  # format code

# Frontend tests
cd frontend && npm run test
```

### Docker

```bash
make dev                # docker-compose dev mode (builds from source)
make docker-build-local # build production image locally
make docker-release     # build + push multi-platform images
```

## Architecture

Three-tier: **Frontend** (Next.js @ :3000) → **API** (FastAPI @ :5055) → **Database** (SurrealDB @ :8000).

```
frontend/              # Next.js 16, React 19, TypeScript
├── src/app/           # App Router pages (directory-based routing)
├── src/components/    # Feature components + Shadcn/ui primitives
├── src/lib/api/       # Axios client, resource-specific API modules
├── src/lib/hooks/     # TanStack Query wrappers, SSE streaming, chat hooks
├── src/lib/stores/    # Zustand state (auth, modals)
├── src/lib/locales/   # i18n translations (en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU)
└── src/lib/types/     # TypeScript type definitions

api/                   # FastAPI REST layer
├── main.py            # App init, CORS, auth middleware, router registration
├── routers/           # HTTP endpoint handlers
├── *_service.py       # Business logic orchestrating domain + graphs
└── models.py          # Pydantic request/response schemas

open_notebook/         # Core backend logic
├── domain/            # Data models (Notebook, Source, Note, Credential, etc.)
│   └── base.py        # ObjectModel (mutable) and RecordModel (singleton) base classes
├── graphs/            # LangGraph workflows (chat, ask, source, transformation)
├── ai/                # ModelManager, model provisioning, key_provider, connection_tester
├── database/          # SurrealDB repository pattern, async migrations
├── podcasts/          # Speaker/Episode profile models
└── utils/             # Chunking, embedding, context builder, text utils

commands/              # surreal-commands async job handlers (embedding, source processing, podcasts)
prompts/               # Jinja2 prompt templates organized by workflow (ask/, chat/, podcast/)
tests/                 # Pytest test suite
```

### Key Architectural Patterns

- **Async-first**: All DB, AI, and graph operations use async/await
- **LangGraph workflows**: State machines for chat, search (ask), content ingestion (source), and transformations. Use `provision_langchain_model()` for smart model selection with large-context fallback (>105k tokens)
- **Fire-and-forget jobs**: Domain model saves submit embedding commands via `surreal_commands`; jobs process asynchronously. Track via `/commands/{id}` endpoint
- **Multi-provider AI**: Esperanto library unifies 16+ providers. Credentials stored encrypted in SurrealDB (Fernet). Models can link to credentials directly, or fall back to env vars via `key_provider`
- **Database migrations**: Auto-run on API startup via `AsyncMigrationManager`. Migration files hard-coded in the manager class (not auto-discovered)
- **Polymorphic model loading**: `ObjectModel.get(id)` resolves subclass from SurrealDB record ID prefix (e.g., `notebook:123` → `Notebook`)

### Frontend Patterns

- **Data flow**: Pages → Hooks (TanStack Query) → API module (Axios) → Backend
- **State**: Zustand for auth/modal state, TanStack Query for server state with cache invalidation
- **i18n**: All UI strings go through `useTranslation()` hook with Proxy-based `t.section.key` access. All frontend changes must consider translation keys in `src/lib/locales/`
- **Components**: Shadcn/ui (Radix primitives + Tailwind CSS + CVA variants). Feature components in `components/{feature}/`, reusable primitives in `components/ui/`

## Important Gotchas

- **Start order**: SurrealDB must be running before API. API must be running before frontend
- **Async loop in graphs**: LangGraph nodes are sync but call async functions; uses `asyncio.new_event_loop()` workaround in `chat.py` and `source_chat.py`
- **`clean_thinking_content()`**: Strips `<think>...</think>` tags from model responses throughout the codebase
- **No connection pooling**: Each `repo_*` call opens/closes a SurrealDB connection (adequate for HTTP request scope)
- **RecordModel singletons**: `__new__` returns existing instance; call `clear_instance()` in tests
- **FormData handling**: Frontend interceptor removes Content-Type header for FormData requests (browser sets multipart boundary)
- **CORS open by default**: `api/main.py` allows all origins in dev

## Sub-Module CLAUDE.md Files

Detailed guidance for specific areas lives in child CLAUDE.md files:

- `frontend/src/CLAUDE.md` — React/Next.js architecture, data flow, component patterns
- `frontend/src/lib/locales/CLAUDE.md` — i18n system, how to add languages
- `api/CLAUDE.md` — FastAPI routes, services, credential management
- `open_notebook/domain/CLAUDE.md` — Data models, repository pattern, search
- `open_notebook/graphs/CLAUDE.md` — LangGraph workflow design
- `open_notebook/ai/CLAUDE.md` — ModelManager, provisioning, key_provider
- `open_notebook/database/CLAUDE.md` — SurrealDB ops, migrations
- `open_notebook/utils/CLAUDE.md` — Chunking, embedding, context builder
- `open_notebook/podcasts/CLAUDE.md` — Podcast profile models
- `commands/CLAUDE.md` — Async job handlers
- `prompts/CLAUDE.md` — Jinja2 prompt templates

## Configuration

- Copy `.env.example` to `.env` for backend config
- `OPEN_NOTEBOOK_ENCRYPTION_KEY` is required for credential storage
- AI provider keys can be set via env vars or through the UI (Settings → API Keys)
- See `docs/5-CONFIGURATION/` for full reference

## Contribution Workflow

Issue-first: create issue → get assigned → then code. Branch naming: `feature/`, `fix/`, `docs/`. PRs must reference an issue. See `docs/7-DEVELOPMENT/contributing.md`.
