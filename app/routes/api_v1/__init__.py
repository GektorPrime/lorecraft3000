"""Typed JSON API for the React frontend (issue #15).

Every route here returns/accepts the Pydantic DTOs in app/schemas.py — never
raw sqlite3.Row objects or service dataclasses directly — so the wire shape is
explicit and versioned independently of the resource routers below.

All business logic stays in app/services/*; route modules only translate
between the service layer and the API's typed request/response shapes, and map
service exceptions to a consistent error envelope
(``{"detail": {"message": ..., "type": ...}}``).

The former single module (app/routes/api_v1.py) was split by resource:
options, characters, styles, ref_sets, scenes, and generations, with shared
helpers in _common.py. Paths, methods, status codes, response bodies, and the
error envelope are unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routes.api_v1 import (
    base_stages,
    characters,
    generations,
    options,
    scenes,
    ref_sets,
    styles,
)

router = APIRouter(tags=["api-v1"])

router.include_router(options.router)
router.include_router(base_stages.router)
router.include_router(characters.router)
router.include_router(styles.router)
router.include_router(ref_sets.router)
router.include_router(scenes.router)
router.include_router(generations.router)
