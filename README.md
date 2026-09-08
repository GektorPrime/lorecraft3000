# LoreCraft3000

LoreCraft3000 is a local comic-generation studio: define your characters once, keep them recognizable across every scene, shape the visual style to taste, and assemble the results into multi-panel pages.

## Features

- Character library with immutable, versioned canonical reference sets
- Multi-character scenes with explicit reference-slot allocation
- Exact prompt and cost preview before any paid request
- Gemini and/or OpenAI image generation behind provider adapters,
  selected per scene by model
- Multi-turn image editing: refine a generated candidate with a natural-language
  instruction on the same provider, keeping character identity anchored
- Hard, configurable daily spending limit
- Advisory identity scoring: every candidate is matched against the scene
  cast's canonical reference gallery and scored per character, surfaced only
  in the UI (it never gates or auto-rejects) — see
  [docs/OPERATIONS.md](docs/OPERATIONS.md) for the one-time model setup
- Every image is filed under a fingerprint of its own contents 
  (so it's deduplicated, verifiable, and never overwritten), 
  and each one carries a full record of exactly how it was generated.
- Manual candidate review
- Panels assembled from accepted candidates with flexible layouts,
  adjustable crops, frames, and gutters, and deterministic panel render PNG export


## Setup

Prerequisites:
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 22.13+ (22.x) or 24+
- npm
- billed Gemini API key (and/or OpenAI API key).

```bash
uv sync
npm install
cp .env.example .env
```

Set `GEMINI_API_KEY` in `.env` (and/or `OPENAI_API_KEY`).
The default daily limit can be changed with
`LORECRAFT_DAILY_SPEND_CAP_USD`. Spend is counted from midnight in the browser's
local timezone; the database stores timestamps in UTC.

## Run in development

```bash
npm run dev
```

This starts FastAPI on <http://127.0.0.1:8000/> and the Vite frontend on
<http://127.0.0.1:5173/>. Open the Vite URL while developing. SQLite migrations
run automatically when FastAPI starts, and Vite proxies `/api/*` requests to
FastAPI.

To use the development app from another device on a trusted home network, run:

```bash
npm run dev:lan
```

Open the Network URL printed by Vite, such as `http://192.168.1.20:5173/`.
This exposes the unauthenticated development UI and its proxied API to devices
on the local network; do not use it on an untrusted network or expose the port
through the router. FastAPI remains bound to loopback and is reached through
Vite's same-origin proxy.

## Run the tests

```bash
npm test
```

This runs both the backend pytest suite and frontend Vitest suite. Run only the
backend suite with `uv run pytest` when needed.

The default suite uses fake providers and never makes paid requests. The live
Gemini and OpenAI smoke tests are skipped unless explicitly enabled. Enabling
them authorizes both paid calls and requires both provider API keys:

```bash
LORECRAFT_RUN_LIVE_TESTS=1 uv run pytest -m live
```

## Frontend (React + Vite)

The browser UI is a React + TypeScript frontend in `frontend/`, talking to the
backend over a typed JSON API under `/api/v1` (see `app/routes/api_v1/` and
`app/schemas.py`). Business logic stays in the Python services
(`app/services/`) — the frontend only renders and calls the API. The React
app is the only UI; there is no server-rendered fallback.

Frontend API types are generated from the backend's OpenAPI document, never
typed by hand: `app/scripts/generate_openapi.py` writes the current schema to
the committed snapshot `frontend/openapi.json`, and `npm run types` runs
[openapi-typescript](https://npmjs.com/package/openapi-typescript) over it,
producing `frontend/src/api/generated/types.d.ts`. `npm run build` regenerates
types first, so a backend DTO change that is not committed together with a
regenerated snapshot fails the build loudly instead of drifting.

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

This regenerates the API types (see the Frontend section), then writes
`frontend/dist/`. The frontend build is required to run the app: `app/main.py`
serves `frontend/dist/` at `/` (and its assets at `/assets/*`) — FastAPI is
then the single production server; no separate frontend server or reverse
proxy is required. Without a build present, `/` returns a short notice
pointing at `npm run build`. `frontend/dist/` is generated and gitignored, not
committed.

### Frontend tests

```bash
npm run test --workspace frontend
```

Uses [Vitest](https://vitest.dev/) with `@testing-library/react` (jsdom
environment, see `frontend/vite.config.ts` and `frontend/src/test/setup.ts`).

## Operating a running instance

See [docs/OPERATIONS.md](docs/OPERATIONS.md) for the operator runbook: backup
and restore, recovery after shutdown during generation, migration recovery,
storage consistency, and the health/readiness endpoints.

Two rules matter most:

- The SQLite database (`data/`) and the image store (`store/`) are one logical
  unit. Always back up, restore, and move them **together** and from the same
  moment. Restoring one without the other produces dangling references and is
  unsupported.
- Readiness is exposed at `GET /health` (503 until the database, migrations,
  and storage are all ready); liveness is at `GET /health/live`.

## Health endpoints

- `GET /health/live` — liveness; `200` whenever the process is up.
- `GET /health` — readiness; verifies database connectivity, that all
  migrations are applied, and that the image store is writable. Returns `200`
  with a per-check breakdown when ready, or `503` with the failing checks
  named. It is read-only and never runs the full consistency scan.
