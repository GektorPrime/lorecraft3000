"""Style bible service: CRUD plus the seeded Victorian default style.

The default style is seeded by migration 002_default_style (idempotent: the
migration runner applies it exactly once per database). The constants below
are the single source of truth for the seed values.
"""

from __future__ import annotations

import sqlite3

from app.domain.models import Style


class StyleError(Exception):
    """Base error for the style service."""


class StyleNameCollisionError(StyleError):
    """Raised when a style name is already taken."""


class StyleNotFoundError(StyleError):
    """Raised when a style id does not exist."""


class StyleArchivedError(StyleError):
    """Raised when an operation is invalid for the seeded default style.

    The default style is the app's baseline and is never archivable — archiving
    it would leave characters/scenes that rely on the default without one.
    """


def _archived_sentinel(style_id: int, name: str) -> str:
    """The value stored in the UNIQUE ``name`` column while archived.

    Renaming the unique column frees the human-facing name for a new active
    style immediately. The original is preserved in ``display_name`` and
    restored by :meth:`StyleService.restore`.
    """
    return f"__archived_{style_id}__{name}"


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
        """Active (non-archived) styles only — this backs every list/picker."""
        rows = self.conn.execute(
            "SELECT * FROM style WHERE archived_at IS NULL "
            "ORDER BY name COLLATE NOCASE, id"
        ).fetchall()
        return [Style.from_row(r) for r in rows]

    def list_archived(self) -> list[Style]:
        rows = self.conn.execute(
            "SELECT * FROM style WHERE archived_at IS NOT NULL "
            "ORDER BY display_name COLLATE NOCASE, name COLLATE NOCASE, id"
        ).fetchall()
        return [Style.from_row(r) for r in rows]

    def get(self, style_id: int) -> Style:
        """Resolve any style, archived or not.

        Archived styles must still resolve so scenes that already reference them
        keep rendering and previewing — archiving hides a style from new work,
        it does not break existing dependencies.
        """
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
    ) -> Style:
        """Create a style. Raises StyleNameCollisionError on duplicate name."""
        if not name.strip():
            raise StyleError("style name is required")
        try:
            cur = self.conn.execute(
                "INSERT INTO style (name, style_contract) VALUES (?, ?)",
                (name.strip(), style_contract),
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
    ) -> Style:
        """Update a style. Raises StyleNameCollisionError on duplicate name."""
        self.get(style_id)  # raises StyleNotFoundError if missing
        if not name.strip():
            raise StyleError("style name is required")
        try:
            self.conn.execute(
                """
                UPDATE style
                   SET name = ?, style_contract = ?
                 WHERE id = ?
                """,
                (name.strip(), style_contract, style_id),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            raise StyleNameCollisionError(
                f"style name '{name}' is already taken — choose a different name"
            ) from exc
        return self.get(style_id)

    # ------------------------------------------------------------------
    # archive / restore (soft delete)
    # ------------------------------------------------------------------

    def archive(self, style_id: int) -> Style:
        """Archive a style: hide it from lists while keeping dependencies intact.

        The seeded default style cannot be archived. Archiving frees the style's
        name for reuse by renaming the unique ``name`` column to an archived
        sentinel and preserving the original in ``display_name``. Idempotent: an
        already-archived style is returned unchanged.
        """
        style = self.get(style_id)
        if style.archived_at is not None:
            return style
        if style.name == DEFAULT_STYLE_NAME:
            raise StyleArchivedError(
                f"the default style '{DEFAULT_STYLE_NAME}' cannot be archived"
            )
        self.conn.execute(
            """
            UPDATE style
               SET display_name = name,
                   name = ?,
                   archived_at = datetime('now')
             WHERE id = ?
            """,
            (_archived_sentinel(style_id, style.name), style_id),
        )
        self.conn.commit()
        return self.get(style_id)

    def restore(self, style_id: int) -> Style:
        """Restore an archived style, reclaiming its original name.

        Fails loudly if another active style has taken the name in the meantime;
        the caller must rename one of them first.
        """
        row = self.conn.execute(
            "SELECT * FROM style WHERE id = ?", (style_id,)
        ).fetchone()
        if row is None:
            raise StyleNotFoundError(f"style {style_id} not found")
        if row["archived_at"] is None:
            return Style.from_row(row)
        original = row["display_name"] or row["name"]
        clash = self.conn.execute(
            "SELECT 1 FROM style WHERE name = ? AND archived_at IS NULL",
            (original,),
        ).fetchone()
        if clash is not None:
            raise StyleNameCollisionError(
                f"style name '{original}' is already taken by an active style — "
                "rename it before restoring this one"
            )
        try:
            self.conn.execute(
                """
                UPDATE style
                   SET name = ?,
                       display_name = NULL,
                       archived_at = NULL
                 WHERE id = ?
                """,
                (original, style_id),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            raise StyleNameCollisionError(
                f"style name '{original}' is already taken — choose a different name"
            ) from exc
        return self.get(style_id)
