"""Persistence and strict validation for panel aggregates."""

from __future__ import annotations

import math
import re
import sqlite3

from app.domain.panels import Panel, PanelRender, PanelSlot

FORMATS = {
    "portrait": (1200, 1800),
    "square": (1600, 1600),
    "landscape": (1800, 1200),
}
_COLOR = re.compile(r"^#[0-9A-F]{6}$")
_AREA_TOLERANCE = 1e-9


class PanelError(Exception):
    pass


class PanelNotFoundError(PanelError):
    pass


class PanelValidationError(PanelError):
    pass


class PanelRevisionConflictError(PanelError):
    pass


class PanelCandidateConflictError(PanelError):
    pass


class PanelIncompleteError(PanelError):
    pass


class PanelRenderNotFoundError(PanelError):
    pass


class PanelService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list(self) -> list[Panel]:
        rows = self.conn.execute("SELECT id FROM panel ORDER BY updated_at DESC, id DESC").fetchall()
        return [self.get(row["id"]) for row in rows]

    def get(self, panel_id: int) -> Panel:
        row = self.conn.execute("SELECT * FROM panel WHERE id = ?", (panel_id,)).fetchone()
        if row is None:
            raise PanelNotFoundError(f"panel {panel_id} not found")
        slots = self.conn.execute(
            "SELECT * FROM panel_slot WHERE panel_id = ? ORDER BY slot_index", (panel_id,)
        ).fetchall()
        render = self.conn.execute(
            "SELECT * FROM panel_render WHERE panel_id = ? ORDER BY panel_revision DESC, id DESC LIMIT 1",
            (panel_id,),
        ).fetchone()
        return Panel(
            id=row["id"], title=row["title"], format=row["format"],
            width_px=row["width_px"], height_px=row["height_px"],
            background_color=row["background_color"], gutter_px=row["gutter_px"],
            frame_px=row["frame_px"], revision=row["revision"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            slots=tuple(PanelSlot.from_row(slot) for slot in slots),
            latest_render=PanelRender.from_row(render) if render else None,
        )

    def create(
        self,
        *,
        title: str,
        format: str,
        rows: int = 1,
        columns: int = 1,
        candidate_id: int | None = None,
    ) -> Panel:
        title = self._title(title)
        width, height = self._format(format)
        if any(isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8
               for value in (rows, columns)):
            raise PanelValidationError("panel rows and columns must be integers from 1 to 8")
        if rows * columns > 64:
            raise PanelValidationError("a panel may have at most 64 slots")
        if candidate_id is not None and (
            isinstance(candidate_id, bool)
            or not isinstance(candidate_id, int)
            or candidate_id < 1
        ):
            raise PanelValidationError("candidate id must be null or a positive integer")
        slots = [
            {
                "candidate_id": candidate_id if row == 0 and column == 0 else None,
                "slot_index": row * columns + column,
                "x0": column / columns,
                "y0": row / rows,
                "x1": (column + 1) / columns,
                "y1": (row + 1) / rows,
                "focal_x": 0.5,
                "focal_y": 0.5,
                "zoom": 1.0,
            }
            for row in range(rows)
            for column in range(columns)
        ]
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._validate_candidates(slots, set())
            cursor = self.conn.execute(
                "INSERT INTO panel (title, format, width_px, height_px) VALUES (?, ?, ?, ?)",
                (title, format, width, height),
            )
            self.conn.executemany(
                "INSERT INTO panel_slot "
                "(panel_id, candidate_id, slot_index, x0, y0, x1, y1, focal_x, focal_y, zoom) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(cursor.lastrowid, slot["candidate_id"], slot["slot_index"],
                  slot["x0"], slot["y0"], slot["x1"], slot["y1"],
                  slot["focal_x"], slot["focal_y"], slot["zoom"]) for slot in slots],
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self.get(int(cursor.lastrowid))

    def update(
        self, panel_id: int, *, expected_revision: int, title: str, format: str,
        background_color: str, gutter_px: int, frame_px: int, slots: list[dict],
    ) -> Panel:
        title = self._title(title)
        width, height = self._format(format)
        self._validate_layout(slots)
        if not _COLOR.fullmatch(background_color):
            raise PanelValidationError("background color must be uppercase #RRGGBB")
        if isinstance(gutter_px, bool) or not isinstance(gutter_px, int) or not 0 <= gutter_px <= 80:
            raise PanelValidationError("gutter must be an integer from 0 to 80")
        if isinstance(frame_px, bool) or not isinstance(frame_px, int) or not 0 <= frame_px <= 80:
            raise PanelValidationError("frame must be an integer from 0 to 80")
        self._validate_render_targets(slots, width, height, gutter_px, frame_px)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            current = self.conn.execute(
                "SELECT revision FROM panel WHERE id = ?", (panel_id,)
            ).fetchone()
            if current is None:
                raise PanelNotFoundError(f"panel {panel_id} not found")
            if current["revision"] != expected_revision:
                raise PanelRevisionConflictError(
                    f"panel {panel_id} is revision {current['revision']}, not {expected_revision}"
                )
            retained = {
                row["candidate_id"] for row in self.conn.execute(
                    "SELECT candidate_id FROM panel_slot "
                    "WHERE panel_id = ? AND candidate_id IS NOT NULL", (panel_id,)
                )
            }
            self._validate_candidates(slots, retained)
            cursor = self.conn.execute(
                """
                UPDATE panel SET title=?, format=?, width_px=?, height_px=?,
                    background_color=?, gutter_px=?, frame_px=?,
                    revision=revision+1, updated_at=datetime('now')
                WHERE id=? AND revision=?
                """,
                (title, format, width, height, background_color, gutter_px, frame_px,
                 panel_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise PanelRevisionConflictError(f"panel {panel_id} changed during update")
            self.conn.execute("DELETE FROM panel_slot WHERE panel_id = ?", (panel_id,))
            self.conn.executemany(
                "INSERT INTO panel_slot "
                "(panel_id, candidate_id, slot_index, x0, y0, x1, y1, focal_x, focal_y, zoom) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(panel_id, slot["candidate_id"], slot["slot_index"],
                  slot["x0"], slot["y0"], slot["x1"], slot["y1"],
                  slot["focal_x"], slot["focal_y"], slot["zoom"])
                 for slot in slots],
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self.get(panel_id)

    def delete(self, panel_id: int) -> None:
        cursor = self.conn.execute("DELETE FROM panel WHERE id = ?", (panel_id,))
        if cursor.rowcount != 1:
            self.conn.rollback()
            raise PanelNotFoundError(f"panel {panel_id} not found")
        self.conn.commit()

    def list_renders(self, panel_id: int) -> list[PanelRender]:
        self.get(panel_id)
        rows = self.conn.execute(
            "SELECT * FROM panel_render WHERE panel_id = ? ORDER BY panel_revision DESC, id DESC",
            (panel_id,),
        ).fetchall()
        return [PanelRender.from_row(row) for row in rows]

    def get_render_row(self, render_id: int):
        row = self.conn.execute("SELECT * FROM panel_render WHERE id = ?", (render_id,)).fetchone()
        if row is None:
            raise PanelRenderNotFoundError(f"panel render {render_id} not found")
        return row

    @staticmethod
    def _title(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PanelValidationError("panel title is required")
        title = value.strip()
        if len(title) > 120:
            raise PanelValidationError("panel title must be 120 characters or fewer")
        return title

    @staticmethod
    def _format(value: str) -> tuple[int, int]:
        try:
            return FORMATS[value]
        except (KeyError, TypeError) as exc:
            raise PanelValidationError(f"unsupported panel format: {value}") from exc

    def _validate_layout(self, panel_slots) -> None:
        if not isinstance(panel_slots, list) or not 1 <= len(panel_slots) <= 64:
            raise PanelValidationError("a panel must have from 1 to 64 slots")
        slot_indexes: list[int] = []
        rectangles: list[tuple[float, float, float, float]] = []
        for panel_slot in panel_slots:
            try:
                slot, candidate = panel_slot["slot_index"], panel_slot["candidate_id"]
                x0, y0, x1, y1 = (panel_slot[key] for key in ("x0", "y0", "x1", "y1"))
                focal_x, focal_y, zoom = panel_slot["focal_x"], panel_slot["focal_y"], panel_slot["zoom"]
            except (KeyError, TypeError) as exc:
                raise PanelValidationError(
                    "every panel slot requires candidate, index, geometry, focal point, and zoom"
                ) from exc
            if isinstance(slot, bool) or not isinstance(slot, int):
                raise PanelValidationError("panel slot indexes must be integers")
            if candidate is not None and (
                isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 1
            ):
                raise PanelValidationError("candidate id must be null or a positive integer")
            numbers = (x0, y0, x1, y1, focal_x, focal_y, zoom)
            if any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) for value in numbers):
                raise PanelValidationError("slot geometry, focal points, and zoom must be finite numbers")
            if not all(0 <= value <= 1 for value in (x0, y0, x1, y1)):
                raise PanelValidationError("slot coordinates must be from 0 to 1")
            if x1 - x0 < 0.04 or y1 - y0 < 0.04:
                raise PanelValidationError("panel slots must be at least 0.04 wide and high")
            if not 0 <= focal_x <= 1 or not 0 <= focal_y <= 1 or not 1 <= zoom <= 3:
                raise PanelValidationError("focal points must be 0..1 and zoom must be 1..3")
            slot_indexes.append(slot)
            rectangles.append((x0, y0, x1, y1))
        if sorted(slot_indexes) != list(range(len(panel_slots))):
            raise PanelValidationError("panel slot indexes must be unique and contiguous from 0")

        for index, first in enumerate(rectangles):
            for second in rectangles[index + 1:]:
                if min(first[2], second[2]) > max(first[0], second[0]) and \
                        min(first[3], second[3]) > max(first[1], second[1]):
                    raise PanelValidationError("panel slots may not overlap")

        if not math.isclose(
            sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rectangles),
            1.0,
            rel_tol=0.0,
            abs_tol=_AREA_TOLERANCE,
        ):
            raise PanelValidationError("panel slots must exactly cover the unit rectangle")
        x_edges = sorted({
            0.0, 1.0, *(edge for rect in rectangles for edge in (rect[0], rect[2]))
        })
        y_edges = sorted({
            0.0, 1.0, *(edge for rect in rectangles for edge in (rect[1], rect[3]))
        })
        for left, right in zip(x_edges, x_edges[1:]):
            for top, bottom in zip(y_edges, y_edges[1:]):
                midpoint = ((left + right) / 2, (top + bottom) / 2)
                covered = sum(
                    x0 < midpoint[0] < x1 and y0 < midpoint[1] < y1
                    for x0, y0, x1, y1 in rectangles
                )
                if covered != 1:
                    raise PanelValidationError("panel slots must exactly cover the unit rectangle once")

    @staticmethod
    def _validate_render_targets(
        panel_slots: list[dict], width: int, height: int, gutter: int, frame: int
    ) -> None:
        content_width, content_height = width - 2 * frame, height - 2 * frame
        before, after = gutter // 2, gutter - gutter // 2
        for slot in panel_slots:
            left = round(frame + slot["x0"] * content_width)
            right = round(frame + slot["x1"] * content_width)
            top = round(frame + slot["y0"] * content_height)
            bottom = round(frame + slot["y1"] * content_height)
            if slot["x0"] > 0:
                left += after
            if slot["x1"] < 1:
                right -= before
            if slot["y0"] > 0:
                top += after
            if slot["y1"] < 1:
                bottom -= before
            if right <= left or bottom <= top:
                raise PanelValidationError(
                    f"frame and gutter leave panel slot {slot['slot_index']} without usable space"
                )

    def _validate_candidates(self, panel_slots: list[dict], retained: set[int]) -> None:
        candidate_ids = {
            slot["candidate_id"]
            for slot in panel_slots
            if slot["candidate_id"] is not None
        }
        for candidate_id in candidate_ids - retained:
            row = self.conn.execute(
                """
                SELECT c.review_status, g.state, g.scene_id
                  FROM candidate c JOIN generation g ON g.id = c.generation_id
                 WHERE c.id = ?
                """, (candidate_id,),
            ).fetchone()
            if row is None:
                raise PanelValidationError(f"candidate {candidate_id} not found")
            if row["scene_id"] is None or row["state"] != "succeeded":
                raise PanelCandidateConflictError(
                    f"candidate {candidate_id} must come from a succeeded scene generation"
                )
            if row["review_status"] != "accepted":
                raise PanelCandidateConflictError(f"candidate {candidate_id} must be accepted first")
