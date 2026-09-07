"""Tests for style CRUD and the seeded Victorian default style."""

from __future__ import annotations

import pytest

from app.db import connect
from app.services.styles import (
    DEFAULT_STYLE_CONTRACT,
    DEFAULT_STYLE_NAME,
    StyleArchivedError,
    StyleNameCollisionError,
    StyleNotFoundError,
    StyleService,
)


def _service(conn) -> StyleService:
    return StyleService(conn)


# ---------------------------------------------------------------------------
# seeded default style
# ---------------------------------------------------------------------------

def test_default_victorian_style_seeded_by_migrations(db_path):
    """Every migrated DB (incl. test DBs via run_migrations) has the default."""
    conn = connect(db_path)
    try:
        style = StyleService(conn).get_default()
    finally:
        conn.close()
    assert style.name == DEFAULT_STYLE_NAME
    assert style.style_contract == DEFAULT_STYLE_CONTRACT


def test_default_style_contract_is_non_empty(conn):
    style = _service(conn).get_default()
    assert len(style.style_contract.split()) > 10


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_create_style_round_trip(conn):
    s = _service(conn).create(
        name="Ink Wash",
        style_contract="Loose ink wash, high contrast.",
    )
    assert s.id > 0
    assert s.name == "Ink Wash"
    assert s.style_contract == "Loose ink wash, high contrast."

    fetched = _service(conn).get(s.id)
    assert fetched == s


def test_create_style_defaults(conn):
    s = _service(conn).create(name="Minimal")
    assert s.style_contract == ""


def test_list_styles_includes_default(conn):
    names = [s.name for s in _service(conn).list()]
    assert DEFAULT_STYLE_NAME in names


def test_update_style(conn):
    service = _service(conn)
    s = service.create(name="Old Name", style_contract="old")
    updated = service.update(s.id, name="New Name", style_contract="new")
    assert updated.name == "New Name"
    assert updated.style_contract == "new"


def test_legacy_ref_image_ids_are_ignored_and_preserved(conn):
    cur = conn.execute(
        "INSERT INTO style (name, style_contract, ref_image_ids) VALUES (?, ?, ?)",
        ("Legacy Style", "old", "[12, 15]"),
    )
    conn.commit()

    service = _service(conn)
    style = service.get(cur.lastrowid)
    assert style.name == "Legacy Style"
    assert "ref_image_ids" not in style.__dict__

    service.update(style.id, name=style.name, style_contract="updated")
    row = conn.execute(
        "SELECT ref_image_ids FROM style WHERE id = ?", (style.id,)
    ).fetchone()
    assert row["ref_image_ids"] == "[12, 15]"


def test_get_missing_style_raises(conn):
    with pytest.raises(StyleNotFoundError):
        _service(conn).get(99999)


# ---------------------------------------------------------------------------
# name uniqueness
# ---------------------------------------------------------------------------

def test_style_name_unique(conn):
    service = _service(conn)
    service.create(name="Ink Wash")
    with pytest.raises(StyleNameCollisionError) as excinfo:
        service.create(name="Ink Wash")
    assert "Ink Wash" in str(excinfo.value)


def test_style_name_unique_on_update(conn):
    service = _service(conn)
    a = service.create(name="Ink Wash")
    service.create(name="Watercolor")
    with pytest.raises(StyleNameCollisionError):
        service.update(a.id, name="Watercolor")


def test_update_keeping_own_name_is_allowed(conn):
    service = _service(conn)
    s = service.create(name="Ink Wash")
    updated = service.update(s.id, name="Ink Wash", style_contract="tweaked")
    assert updated.name == "Ink Wash"
    assert updated.style_contract == "tweaked"


# ---------------------------------------------------------------------------
# archive / restore (soft delete)
# ---------------------------------------------------------------------------

def test_archive_hides_from_list_but_get_still_resolves(conn):
    service = _service(conn)
    s = service.create(name="Ink Wash", style_contract="x")
    service.archive(s.id)
    assert all(x.name != "Ink Wash" for x in service.list())
    # Existing scenes reference styles by id, so archived styles must still
    # resolve — the display name is preserved.
    fetched = service.get(s.id)
    assert fetched.name == "Ink Wash"
    assert fetched.archived_at is not None


def test_archive_frees_name_for_reuse(conn):
    service = _service(conn)
    s = service.create(name="Ink Wash")
    service.archive(s.id)
    reused = service.create(name="Ink Wash")
    assert reused.id != s.id
    assert reused.name == "Ink Wash"
    assert reused.archived_at is None


def test_archive_is_idempotent(conn):
    service = _service(conn)
    s = service.create(name="Ink Wash")
    service.archive(s.id)
    again = service.archive(s.id)
    assert again.archived_at is not None


def test_default_style_cannot_be_archived(conn):
    service = _service(conn)
    default = service.get_default()
    with pytest.raises(StyleArchivedError):
        service.archive(default.id)


def test_archive_missing_style_raises(conn):
    with pytest.raises(StyleNotFoundError):
        _service(conn).archive(99999)


def test_restore_reclaims_original_name(conn):
    service = _service(conn)
    s = service.create(name="Ink Wash", style_contract="x")
    service.archive(s.id)
    restored = service.restore(s.id)
    assert restored.name == "Ink Wash"
    assert restored.archived_at is None
    assert any(x.id == s.id for x in service.list())


def test_restore_blocked_when_name_taken_by_active(conn):
    service = _service(conn)
    s = service.create(name="Ink Wash")
    service.archive(s.id)
    service.create(name="Ink Wash")  # reclaims the freed name
    with pytest.raises(StyleNameCollisionError):
        service.restore(s.id)


def test_list_archived_returns_only_archived(conn):
    service = _service(conn)
    active = service.create(name="Active")
    archived = service.create(name="Archived Later")
    service.archive(archived.id)
    archived_names = [s.name for s in service.list_archived()]
    assert "Archived Later" in archived_names
    assert "Active" not in archived_names
    assert active.id not in {s.id for s in service.list_archived()}
