"""Candidate review and content-lookup service for the JSON API.

Candidate rows are read/written only through this service; route handlers
translate results into DTOs and never touch the ``candidate`` table directly.
"""

from __future__ import annotations

import sqlite3


class CandidateError(Exception):
    """Base error for the candidate service."""


class CandidateNotFoundError(CandidateError):
    """Raised when a candidate id does not exist."""


class CandidateService:
    """Candidate review and content lookup against a SQLite connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def review(self, candidate_id: int, verdict: str) -> sqlite3.Row:
        """Set a candidate's review status in one atomic statement.

        Raises CandidateNotFoundError if the id does not exist.
        """
        cursor = self.conn.execute(
            "UPDATE candidate SET review_status = ? WHERE id = ?",
            (verdict, candidate_id),
        )
        if cursor.rowcount != 1:
            self.conn.rollback()
            raise CandidateNotFoundError(f"candidate {candidate_id} not found")
        self.conn.commit()
        return self.get(candidate_id)

    def get(self, candidate_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM candidate WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise CandidateNotFoundError(f"candidate {candidate_id} not found")
        return row

    def content_sha(self, candidate_id: int) -> str:
        """Resolve a candidate id to its stored image hash.

        Raises CandidateNotFoundError if the id does not exist; the caller uses
        the hash to read bytes from the content-addressed store.
        """
        row = self.conn.execute(
            "SELECT sha256 FROM candidate WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise CandidateNotFoundError(f"candidate {candidate_id} not found")
        return row["sha256"]

    def list_accepted(self) -> list[sqlite3.Row]:
        """Every accepted candidate across all panels, newest first, joined
        with its panel (scene) so callers can render a gallery grid."""
        return self.conn.execute(
            """
            SELECT c.id               AS candidate_id,
                   c.generation_id    AS generation_id,
                   c.created_at       AS created_at,
                   s.id               AS panel_id,
                   s.beat_text        AS beat_text,
                   s.aspect_ratio     AS aspect_ratio
            FROM candidate c
            JOIN generation g ON g.id = c.generation_id
            JOIN scene s     ON s.id = g.scene_id
            WHERE c.review_status = 'accepted'
            ORDER BY c.created_at DESC, c.id DESC
            """
        ).fetchall()