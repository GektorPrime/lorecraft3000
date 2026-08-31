# LoreCraft3000

A locally hosted tool for generating comic panels with **persistent character
identity**. Single user, runs on localhost, no auth, no cloud deployment.

The full design and specification lives in
[documentation/agents.md](documentation/agents.md). The implementation plan is
in [documentation/phase-1-plan.md](documentation/phase-1-plan.md).

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# Install dependencies (runtime + dev) into the project-local .venv
uv sync

# Copy the example env and fill in your Gemini API key
cp .env.example .env
#   edit .env and set GEMINI_API_KEY=...
```

## Run the server

```bash
uv run uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/ in your browser. The home route returns a
working landing page; the database is initialized (idempotently) on startup.

## Run the tests

```bash
uv run pytest
```

The default suite never hits the network. It covers schema invariants, the
library and reference workflow, multi-character prompt assembly, cost guarding,
provider request construction, provenance, and a fake-provider generation path.
The paid Gemini smoke test is skipped unless explicitly authorized:

```bash
LORECRAFT_RUN_LIVE_TESTS=1 uv run pytest -m live
```

## Project layout

```
app/
  main.py          FastAPI app startup + routes
  config.py        settings from .env
  db.py            SQLite connection helpers (FK integrity on)
  migrate.py       migration runner (idempotent)
  migrations/      ordered migration modules
  storage.py       content-addressed image storage
  domain/          domain models and generation request values
  services/        library, cost ledger, and generation orchestration
  providers/       provider boundary and Gemini adapter
  assembler/       multi-character prompt and reference-slot assembly
  templates/       server-rendered Jinja templates
  static/          CSS and vendored HTMX
tests/             pytest suite
validate_refs.py   Phase 0 standalone utility (unchanged)
```

## Phase 0 utility

`validate_refs.py` remains a standalone Phase 0 utility and is not part of the
app package. Run it directly:

```bash
uv run python validate_refs.py        # dry run
uv run python validate_refs.py --go   # actually spends money
```
