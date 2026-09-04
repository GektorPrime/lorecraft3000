"""Reference-set versioning service (Milestone 5).

Workflow per character (multi-character-ready — nothing here assumes a single
character; every operation is scoped by character_id or ref_set_id):

  - create_draft(): a new DRAFT ref_set with the next version number for that
    character (version numbering unique per character, enforced by schema).
  - add_image()/remove_image()/set_image_role(): edit a DRAFT only. Canonical
    sets are immutable (schema triggers) and this service refuses to touch
    anything that is not a draft.
  - promote(): make a draft canonical in ONE transaction that also retires the
    prior canonical (canonical -> retired), preserving the schema invariant
    "exactly one canonical per character". Prior versions are kept forever.
  - copy_to_new_draft(): copy an existing set's ref_image rows into a fresh
    draft version so the user can iterate toward a new canonical.

Images are stored via the EXISTING content-addressed storage service
(app.storage.ImageStorage); ref_image rows only ever point at stored sha256
values. There is deliberately NO pathway here that reads from generation or
candidate tables — generated images are never auto-promoted into a ref set.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import NoReturn

from app.domain.models import RefImage, RefSet, RefSetSummary
from app.services.identity import (
    FACE_ROLES,
    FaceEmbedder,
    get_embedder,
    store_embedding,
)
from app.services.validation import ALLOWED_ROLES
from app.storage import ImageStorage, ImageStorageError

log = logging.getLogger(__name__)


class RefSetError(Exception):
    """Base error for the reference-set service."""


def _embed_image(
    conn: sqlite3.Connection,
    sha256: str,
    data: bytes,
    embedder: FaceEmbedder | None,
) -> None:
    """Compute and store a face embedding.  Never raises."""
    if embedder is None:
        embedder = get_embedder()
    if embedder is None:
        return
    try:
        vector = embedder.embed(data)
        if vector is not None:
            store_embedding(conn, sha256, vector)
    except Exception:
        log.warning("face embedding failed for %s — continuing without it", sha256[:12])


class RefSetNotFoundError(RefSetError):
    """Raised when a ref_set id does not exist."""


class RefImageNotFoundError(RefSetError):
    """Raised when a ref_image id does not exist."""


class RefSetNotDraftError(RefSetError):
    """Raised when an edit/promote targets a set that is not a draft."""


class InvalidRoleError(RefSetError):
    """Raised when an image role is not in the allowed set."""


class ImageRejectedError(RefSetError):
    """Raised when uploaded bytes are not a storable image."""


class RefSetService:
    """Reference-set workflow against a SQLite connection + image storage."""

    def __init__(self, conn: sqlite3.Connection, storage: ImageStorage) -> None:
        self.conn = conn
        self.storage = storage

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def get(self, ref_set_id: int) -> RefSet:
        row = self.conn.execute(
            "SELECT * FROM ref_set WHERE id = ?", (ref_set_id,)
        ).fetchone()
        if row is None:
            raise RefSetNotFoundError(f"ref_set {ref_set_id} not found")
        return RefSet(
            id=row["id"],
            character_id=row["character_id"],
            version=row["version"],
            status=row["status"],
            created_at=row["created_at"],
        )

    def list_for_character(self, character_id: int) -> list[RefSetSummary]:
        """All versions for a character, newest first, with image counts."""
        rows = self.conn.execute(
            """
            SELECT rs.*,
                   (SELECT COUNT(*) FROM ref_image ri WHERE ri.ref_set_id = rs.id)
                       AS image_count
              FROM ref_set rs
             WHERE rs.character_id = ?
             ORDER BY rs.version DESC
            """,
            (character_id,),
        ).fetchall()
        return [
            RefSetSummary(
                ref_set=RefSet(
                    id=r["id"],
                    character_id=r["character_id"],
                    version=r["version"],
                    status=r["status"],
                    created_at=r["created_at"],
                ),
                image_count=r["image_count"],
            )
            for r in rows
        ]

    def get_canonical(self, character_id: int) -> RefSet | None:
        row = self.conn.execute(
            "SELECT * FROM ref_set WHERE character_id = ? AND status = 'canonical'",
            (character_id,),
        ).fetchone()
        if row is None:
            return None
        return RefSet(
            id=row["id"],
            character_id=row["character_id"],
            version=row["version"],
            status=row["status"],
            created_at=row["created_at"],
        )

    def images(self, ref_set_id: int) -> list[RefImage]:
        rows = self.conn.execute(
            "SELECT * FROM ref_image WHERE ref_set_id = ? ORDER BY id",
            (ref_set_id,),
        ).fetchall()
        return [RefImage.from_row(r) for r in rows]

    def content_sha(self, image_id: int) -> str:
        """Resolve a ref image id to its stored content hash.

        Raises RefImageNotFoundError if the id does not exist; the caller uses
        the hash to read bytes from the content-addressed store.
        """
        row = self.conn.execute(
            "SELECT sha256 FROM ref_image WHERE id = ?", (image_id,)
        ).fetchone()
        if row is None:
            raise RefImageNotFoundError(f"ref image {image_id} not found")
        return row["sha256"]

    # ------------------------------------------------------------------
    # draft lifecycle
    # ------------------------------------------------------------------

    def create_draft(self, character_id: int) -> RefSet:
        """Create a new DRAFT with the next version number for the character."""
        version = self._next_version(character_id)
        cur = self.conn.execute(
            "INSERT INTO ref_set (character_id, version, status) VALUES (?, ?, 'draft')",
            (character_id, version),
        )
        self.conn.commit()
        return self.get(cur.lastrowid)

    def copy_to_new_draft(self, ref_set_id: int) -> RefSet:
        """Copy a set's ref_image rows into a fresh draft (next version).

        Works from any source status (draft, canonical, or retired) so the
        user can iterate toward a new canonical from the current one.
        """
        source = self.get(ref_set_id)
        new_version = self._next_version(source.character_id)
        cur = self.conn.execute(
            "INSERT INTO ref_set (character_id, version, status) VALUES (?, ?, 'draft')",
            (source.character_id, new_version),
        )
        new_id = cur.lastrowid
        for img in self.images(ref_set_id):
            self.conn.execute(
                """
                INSERT INTO ref_image
                    (ref_set_id, sha256, role, weight, embedding, quality_flags)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id,
                    img.sha256,
                    img.role,
                    img.weight,
                    img.embedding,
                    json.dumps(img.quality_flags),
                ),
            )
        self.conn.commit()
        return self.get(new_id)

    # ------------------------------------------------------------------
    # draft editing (images)
    # ------------------------------------------------------------------

    def add_image(
        self,
        ref_set_id: int,
        data: bytes,
        role: str,
        *,
        source_name: str | None = None,
        embedder: FaceEmbedder | None = None,
    ) -> RefImage:
        """Store image bytes via content-addressed storage and attach to a draft.

        Raises RefSetNotDraftError if the set is not a draft, InvalidRoleError
        for roles outside the allowed set, ImageRejectedError if the bytes are
        not a storable image.

        For face-role images, an optional FaceEmbedder is used to compute a
        512-d ArcFace vector.  The embedding is stored in the face_embedding
        table keyed by content hash.  If the embedder is not provided, the
        singleton is fetched via get_embedder().  Embedding failures never
        prevent the image from being stored.
        """
        self._require_draft(ref_set_id)
        self._validate_role(role)
        try:
            meta = self.storage.store(
                data,
                source_name=source_name,
                allowed_formats={"PNG", "JPEG", "WEBP"},
            )
        except ImageStorageError as exc:
            raise ImageRejectedError(f"image rejected: {exc}") from exc
        try:
            cur = self.conn.execute(
                """
                INSERT INTO ref_image (ref_set_id, sha256, role, weight, quality_flags)
                VALUES (?, ?, ?, 1.0, '[]')
                """,
                (ref_set_id, meta.sha256, role),
            )
        except sqlite3.IntegrityError as exc:
            self._raise_image_immutability_error(ref_set_id, exc)
        # Embed face-role images eagerly so the vector is available the moment
        # the image is uploaded (not deferred to promote).  Failures are logged
        # and swallowed — the image is still usable without an embedding.
        if role in FACE_ROLES:
            _embed_image(self.conn, meta.sha256, data, embedder)
        self.conn.commit()
        return self._get_image(cur.lastrowid)

    def remove_image(self, ref_set_id: int, image_id: int) -> None:
        """Remove an image from a draft. Canonical sets are untouchable."""
        self._require_draft(ref_set_id)
        self._get_image_in_set(ref_set_id, image_id)
        try:
            self.conn.execute(
                "DELETE FROM ref_image WHERE id = ? AND ref_set_id = ?",
                (image_id, ref_set_id),
            )
        except sqlite3.IntegrityError as exc:
            self._raise_image_immutability_error(ref_set_id, exc)
        self.conn.commit()

    def set_image_role(self, ref_set_id: int, image_id: int, role: str) -> RefImage:
        """Re-role an image inside a draft. Canonical sets are untouchable."""
        self._require_draft(ref_set_id)
        self._validate_role(role)
        self._get_image_in_set(ref_set_id, image_id)
        try:
            self.conn.execute(
                "UPDATE ref_image SET role = ? WHERE id = ? AND ref_set_id = ?",
                (role, image_id, ref_set_id),
            )
        except sqlite3.IntegrityError as exc:
            self._raise_image_immutability_error(ref_set_id, exc)
        self.conn.commit()
        return self._get_image_in_set(ref_set_id, image_id)

    # ------------------------------------------------------------------
    # promotion
    # ------------------------------------------------------------------

    def promote(self, ref_set_id: int) -> RefSet:
        """Promote a draft to canonical in ONE transaction.

        The same transaction retires the prior canonical (canonical -> retired,
        the only transition the schema allows on a canonical row), so the
        "exactly one canonical per character" invariant holds at every commit
        point. Prior versions are kept forever (retired, never deleted).

        The transaction boundary is an explicit SAVEPOINT rather than BEGIN:
        a savepoint nests inside any transaction the caller may already have
        open (no "cannot start a transaction within a transaction" failure),
        and ROLLBACK TO the savepoint undoes both UPDATEs together, so a
        failure at either step leaves the prior canonical canonical and the
        draft a draft.
        """
        draft = self.get(ref_set_id)
        if draft.status != "draft":
            raise RefSetNotDraftError(
                f"ref_set {ref_set_id} is '{draft.status}'; only drafts can be promoted"
            )
        conn = self.conn
        savepoint_created = False
        try:
            conn.execute("SAVEPOINT promote_ref_set")
            savepoint_created = True
            image = conn.execute(
                "SELECT 1 FROM ref_image WHERE ref_set_id = ? LIMIT 1",
                (ref_set_id,),
            ).fetchone()
            if image is None:
                raise RefSetError("a reference set needs at least one image before promotion")
            conn.execute(
                "UPDATE ref_set SET status = 'retired' "
                "WHERE character_id = ? AND status = 'canonical'",
                (draft.character_id,),
            )
            conn.execute(
                "UPDATE ref_set SET status = 'canonical' WHERE id = ?",
                (ref_set_id,),
            )
            conn.execute("RELEASE SAVEPOINT promote_ref_set")
            savepoint_created = False
        except RefSetError:
            if savepoint_created:
                conn.execute("ROLLBACK TO SAVEPOINT promote_ref_set")
                conn.execute("RELEASE SAVEPOINT promote_ref_set")
            raise
        except sqlite3.Error as exc:
            if savepoint_created:
                conn.execute("ROLLBACK TO SAVEPOINT promote_ref_set")
                conn.execute("RELEASE SAVEPOINT promote_ref_set")
            raise RefSetError(f"promotion failed: {exc}") from exc
        return self.get(ref_set_id)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _next_version(self, character_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS max_version "
            "FROM ref_set WHERE character_id = ?",
            (character_id,),
        ).fetchone()
        return int(row["max_version"]) + 1

    def _require_draft(self, ref_set_id: int) -> None:
        rs = self.get(ref_set_id)
        if rs.status != "draft":
            raise RefSetNotDraftError(
                f"ref_set {ref_set_id} is '{rs.status}'; edits are only allowed "
                "while the set is a draft"
            )

    def _raise_image_immutability_error(
        self, ref_set_id: int, exc: sqlite3.IntegrityError
    ) -> NoReturn:
        message = str(exc)
        if "draft ref_sets" in message or "ref_sets are immutable" in message:
            self.conn.rollback()
            raise RefSetNotDraftError(
                f"ref_set {ref_set_id} became immutable while the image was edited"
            ) from exc
        raise exc

    @staticmethod
    def _validate_role(role: str) -> None:
        if role not in ALLOWED_ROLES:
            allowed = ", ".join(ALLOWED_ROLES)
            raise InvalidRoleError(
                f"invalid role '{role}' — allowed roles: {allowed}"
            )

    def _get_image(self, image_id: int) -> RefImage:
        row = self.conn.execute(
            "SELECT * FROM ref_image WHERE id = ?", (image_id,)
        ).fetchone()
        if row is None:
            raise RefSetError(f"ref_image {image_id} not found")
        return RefImage.from_row(row)

    def _get_image_in_set(self, ref_set_id: int, image_id: int) -> RefImage:
        row = self.conn.execute(
            "SELECT * FROM ref_image WHERE id = ? AND ref_set_id = ?",
            (image_id, ref_set_id),
        ).fetchone()
        if row is None:
            raise RefSetError(
                f"ref_image {image_id} does not belong to ref_set {ref_set_id}"
            )
        return RefImage.from_row(row)
