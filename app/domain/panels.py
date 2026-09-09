"""Domain values for flexible panels."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class PanelSlot:
    id: int
    panel_id: int
    candidate_id: int | None
    gallery_picture_id: int | None
    slot_index: int
    x0: float
    y0: float
    x1: float
    y1: float
    focal_x: float
    focal_y: float
    zoom: float

    @classmethod
    def from_row(cls, row) -> "PanelSlot":
        return cls(**{field: row[field] for field in cls.__dataclass_fields__})


@dataclass(frozen=True)
class PanelRender:
    id: int
    panel_id: int
    panel_revision: int
    width: int
    height: int
    layout: dict
    created_at: str

    @classmethod
    def from_row(cls, row) -> "PanelRender":
        return cls(
            id=row["id"],
            panel_id=row["panel_id"],
            panel_revision=row["panel_revision"],
            width=row["width"],
            height=row["height"],
            layout=json.loads(row["layout_json"]),
            created_at=row["created_at"],
        )


@dataclass(frozen=True)
class Panel:
    id: int
    title: str
    format: str
    width_px: int
    height_px: int
    background_color: str
    gutter_px: int
    frame_px: int
    revision: int
    created_at: str
    updated_at: str
    slots: tuple[PanelSlot, ...] = ()
    latest_render: PanelRender | None = None
