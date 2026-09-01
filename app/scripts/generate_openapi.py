"""Write the backend's OpenAPI document to the committed frontend snapshot.

The React frontend generates its api types (openapi-typescript) from
``frontend/openapi.json`` (see frontend/package.json "types" script) so the two
halves cannot drift. This script rebuilds the FastAPI app in-process and writes
the current schema — no running server required.

Usage:

    uv run python -m app.scripts.generate_openapi

After touching app/routes/api_v1/*, app/schemas.py, or any DTO the routes
reference, regenerate the snapshot and commit it together with the change.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app

FRONTEND_OPENAPI = (
    Path(__file__).resolve().parent.parent.parent / "frontend" / "openapi.json"
)


def main() -> None:
    schema = app.openapi()
    FRONTEND_OPENAPI.write_text(
        json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"wrote {FRONTEND_OPENAPI} ({len(schema['paths'])} paths)")


if __name__ == "__main__":
    main()