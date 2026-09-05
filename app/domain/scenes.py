"""Scene/panel domain values."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Scene:
    id: int
    beat_text: str
    camera: str
    framing: str
    mood: str
    aspect_ratio: str
    cast: list[dict]
    style_id: int | None
    base_stage_id: int | None
    model: str
    image_size: str
    created_at: str

    @classmethod
    def from_row(cls, row) -> "Scene":
        return cls(
            id=row["id"],
            beat_text=row["beat_text"],
            camera=row["camera"],
            framing=row["framing"],
            mood=row["mood"],
            aspect_ratio=row["aspect_ratio"],
            cast=json.loads(row["cast_json"]),
            style_id=row["style_id"],
            base_stage_id=row["base_stage_id"],
            model=row["model"],
            image_size=row["image_size"],
            created_at=row["created_at"],
        )
