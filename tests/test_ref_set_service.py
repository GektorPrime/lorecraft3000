"""Tests for the reference-set versioning service (Milestone 5).

Proves: per-character version numbering, image upload + role assignment through
the REAL content-addressed storage service, draft-only editing, single-
transaction promotion that retires the prior canonical with exactly-one-
canonical preserved, and new-draft-from-existing copying images.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.services.characters import CharacterService
from app.services.ref_sets import (
    ImageRejectedError,
    InvalidRoleError,
    RefSetError,
    RefSetNotDraftError,
    RefSetService,
)
from app.services.validation import ALLOWED_ROLES
from tests.conftest import make_png_bytes


def _character(conn, name="Elias", slug="elias") -> int:
    return CharacterService(conn).create(name=name, slug=slug).id


def _service(conn, storage) -> RefSetService:
    return RefSetService(conn, storage)


def _status(conn, ref_set_id: int) -> str:
    row = conn.execute("SELECT status FROM ref_set WHERE id = ?", (ref_set_id,)).fetchone()
    return row["status"]


def _canonical_count(conn, character_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM ref_set WHERE character_id = ? AND status = 'canonical'",
        (character_id,),
    ).fetchone()
    return row["n"]


# ---------------------------------------------------------------------------
# draft creation + per-character version numbering
# ---------------------------------------------------------------------------

def test_create_draft_versions_unique_per_character(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    v1 = service.create_draft(cid)
    v2 = service.create_draft(cid)
    assert v1.version == 1
    assert v2.version == 2
    assert v1.status == "draft"
    assert v2.status == "draft"


def test_version_numbering_is_per_character(conn, storage):
    """Two characters each get their own v1 — nothing is global."""
    service = _service(conn, storage)
    a = _character(conn, name="Elias", slug="elias")
    b = _character(conn, name="Margaret", slug="margaret")
    assert service.create_draft(a).version == 1
    assert service.create_draft(b).version == 1
    assert service.create_draft(a).version == 2


def test_create_draft_after_promotion_continues_numbering(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    d1 = service.create_draft(cid)
    service.promote(d1.id)
    d2 = service.create_draft(cid)
    assert d2.version == 2


# ---------------------------------------------------------------------------
# image upload + role assignment (real content-addressed storage)
# ---------------------------------------------------------------------------

def test_add_image_stores_bytes_via_content_addressed_storage(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    draft = service.create_draft(cid)
    png = make_png_bytes((10, 20, 30))

    img = service.add_image(draft.id, png, "face_front", source_name="ref.png")

    # The ref_image row points at the sha256 the storage service computed.
    meta = storage.store(png)  # same bytes -> same sha256 (dedupe proves it)
    assert img.sha256 == meta.sha256
    assert img.role == "face_front"
    assert img.weight == 1.0

    # The bytes live on disk under store/<sha256[:2]>/<sha256>.png — never in the DB.
    stored_path = storage.root / meta.sha256[:2] / f"{meta.sha256}.png"
    assert stored_path.exists()
    assert stored_path.read_bytes() == png


def test_add_image_accepts_all_allowed_roles(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    draft = service.create_draft(cid)
    for role in ALLOWED_ROLES:
        img = service.add_image(draft.id, make_png_bytes(), role)
        assert img.role == role
    assert len(service.images(draft.id)) == len(ALLOWED_ROLES)


def test_add_image_rejects_invalid_role(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    draft = service.create_draft(cid)
    with pytest.raises(InvalidRoleError) as excinfo:
        service.add_image(draft.id, make_png_bytes(), "bogus_role")
    assert "bogus_role" in str(excinfo.value)
    assert service.images(draft.id) == []


def test_add_image_rejects_non_image_bytes(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    draft = service.create_draft(cid)
    with pytest.raises(ImageRejectedError):
        service.add_image(draft.id, b"this is not an image", "face_front")
    assert service.images(draft.id) == []


def test_every_ref_image_sha256_exists_on_disk(conn, storage):
    """Ref images only ever point at content-addressed files — no DB bytes,
    and no pathway that fabricates pointers to non-stored images."""
    service = _service(conn, storage)
    cid = _character(conn)
    draft = service.create_draft(cid)
    for color in ((10, 20, 30), (30, 20, 10), (20, 30, 10)):
        service.add_image(draft.id, make_png_bytes(color), "face_front")

    rows = conn.execute("SELECT sha256 FROM ref_image").fetchall()
    assert len(rows) == 3
    for row in rows:
        matches = list(storage.root.rglob(f"{row['sha256']}.*"))
        assert matches, f"no stored file for ref_image sha256 {row['sha256']}"
        assert any(p.suffix in (".png", ".jpg", ".webp") for p in matches)


# ---------------------------------------------------------------------------
# draft editing (add/remove/re-role) — drafts only
# ---------------------------------------------------------------------------

def test_remove_image_from_draft(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    draft = service.create_draft(cid)
    a = service.add_image(draft.id, make_png_bytes((10, 20, 30)), "face_front")
    b = service.add_image(draft.id, make_png_bytes((30, 20, 10)), "full_body")

    service.remove_image(draft.id, a.id)
    remaining = service.images(draft.id)
    assert [i.id for i in remaining] == [b.id]


def test_set_image_role_on_draft(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    draft = service.create_draft(cid)
    img = service.add_image(draft.id, make_png_bytes(), "face_front")

    updated = service.set_image_role(draft.id, img.id, "outfit")
    assert updated.role == "outfit"
    assert service.images(draft.id)[0].role == "outfit"


def test_set_image_role_rejects_invalid_role(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    draft = service.create_draft(cid)
    img = service.add_image(draft.id, make_png_bytes(), "face_front")
    with pytest.raises(InvalidRoleError):
        service.set_image_role(draft.id, img.id, "nope")
    assert service.images(draft.id)[0].role == "face_front"


def test_edit_blocked_on_canonical(conn, storage):
    """After promotion the set is immutable: add/remove/re-role all raise."""
    service = _service(conn, storage)
    cid = _character(conn)
    draft = service.create_draft(cid)
    img = service.add_image(draft.id, make_png_bytes(), "face_front")
    service.promote(draft.id)

    with pytest.raises(RefSetNotDraftError):
        service.add_image(draft.id, make_png_bytes(), "full_body")
    with pytest.raises(RefSetNotDraftError):
        service.remove_image(draft.id, img.id)
    with pytest.raises(RefSetNotDraftError):
        service.set_image_role(draft.id, img.id, "outfit")
    # Nothing changed.
    assert len(service.images(draft.id)) == 1
    assert service.images(draft.id)[0].role == "face_front"


def test_edit_blocked_on_retired(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    v1 = service.create_draft(cid)
    service.add_image(v1.id, make_png_bytes(), "face_front")
    service.promote(v1.id)
    v2 = service.create_draft(cid)
    service.promote(v2.id)  # v1 is now retired

    with pytest.raises(RefSetNotDraftError):
        service.add_image(v1.id, make_png_bytes(), "full_body")


# ---------------------------------------------------------------------------
# promotion: single transaction, retires prior canonical, exactly one canonical
# ---------------------------------------------------------------------------

def test_promote_first_draft_becomes_canonical(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    draft = service.create_draft(cid)
    service.add_image(draft.id, make_png_bytes(), "face_front")

    promoted = service.promote(draft.id)
    assert promoted.status == "canonical"
    assert service.get_canonical(cid).id == draft.id
    assert _canonical_count(conn, cid) == 1


def test_promote_retires_prior_canonical_and_keeps_exactly_one(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    v1 = service.create_draft(cid)
    service.add_image(v1.id, make_png_bytes((10, 20, 30)), "face_front")
    service.promote(v1.id)

    v2 = service.create_draft(cid)
    service.add_image(v2.id, make_png_bytes((30, 20, 10)), "full_body")
    service.promote(v2.id)

    assert _status(conn, v1.id) == "retired"  # kept forever, not deleted
    assert _status(conn, v2.id) == "canonical"
    assert _canonical_count(conn, cid) == 1
    assert service.get_canonical(cid).id == v2.id
    # Prior versions are still listed (history preserved).
    versions = {s.ref_set.id: s.ref_set.status for s in service.list_for_character(cid)}
    assert versions == {v1.id: "retired", v2.id: "canonical"}


def test_promote_non_draft_rejected(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    draft = service.create_draft(cid)
    service.promote(draft.id)
    with pytest.raises(RefSetNotDraftError):
        service.promote(draft.id)  # already canonical


def test_promote_missing_ref_set_raises(conn, storage):
    with pytest.raises(RefSetError):
        _service(conn, storage).promote(99999)


class _FlakyConn:
    """Connection wrapper that fails the Nth matching statement.

    Used to prove promotion is atomic: if the second UPDATE of the promotion
    fails, the first (retiring the prior canonical) must be rolled back.
    """

    def __init__(self, real, fail_prefix: str) -> None:
        self._real = real
        self._fail_prefix = fail_prefix

    def __getattr__(self, name):
        return getattr(self._real, name)

    def execute(self, sql, *args, **kwargs):
        if sql.startswith(self._fail_prefix):
            raise sqlite3.IntegrityError("simulated mid-promotion failure")
        return self._real.execute(sql, *args, **kwargs)


def test_promotion_is_atomic_on_failure(conn, storage):
    """A failure mid-promotion leaves the prior canonical intact."""
    service = _service(conn, storage)
    cid = _character(conn)
    v1 = service.create_draft(cid)
    service.add_image(v1.id, make_png_bytes(), "face_front")
    service.promote(v1.id)
    v2 = service.create_draft(cid)

    flaky = _FlakyConn(conn, "UPDATE ref_set SET status = 'canonical'")
    flaky_service = RefSetService(flaky, storage)
    with pytest.raises(RefSetError):
        flaky_service.promote(v2.id)

    # The retire of v1 was rolled back with the failed promote of v2.
    assert _status(conn, v1.id) == "canonical"
    assert _status(conn, v2.id) == "draft"
    assert _canonical_count(conn, cid) == 1


def test_promote_works_with_open_outer_transaction(conn, storage):
    """promote must not fail when the connection already has an open
    transaction (its explicit SAVEPOINT boundary nests, so no
    'cannot start a transaction within a transaction' error)."""
    service = _service(conn, storage)
    cid = _character(conn)
    v1 = service.create_draft(cid)
    service.promote(v1.id)
    v2 = service.create_draft(cid)

    # Open an outer transaction with an unrelated write.
    conn.execute("UPDATE character SET name = name WHERE id = ?", (cid,))
    assert conn.in_transaction

    promoted = service.promote(v2.id)
    assert promoted.status == "canonical"
    assert _status(conn, v1.id) == "retired"
    assert _canonical_count(conn, cid) == 1
    assert conn.in_transaction

    # Promotion must not commit its caller's transaction. Rolling back the
    # outer transaction restores both ref-set statuses.
    conn.rollback()
    assert _status(conn, v1.id) == "canonical"
    assert _status(conn, v2.id) == "draft"


def test_image_edit_rejects_image_from_another_ref_set(conn, storage):
    service = _service(conn, storage)
    first_character = _character(conn, "First", "first")
    second_character = _character(conn, "Second", "second")
    first_set = service.create_draft(first_character)
    second_set = service.create_draft(second_character)
    image = service.add_image(first_set.id, make_png_bytes(), "face_front")

    with pytest.raises(RefSetError, match="does not belong"):
        service.set_image_role(second_set.id, image.id, "outfit")
    with pytest.raises(RefSetError, match="does not belong"):
        service.remove_image(second_set.id, image.id)

    assert service.images(first_set.id)[0].role == "face_front"


# ---------------------------------------------------------------------------
# new draft from existing
# ---------------------------------------------------------------------------

def test_copy_to_new_draft_copies_images(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    v1 = service.create_draft(cid)
    a = service.add_image(v1.id, make_png_bytes((10, 20, 30)), "face_front")
    b = service.add_image(v1.id, make_png_bytes((30, 20, 10)), "outfit")
    service.promote(v1.id)

    v2 = service.copy_to_new_draft(v1.id)

    assert v2.id != v1.id
    assert v2.character_id == cid
    assert v2.version == 2
    assert v2.status == "draft"

    copied = service.images(v2.id)
    assert [(i.sha256, i.role, i.weight) for i in copied] == [
        (a.sha256, a.role, a.weight),
        (b.sha256, b.role, b.weight),
    ]
    # The original canonical is untouched.
    assert _status(conn, v1.id) == "canonical"
    assert _canonical_count(conn, cid) == 1


def test_copy_from_draft_works(conn, storage):
    service = _service(conn, storage)
    cid = _character(conn)
    d1 = service.create_draft(cid)
    service.add_image(d1.id, make_png_bytes(), "face_front")
    d2 = service.copy_to_new_draft(d1.id)
    assert d2.version == 2
    assert len(service.images(d2.id)) == 1


def test_copy_does_not_share_rows(conn, storage):
    """Copying duplicates rows; editing the copy must not touch the source."""
    service = _service(conn, storage)
    cid = _character(conn)
    d1 = service.create_draft(cid)
    img = service.add_image(d1.id, make_png_bytes(), "face_front")
    d2 = service.copy_to_new_draft(d1.id)

    service.remove_image(d2.id, service.images(d2.id)[0].id)
    assert len(service.images(d1.id)) == 1
    assert service.images(d1.id)[0].id == img.id
