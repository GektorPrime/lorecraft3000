"""Candidate identity-score column (Phase: identity scoring).

Stores per-detected-face scores for the panel's cast as JSON:
    {"cast": {"<character_id>": <best similarity>}, "faces_detected": <n>}

The column is advisory-only — nothing in the review/generation flow reads it
as a gate, and the scoring step that writes it must never fail a generation.
"""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        "ALTER TABLE candidate "
        "ADD COLUMN identity_scores TEXT NOT NULL DEFAULT '{}'"
    )