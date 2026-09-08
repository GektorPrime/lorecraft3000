"""Persistence and strict validation for comic-page aggregates."""

from __future__ import annotations

import json
import re
import sqlite3

from app.domain.comic_pages import ComicPage, ComicPagePanel, PageRender

FORMATS = {
    "portrait": (1200, 1800),
    "square": (1600, 1600),
    "landscape": (1800, 1200),
}
TEMPLATES = {
    "full": (1, ()),
    "two_rows": (2, (0.5,)),
    "two_columns": (2, (0.5,)),
    "feature_top": (3, (0.55, 0.5)),
    "feature_bottom": (3, (0.45, 0.5)),
    "three_rows": (3, (1 / 3, 2 / 3)),
    "four_grid": (4, (0.5, 0.5)),
    "feature_left": (3, (0.55, 0.5)),
    "six_grid": (6, (1 / 3, 2 / 3, 0.5)),
}
_COLOR = re.compile(r"^#[0-9A-F]{6}$")


class PageError(Exception):
    pass


class PageNotFoundError(PageError):
    pass


class PageValidationError(PageError):
    pass


class PageRevisionConflictError(PageError):
    pass


class PageCandidateConflictError(PageError):
    pass


class PageIncompleteError(PageError):
    pass


class PageRenderNotFoundError(PageError):
    pass


def template_rectangles(key: str, dividers: list[float]) -> list[tuple[float, float, float, float]]:
    if key == "full":
        return [(0, 0, 1, 1)]
    if key == "two_rows":
        y = dividers[0]
        return [(0, 0, 1, y), (0, y, 1, 1)]
    if key == "two_columns":
        x = dividers[0]
        return [(0, 0, x, 1), (x, 0, 1, 1)]
    if key == "feature_top":
        y, x = dividers
        return [(0, 0, 1, y), (0, y, x, 1), (x, y, 1, 1)]
    if key == "feature_bottom":
        y, x = dividers
        return [(0, 0, x, y), (x, 0, 1, y), (0, y, 1, 1)]
    if key == "three_rows":
        y1, y2 = dividers
        return [(0, 0, 1, y1), (0, y1, 1, y2), (0, y2, 1, 1)]
    if key == "four_grid":
        x, y = dividers
        return [(0, 0, x, y), (x, 0, 1, y), (0, y, x, 1), (x, y, 1, 1)]
    if key == "feature_left":
        x, y = dividers
        return [(0, 0, x, 1), (x, 0, 1, y), (x, y, 1, 1)]
    x1, x2, y = dividers
    return [
        (0, 0, x1, y), (x1, 0, x2, y), (x2, 0, 1, y),
        (0, y, x1, 1), (x1, y, x2, 1), (x2, y, 1, 1),
    ]


