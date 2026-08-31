"""Style bible service: CRUD plus the seeded Victorian default style.

The default style is seeded by migration 002_default_style (idempotent: the
migration runner applies it exactly once per database). The constants below
are the single source of truth for the seed values.
"""

from __future__ import annotations

import json
import sqlite3

from app.domain.models import Style


class StyleError(Exception):
    """Base error for the style service."""


class StyleNameCollisionError(StyleError):
    """Raised when a style name is already taken."""


class StyleNotFoundError(StyleError):
    """Raised when a style id does not exist."""


# The project's decided art style (documentation/agents.md, Open decision 1).
DEFAULT_STYLE_NAME = "Victorian Oil Painting"
DEFAULT_STYLE_CONTRACT = (
    "Victorian-era oil painting. Rich, warm chiaroscuro lighting; visible "
    "brushwork; deep shadows and candlelit highlights; muted earth tones with "
    "jewel accents; painterly romantic realism in the manner of 19th-century "
    "academic portraiture. No modern photographic artifacts, no digital "
    "gradients, no flat cel shading."
)


class StyleService:
    """CRUD for styles against a SQLite connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def list(self) -> list[Style]:
        rows = self.conn.execute(
            "SELECT * FROM style ORDER BY name COLLATE NOCASE, id"
        ).fetchall()
        return [Style.from_row(r) for r in rows]

    def get(self, style_id: int) -> Style:
        row = self.conn.execute(
            "SELECT * FROM style WHERE id = ?", (style_id,)
        ).fetchone()
        if row is None:
            raise StyleNotFoundError(f"style {style_id} not found")
        return Style.from_row(row)

    def get_default(self) -> Style:
        """The seeded Victorian oil-painting default style."""
        row = self.conn.execute(
            "SELECT * FROM style WHERE name = ?", (DEFAULT_STYLE_NAME,)
        ).fetchone()
        if row is None:
            raise StyleNotFoundError(
                f"default style '{DEFAULT_STYLE_NAME}' is missing — "
                "run migrations (002_default_style seeds it)"
            )
        return Style.from_row(row)

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        name: str,
        style_contract: str = "",
        ref_image_ids: list[int] | None = None,
    ) -> Style:
        """Create a style. Raises StyleNameCollisionError on duplicate name."""
        if not name.strip():
            raise StyleError("style name is required")
        try:
            cur = self.conn.execute(
                "INSERT INTO style (name, style_contract, ref_image_ids) VALUES (?, ?, ?)",
                (name.strip(), style_contract, json.dumps(ref_image_ids or [])),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            raise StyleNameCollisionError(
                f"style name '{name}' is already taken — choose a different name"
            ) from exc
        return self.get(cur.lastrowid)

    def update(
        self,
        style_id: int,
        *,
        name: str,
        style_contract: str = "",
        ref_image_ids: list[int] | None = None,
    ) -> Style:
        """Update a style. Raises StyleNameCollisionError on duplicate name."""
        self.get(style_id)  # raises StyleNotFoundError if missing
        if not name.strip():
            raise StyleError("style name is required")
        try:
            self.conn.execute(
                """
                UPDATE style
                   SET name = ?, style_contract = ?, ref_image_ids = ?
                 WHERE id = ?
                """,
                (name.strip(), style_contract, json.dumps(ref_image_ids or []), style_id),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            raise StyleNameCollisionError(
                f"style name '{name}' is already taken — choose a different name"
            ) from exc
        return self.get(style_id)