# LoreCraft3000

A local tool for generating Victorian oil-painting comic panels while keeping
multiple characters recognizable across scenes.

## Features

- Character library with immutable, versioned canonical reference sets
- Multi-character panels with explicit reference-slot allocation
- Exact prompt and cost preview before any paid request
- Gemini image generation behind a provider adapter
- Hard, configurable daily spending limit (`$3` by default)
- Content-addressed images with complete generation provenance
- Manual candidate review without automatically changing character canon

## Setup

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and a billed Gemini API
key.

```bash
uv sync
cp .env.example .env
```

Set `GEMINI_API_KEY` in `.env`. The default daily limit can be changed with
`LORECRAFT_DAILY_SPEND_CAP_USD`.

## Run the server

```bash
uv run uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/>. SQLite migrations run automatically at startup.

## Run the tests

```bash
uv run pytest
```

The default suite uses a fake provider and never makes paid requests. The live
Gemini smoke test is skipped unless explicitly enabled:

```bash
LORECRAFT_RUN_LIVE_TESTS=1 uv run pytest -m live
```