class PageService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list(self) -> list[ComicPage]:
        rows = self.conn.execute("SELECT id FROM comic_page ORDER BY updated_at DESC, id DESC").fetchall()
        return [self.get(row["id"]) for row in rows]

    def get(self, page_id: int) -> ComicPage:
        row = self.conn.execute("SELECT * FROM comic_page WHERE id = ?", (page_id,)).fetchone()
        if row is None:
            raise PageNotFoundError(f"page {page_id} not found")
        panels = self.conn.execute(
            "SELECT * FROM comic_page_panel WHERE page_id = ? ORDER BY slot_index", (page_id,)
        ).fetchall()
        render = self.conn.execute(
            "SELECT * FROM page_render WHERE page_id = ? ORDER BY page_revision DESC, id DESC LIMIT 1",
            (page_id,),
        ).fetchone()
        return ComicPage(
            id=row["id"], title=row["title"], format=row["format"],
            width_px=row["width_px"], height_px=row["height_px"],
            background_color=row["background_color"], gutter_px=row["gutter_px"],
            template_key=row["template_key"], template_version=row["template_version"],
            divider_values=json.loads(row["divider_values_json"]), revision=row["revision"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            panels=tuple(ComicPagePanel.from_row(panel) for panel in panels),
            latest_render=PageRender.from_row(render) if render else None,
        )

    def create(
        self,
        *,
        title: str,
        format: str,
        template_key: str,
        candidate_id: int | None = None,
    ) -> ComicPage:
        title = self._title(title)
        width, height = self._format(format)
        _, defaults = self._template(template_key)
        panels = [] if candidate_id is None else [{"candidate_id": candidate_id}]
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._validate_candidates(panels, set())
            cursor = self.conn.execute(
                "INSERT INTO comic_page (title, format, width_px, height_px, template_key, divider_values_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (title, format, width, height, template_key, json.dumps(defaults)),
            )
            if candidate_id is not None:
                self.conn.execute(
                    "INSERT INTO comic_page_panel (page_id, candidate_id, slot_index) VALUES (?, ?, 0)",
                    (cursor.lastrowid, candidate_id),
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self.get(int(cursor.lastrowid))

    def update(
        self, page_id: int, *, expected_revision: int, title: str, format: str,
        background_color: str, gutter_px: int, template_key: str,
        template_version: int, divider_values: list[float], panels: list[dict],
    ) -> ComicPage:
        title = self._title(title)
        width, height = self._format(format)
        self._validate_layout(template_key, template_version, divider_values, panels)
        if not _COLOR.fullmatch(background_color):
            raise PageValidationError("background color must be uppercase #RRGGBB")
        if isinstance(gutter_px, bool) or not isinstance(gutter_px, int) or not 0 <= gutter_px <= 80:
            raise PageValidationError("gutter must be an integer from 0 to 80")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            current = self.conn.execute(
                "SELECT revision FROM comic_page WHERE id = ?", (page_id,)
            ).fetchone()
            if current is None:
                raise PageNotFoundError(f"page {page_id} not found")
            if current["revision"] != expected_revision:
                raise PageRevisionConflictError(
                    f"page {page_id} is revision {current['revision']}, not {expected_revision}"
                )
            retained = {
                row["candidate_id"] for row in self.conn.execute(
                    "SELECT candidate_id FROM comic_page_panel WHERE page_id = ?", (page_id,)
                )
            }
            self._validate_candidates(panels, retained)
            cursor = self.conn.execute(
                """
                UPDATE comic_page SET title=?, format=?, width_px=?, height_px=?,
                    background_color=?, gutter_px=?, template_key=?, template_version=?,
                    divider_values_json=?, revision=revision+1, updated_at=datetime('now')
                WHERE id=? AND revision=?
                """,
                (title, format, width, height, background_color, gutter_px, template_key,
                 template_version, json.dumps(divider_values), page_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise PageRevisionConflictError(f"page {page_id} changed during update")
            self.conn.execute("DELETE FROM comic_page_panel WHERE page_id = ?", (page_id,))
            self.conn.executemany(
                "INSERT INTO comic_page_panel "
                "(page_id, candidate_id, slot_index, focal_x, focal_y, zoom) VALUES (?, ?, ?, ?, ?, ?)",
                [(page_id, p["candidate_id"], p["slot_index"], p["focal_x"], p["focal_y"], p["zoom"])
                 for p in panels],
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self.get(page_id)

    def delete(self, page_id: int) -> None:
        cursor = self.conn.execute("DELETE FROM comic_page WHERE id = ?", (page_id,))
        if cursor.rowcount != 1:
            self.conn.rollback()
            raise PageNotFoundError(f"page {page_id} not found")
        self.conn.commit()

    def list_renders(self, page_id: int) -> list[PageRender]:
        self.get(page_id)
        rows = self.conn.execute(
            "SELECT * FROM page_render WHERE page_id = ? ORDER BY page_revision DESC, id DESC",
            (page_id,),
        ).fetchall()
        return [PageRender.from_row(row) for row in rows]

    def get_render_row(self, render_id: int):
        row = self.conn.execute("SELECT * FROM page_render WHERE id = ?", (render_id,)).fetchone()
        if row is None:
            raise PageRenderNotFoundError(f"page render {render_id} not found")
        return row

    @staticmethod
    def _title(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PageValidationError("page title is required")
        title = value.strip()
        if len(title) > 120:
            raise PageValidationError("page title must be 120 characters or fewer")
        return title

    @staticmethod
    def _format(value: str) -> tuple[int, int]:
        try:
            return FORMATS[value]
        except (KeyError, TypeError) as exc:
            raise PageValidationError(f"unsupported page format: {value}") from exc

    @staticmethod
    def _template(value: str) -> tuple[int, tuple[float, ...]]:
        try:
            return TEMPLATES[value]
        except (KeyError, TypeError) as exc:
            raise PageValidationError(f"unsupported page template: {value}") from exc

    def _validate_layout(self, key, version, dividers, panels) -> None:
        slots, defaults = self._template(key)
        if version != 1:
            raise PageValidationError("unsupported template version")
        if not isinstance(dividers, list) or len(dividers) != len(defaults):
            raise PageValidationError(f"template {key} requires {len(defaults)} divider values")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.2 <= v <= 0.8 for v in dividers):
            raise PageValidationError("divider values must be numbers from 0.2 to 0.8")
        if key in {"three_rows", "six_grid"} and dividers[1] - dividers[0] < 0.099999:
            raise PageValidationError("thirds dividers must be at least 10% apart")
        if not isinstance(panels, list) or len(panels) > slots:
            raise PageValidationError(f"template {key} has {slots} slots")
        slot_indexes, candidate_ids = [], []
        for panel in panels:
            try:
                slot, candidate = panel["slot_index"], panel["candidate_id"]
                focal_x, focal_y, zoom = panel["focal_x"], panel["focal_y"], panel["zoom"]
            except (KeyError, TypeError) as exc:
                raise PageValidationError("every panel requires candidate, slot, focal point, and zoom") from exc
            if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < slots:
                raise PageValidationError(f"panel slot must be from 0 to {slots - 1}")
            if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 1:
                raise PageValidationError("candidate id must be a positive integer")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (focal_x, focal_y, zoom)):
                raise PageValidationError("focal points and zoom must be numbers")
            if not 0 <= focal_x <= 1 or not 0 <= focal_y <= 1 or not 1 <= zoom <= 3:
                raise PageValidationError("focal points must be 0..1 and zoom must be 1..3")
            slot_indexes.append(slot)
            candidate_ids.append(candidate)
        if len(slot_indexes) != len(set(slot_indexes)):
            raise PageValidationError("a slot may be used only once")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise PageValidationError("a candidate may appear only once on a page")

    def _validate_candidates(self, panels: list[dict], retained: set[int]) -> None:
        for candidate_id in {panel["candidate_id"] for panel in panels} - retained:
            row = self.conn.execute(
                """
                SELECT c.review_status, g.state, g.scene_id
                  FROM candidate c JOIN generation g ON g.id = c.generation_id
                 WHERE c.id = ?
                """, (candidate_id,),
            ).fetchone()
            if row is None:
                raise PageValidationError(f"candidate {candidate_id} not found")
            if row["scene_id"] is None or row["state"] != "succeeded":
                raise PageCandidateConflictError(
                    f"candidate {candidate_id} must come from a succeeded scene generation"
                )
            if row["review_status"] != "accepted":
                raise PageCandidateConflictError(f"candidate {candidate_id} must be accepted first")
