"""Deterministic Pillow compositor for comic-page revisions."""

from __future__ import annotations

import io
import json
import sqlite3

from PIL import Image, ImageColor, ImageOps, UnidentifiedImageError

from app.domain.comic_pages import PageRender
from app.services.comic_pages import (
    PageIncompleteError,
    PageRevisionConflictError,
    PageService,
    template_rectangles,
)
from app.storage import ImageStorage, ImageStorageError


class PageRenderService:
    def __init__(self, conn: sqlite3.Connection, storage: ImageStorage) -> None:
        self.conn = conn
        self.storage = storage

    def render(self, page_id: int, *, expected_revision: int) -> PageRender:
        pages = PageService(self.conn)
        page = pages.get(page_id)
        if page.revision != expected_revision:
            raise PageRevisionConflictError(
                f"page {page_id} is revision {page.revision}, not {expected_revision}"
            )
        existing = self.conn.execute(
            "SELECT * FROM page_render WHERE page_id = ? AND page_revision = ?",
            (page_id, expected_revision),
        ).fetchone()
        if existing:
            return PageRender.from_row(existing)

        normalized = template_rectangles(page.template_key, page.divider_values)
        if {panel.slot_index for panel in page.panels} != set(range(len(normalized))):
            raise PageIncompleteError("every template slot must be filled before rendering")

        canvas = Image.new(
            "RGB", (page.width_px, page.height_px), ImageColor.getrgb(page.background_color)
        )
        snapshot_panels: list[dict] = []
        for panel in page.panels:
            target = self._target_rect(
                normalized[panel.slot_index], page.width_px, page.height_px, page.gutter_px
            )
            target_width, target_height = target[2] - target[0], target[3] - target[1]
            candidate = self.conn.execute(
                "SELECT sha256 FROM candidate WHERE id = ?", (panel.candidate_id,)
            ).fetchone()
            if candidate is None:  # The panel FK should make this impossible.
                raise ImageStorageError(f"candidate {panel.candidate_id} image is unavailable")
            source_bytes, _ = self.storage.read(candidate["sha256"])
            try:
                with Image.open(io.BytesIO(source_bytes)) as opened:
                    source = ImageOps.exif_transpose(opened).convert("RGB")
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                raise ImageStorageError(f"candidate {panel.candidate_id} is not decodable: {exc}") from exc
            crop = self._crop_box(
                source.width, source.height, target_width / target_height,
                panel.focal_x, panel.focal_y, panel.zoom,
            )
            rendered = source.crop(crop).resize(
                (target_width, target_height), Image.Resampling.LANCZOS
            )
            canvas.paste(rendered, (target[0], target[1]))
            snapshot_panels.append(
                {
                    "slot_index": panel.slot_index,
                    "candidate_id": panel.candidate_id,
                    "target_rect": list(target),
                    "source_size": [source.width, source.height],
                    "source_crop": [round(value, 6) for value in crop],
                    "focal_x": panel.focal_x,
                    "focal_y": panel.focal_y,
                    "zoom": panel.zoom,
                }
            )

        layout = {
            "template_key": page.template_key,
            "template_version": page.template_version,
            "divider_values": page.divider_values,
            "gutter_px": page.gutter_px,
            "background_color": page.background_color,
            "panels": snapshot_panels,
        }
        output = io.BytesIO()
        canvas.save(output, format="PNG", compress_level=9)
        stored = self.storage.store(output.getvalue(), source_name=f"page-{page_id}-r{expected_revision}.png")

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            current = self.conn.execute(
                "SELECT revision FROM comic_page WHERE id = ?", (page_id,)
            ).fetchone()
            if current is None or current["revision"] != expected_revision:
                raise PageRevisionConflictError(f"page {page_id} changed during rendering")
            existing = self.conn.execute(
                "SELECT * FROM page_render WHERE page_id = ? AND page_revision = ?",
                (page_id, expected_revision),
            ).fetchone()
            if existing:
                self.conn.commit()
                return PageRender.from_row(existing)
            cursor = self.conn.execute(
                """
                INSERT INTO page_render
                    (page_id, page_revision, sha256, width, height, layout_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (page_id, expected_revision, stored.sha256, page.width_px, page.height_px,
                 json.dumps(layout, sort_keys=True, separators=(",", ":"))),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return PageRender.from_row(
            self.conn.execute("SELECT * FROM page_render WHERE id = ?", (cursor.lastrowid,)).fetchone()
        )

    @staticmethod
    def _target_rect(rect, width: int, height: int, gutter: int) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = rect
        left, top = round(x0 * width), round(y0 * height)
        right, bottom = round(x1 * width), round(y1 * height)
        before, after = gutter // 2, gutter - gutter // 2
        if x0 > 0:
            left += after
        if x1 < 1:
            right -= before
        if y0 > 0:
            top += after
        if y1 < 1:
            bottom -= before
        return left, top, right, bottom

    @staticmethod
    def _crop_box(
        source_width: int, source_height: int, target_aspect: float,
        focal_x: float, focal_y: float, zoom: float,
    ) -> tuple[float, float, float, float]:
        if source_width / source_height >= target_aspect:
            crop_height = source_height / zoom
            crop_width = crop_height * target_aspect
        else:
            crop_width = source_width / zoom
            crop_height = crop_width / target_aspect
        center_x, center_y = focal_x * source_width, focal_y * source_height
        left = min(max(center_x - crop_width / 2, 0.0), source_width - crop_width)
        top = min(max(center_y - crop_height / 2, 0.0), source_height - crop_height)
        # Keep tiny floating-point excursions out of Pillow and the snapshot.
        left, top = max(0.0, left), max(0.0, top)
        return left, top, min(source_width, left + crop_width), min(source_height, top + crop_height)
