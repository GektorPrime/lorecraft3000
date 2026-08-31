# LoreCraft3000

A local tool for generating comic panels while keeping multiple characters
recognizable across scenes. Visual styles are editable; Victorian Oil Painting
is included as the initial default.

## Features

- Character library with immutable, versioned canonical reference sets
- Multi-character panels with explicit reference-slot allocation
- Exact prompt and cost preview before any paid request
- Gemini image generation behind a provider adapter
- Hard, configurable daily spending limit (`$3` by default)
- Content-addressed images with complete generation provenance
- Manual candidate review without automatically changing character canon
- Typed `/api/v1` JSON API backing a separated React + Vite frontend
  (`frontend/`), with a legacy server-rendered UI kept for compatibility

## Setup

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 20+, npm, and a
billed Gemini API key.

```bash
uv sync
npm install
cp .env.example .env
```

Set `GEMINI_API_KEY` in `.env`. The default daily limit can be changed with
`LORECRAFT_DAILY_SPEND_CAP_USD`.

## Run in development

```bash
npm run dev
```

This starts FastAPI on <http://127.0.0.1:8000/> and the Vite frontend on
<http://127.0.0.1:5173/>. Open the Vite URL while developing. SQLite migrations
run automatically when FastAPI starts, and Vite proxies `/api/*` requests to
FastAPI.

## Run the tests

```bash
npm test
```

This runs both the backend pytest suite and frontend Vitest suite. Run only the
backend suite with `uv run pytest` when needed.

The default suite uses a fake provider and never makes paid requests. The live
Gemini smoke test is skipped unless explicitly enabled:

```bash
LORECRAFT_RUN_LIVE_TESTS=1 uv run pytest -m live
```

## Frontend (React + Vite)

The primary browser UI is a separated React + TypeScript frontend in
`frontend/`, talking to the backend over a typed JSON API under
`/api/v1` (see `app/routes/api_v1.py` and `app/schemas.py`). Business logic
stays in the Python services (`app/services/`) — the frontend only renders
and calls the API. A legacy server-rendered Jinja UI (`app/templates/`)
remains mounted at its original routes for backward compatibility; the React
app uses hash-based client routes (e.g. `/#/characters`) specifically so it
never collides with those paths.

### Run in development

```bash
npm run dev
```

The root npm workspace uses `concurrently` to run FastAPI and Vite in one
terminal. Stopping the command stops both processes. Vite proxies `/api/*`
requests to FastAPI on `127.0.0.1:8000` (see `frontend/vite.config.ts`);
override the target with `VITE_BACKEND_URL` if the backend runs elsewhere.
If the default ports are occupied, override them together:

```bash
BACKEND_PORT=8010 FRONTEND_PORT=5174 \
VITE_BACKEND_URL=http://127.0.0.1:8010 npm run dev
```

### Build for production

```bash
npm run build
```

This writes `frontend/dist/`. When that directory exists, `app/main.py`
serves it directly at `/` (and its assets at `/assets/*`) — FastAPI is then
the single production server; no separate frontend server or reverse proxy
is required. `frontend/dist/` is generated and gitignored, not committed.

### Frontend tests

```bash
npm run test --workspace frontend
```

Uses [Vitest](https://vitest.dev/) with `@testing-library/react` (jsdom
environment, see `frontend/vite.config.ts` and `frontend/src/test/setup.ts`).
