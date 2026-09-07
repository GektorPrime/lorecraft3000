"""Soft-delete (archive) support for characters and styles.

Characters and styles are archived, not hard-deleted, so scenes that already
reference them keep working (an archived character stays in a scene's cast;
an archived style stays on existing scenes). Archived rows are hidden from
lists/pickers and can
no longer be reused for NEW scenes, but their dependencies are never broken.

Freeing the name/slug on archive
--------------------------------
``character.slug`` and ``style.name`` carry column-level UNIQUE constraints
(001_initial). Both tables are referenced by foreign keys — ``character`` by
``ref_set``/``scene`` (via cast) and ``style`` by ``character.default_style_id``
and ``scene.style_id`` — so a table rebuild to relax the UNIQUE constraint into
a partial index would require dropping and recreating those child FKs, which is
far more invasive than the problem warrants.

Instead the service renames the unique column on archive to a sentinel value
(``__archived_{id}__{original}``) and preserves the human-facing original in a
new column (``display_name`` / ``display_slug``). That frees the original
name/slug for a new active record immediately, keeps the row (and its FK
targets) intact, and lets restore put the original back after checking that no
active record has since taken the name/slug.

This migration only adds the columns; all archive/restore logic lives in the
services so it stays testable and transactional per-operation.
"""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    # The runner owns the transaction (see 001_initial.upgrade): every statement
    # here plus the schema_migrations insert commit together, so a failure rolls
    # back the whole migration and it can be re-run cleanly.
    statements = (
        # NULL archived_at == active. Archived rows carry the archive timestamp.
        "ALTER TABLE character ADD COLUMN archived_at TEXT",
        "ALTER TABLE style ADD COLUMN archived_at TEXT",
        # Human-facing originals, preserved when the unique column is renamed to
        # its archived sentinel so the UI can still show the real name/slug and
        # restore can put it back.
        "ALTER TABLE character ADD COLUMN display_slug TEXT",
        "ALTER TABLE style ADD COLUMN display_name TEXT",
    )
    for statement in statements:
        conn.execute(statement)
