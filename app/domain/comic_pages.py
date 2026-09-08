"""Domain values for template-based comic pages."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class ComicPagePanel:
    id: int
    page_id: int
    candidate_id: int
    slot_index: int
    focal_x: float
    focal_y: float
    zoom: float

    @classmethod
    def from_row(cls, row) -> "ComicPagePanel":
        return cls(**{field: row[field] for field in cls.__dataclass_fields__})


@dataclass(frozen=True)
class PageRender:
    id: int
    page_id: int
    page_revision: int
    width: int
    height: int
    layout: dict
    created_at: str

    @classmethod
    def from_row(cls, row) -> "PageRender":
        return cls(
            id=row["id"],
            page_id=row["page_id"],
            page_revision=row["page_revision"],
            width=row["width"],
            height=row["height"],
            layout=json.loads(row["layout_json"]),
            created_at=row["created_at"],
        )


@dataclass(frozen=True)
class ComicPage:
    id: int
    title: str
    format: str
    width_px: int
    height_px: int
    background_color: str
    gutter_px: int
    template_key: str
    template_version: int
    divider_values: list[float]
    revision: int
    created_at: str
    updated_at: str
    panels: tuple[ComicPagePanel, ...] = ()
    latest_render: PageRender | None = None
