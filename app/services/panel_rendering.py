"""Deterministic Pillow compositor for panel revisions."""

from __future__ import annotations

import io
import json
import sqlite3

from PIL import Image, ImageColor, ImageOps, UnidentifiedImageError

from app.domain.panels import PanelRender
from app.services.panels import (
    PanelIncompleteError,
    PanelRevisionConflictError,
    PanelService,
    PanelValidationError,
)
from app.storage import ImageStorage, ImageStorageError


class PanelRenderService:
    def __init__(self, conn: sqlite3.Connection, storage: ImageStorage) -> None:
        self.conn = conn
        self.storage = storage

    def render(self, panel_id: int, *, expected_revision: int) -> PanelRender:
        panels = PanelService(self.conn)
        panel = panels.get(panel_id)
        if panel.revision != expected_revision:
            raise PanelRevisionConflictError(
                f"panel {panel_id} is revision {panel.revision}, not {expected_revision}"
            )
        existing = self.conn.execute(
            "SELECT * FROM panel_render WHERE panel_id = ? AND panel_revision = ?",
            (panel_id, expected_revision),
        ).fetchone()
        if existing:
            return PanelRender.from_row(existing)

        if not panel.slots or any(slot.candidate_id is None for slot in panel.slots):
            raise PanelIncompleteError("every panel slot must be filled before rendering")

        canvas = Image.new(
            "RGB", (panel.width_px, panel.height_px), ImageColor.getrgb(panel.background_color)
        )
        snapshot_slots: list[dict] = []
        for slot in panel.slots:
            target = self._target_rect(
                (slot.x0, slot.y0, slot.x1, slot.y1),
                panel.width_px, panel.height_px, panel.gutter_px, panel.frame_px,
            )
            target_width, target_height = target[2] - target[0], target[3] - target[1]
            if target_width <= 0 or target_height <= 0:
                raise PanelValidationError(
                    f"frame and gutter leave panel slot {slot.slot_index} without a positive target"
                )
            candidate = self.conn.execute(
                "SELECT sha256 FROM candidate WHERE id = ?", (slot.candidate_id,)
            ).fetchone()
            if candidate is None:  # The panel slot FK should make this impossible.
                raise ImageStorageError(f"candidate {slot.candidate_id} image is unavailable")
            source_bytes, _ = self.storage.read(candidate["sha256"])
            try:
                with Image.open(io.BytesIO(source_bytes)) as opened:
                    source = ImageOps.exif_transpose(opened).convert("RGB")
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                raise ImageStorageError(f"candidate {slot.candidate_id} is not decodable: {exc}") from exc
            crop = self._crop_box(
                source.width, source.height, target_width / target_height,
                slot.focal_x, slot.focal_y, slot.zoom,
            )
            rendered = source.crop(crop).resize(
                (target_width, target_height), Image.Resampling.LANCZOS
            )
            canvas.paste(rendered, (target[0], target[1]))
            snapshot_slots.append(
                {
                    "slot_index": slot.slot_index,
                    "candidate_id": slot.candidate_id,
                    "x0": slot.x0,
                    "y0": slot.y0,
                    "x1": slot.x1,
                    "y1": slot.y1,
                    "target_rect": list(target),
                    "source_size": [source.width, source.height],
                    "source_crop": [round(value, 6) for value in crop],
                    "focal_x": slot.focal_x,
                    "focal_y": slot.focal_y,
                    "zoom": slot.zoom,
                }
            )

        layout = {
            "gutter_px": panel.gutter_px,
            "frame_px": panel.frame_px,
            "background_color": panel.background_color,
            "slots": snapshot_slots,
        }
        output = io.BytesIO()
        canvas.save(output, format="PNG", compress_level=9)
        stored = self.storage.store(output.getvalue(), source_name=f"panel-{panel_id}-r{expected_revision}.png")

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            current = self.conn.execute(
                "SELECT revision FROM panel WHERE id = ?", (panel_id,)
            ).fetchone()
            if current is None or current["revision"] != expected_revision:
                raise PanelRevisionConflictError(f"panel {panel_id} changed during rendering")
            existing = self.conn.execute(
                "SELECT * FROM panel_render WHERE panel_id = ? AND panel_revision = ?",
                (panel_id, expected_revision),
            ).fetchone()
            if existing:
                self.conn.commit()
                return PanelRender.from_row(existing)
            cursor = self.conn.execute(
                """
                INSERT INTO panel_render
                    (panel_id, panel_revision, sha256, width, height, layout_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (panel_id, expected_revision, stored.sha256, panel.width_px, panel.height_px,
                 json.dumps(layout, sort_keys=True, separators=(",", ":"))),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return PanelRender.from_row(
            self.conn.execute("SELECT * FROM panel_render WHERE id = ?", (cursor.lastrowid,)).fetchone()
        )

    @staticmethod
    def _target_rect(
        rect, width: int, height: int, gutter: int, frame: int
    ) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = rect
        content_width, content_height = width - 2 * frame, height - 2 * frame
        left, top = round(frame + x0 * content_width), round(frame + y0 * content_height)
        right = round(frame + x1 * content_width)
        bottom = round(frame + y1 * content_height)
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
