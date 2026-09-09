"""Domain values for user-uploaded gallery pictures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GalleryPicture:
    id: int
    sha256: str
    title: str
    original_filename: str | None
    image_width: int
    image_height: int
    created_at: str
    archived_at: str | None

    @classmethod
    def from_row(cls, row) -> "GalleryPicture":
        return cls(**{field: row[field] for field in cls.__dataclass_fields__})
