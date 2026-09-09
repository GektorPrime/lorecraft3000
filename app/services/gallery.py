"""Uploaded gallery-picture persistence and image policy."""

from __future__ import annotations

import io
import math
import sqlite3

from PIL import Image, ImageOps

from app.domain.gallery import GalleryPicture
from app.storage import ImageStorage, ImageStorageError

MAX_TITLE_LENGTH = 120
MAX_FILENAME_LENGTH = 1024


class GalleryPictureError(Exception):
    pass


class GalleryPictureNotFoundError(GalleryPictureError):
    pass


class GalleryPictureValidationError(GalleryPictureError):
    pass


class GalleryPictureService:
    def __init__(self, conn: sqlite3.Connection, storage: ImageStorage) -> None:
        self.conn = conn
        self.storage = storage

    def upload(
        self, data: bytes, title: str, *, original_filename: str | None = None
    ) -> GalleryPicture:
        clean_title = self._title(title)
        clean_filename = self._filename(original_filename)
        try:
            image = self.storage.store(
                data,
                source_name=clean_filename,
                allowed_formats={"PNG", "JPEG", "WEBP"},
                reject_animated=True,
                max_width=8_192,
                max_height=8_192,
                max_pixels=40_000_000,
            )
        except ImageStorageError as exc:
            raise GalleryPictureValidationError(f"image rejected: {exc}") from exc
        with Image.open(io.BytesIO(data)) as opened:
            image_width, image_height = ImageOps.exif_transpose(opened).size
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO gallery_picture
                    (sha256, title, original_filename, image_width, image_height)
                VALUES (?, ?, ?, ?, ?)
                """,
                (image.sha256, clean_title, clean_filename, image_width, image_height),
            )
        return self.get(int(cursor.lastrowid))

    def list(self, *, include_archived: bool = False) -> list[GalleryPicture]:
        where = "" if include_archived else "WHERE archived_at IS NULL"
        rows = self.conn.execute(
            f"SELECT * FROM gallery_picture {where} ORDER BY created_at DESC, id DESC"
        ).fetchall()
        return [GalleryPicture.from_row(row) for row in rows]

    def get(self, picture_id: int) -> GalleryPicture:
        row = self.conn.execute(
            "SELECT * FROM gallery_picture WHERE id = ?", (picture_id,)
        ).fetchone()
        if row is None:
            raise GalleryPictureNotFoundError(f"gallery picture {picture_id} not found")
        return GalleryPicture.from_row(row)

    def content_sha(self, picture_id: int) -> str:
        return self.get(picture_id).sha256

    def archive(self, picture_id: int) -> GalleryPicture:
        self.get(picture_id)
        with self.conn:
            self.conn.execute(
                "UPDATE gallery_picture SET archived_at=datetime('now') "
                "WHERE id=? AND archived_at IS NULL",
                (picture_id,),
            )
        return self.get(picture_id)

    def restore(self, picture_id: int) -> GalleryPicture:
        self.get(picture_id)
        with self.conn:
            self.conn.execute(
                "UPDATE gallery_picture SET archived_at=NULL "
                "WHERE id=? AND archived_at IS NOT NULL",
                (picture_id,),
            )
        return self.get(picture_id)

    @staticmethod
    def aspect_ratio(picture: GalleryPicture) -> str:
        divisor = math.gcd(picture.image_width, picture.image_height)
        return f"{picture.image_width // divisor}:{picture.image_height // divisor}"

    @staticmethod
    def _title(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise GalleryPictureValidationError("gallery picture title is required")
        title = value.strip()
        if len(title) > MAX_TITLE_LENGTH:
            raise GalleryPictureValidationError(
                f"gallery picture title must be {MAX_TITLE_LENGTH} characters or fewer"
            )
        return title

    @staticmethod
    def _filename(value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if len(value) > MAX_FILENAME_LENGTH:
            raise GalleryPictureValidationError(
                f"original filename must be {MAX_FILENAME_LENGTH} characters or fewer"
            )
        return value
