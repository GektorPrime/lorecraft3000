"""Tests for the style bible service.

Proves: CRUD, name uniqueness, ref_image_ids round-trip, and that the seeded
Victorian oil-painting default style is present in every migrated database.
"""

from __future__ import annotations

import pytest

from app.db import connect
from app.services.styles import (
    DEFAULT_STYLE_CONTRACT,
    DEFAULT_STYLE_NAME,
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
    assert style.ref_image_ids == []


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
        ref_image_ids=[1, 2, 3],
    )
    assert s.id > 0
    assert s.name == "Ink Wash"
    assert s.style_contract == "Loose ink wash, high contrast."
    assert s.ref_image_ids == [1, 2, 3]

    fetched = _service(conn).get(s.id)
    assert fetched == s


def test_create_style_defaults(conn):
    s = _service(conn).create(name="Minimal")
    assert s.style_contract == ""
    assert s.ref_image_ids == []


def test_list_styles_includes_default(conn):
    names = [s.name for s in _service(conn).list()]
    assert DEFAULT_STYLE_NAME in names


def test_update_style(conn):
    service = _service(conn)
    s = service.create(name="Old Name", style_contract="old", ref_image_ids=[1])
    updated = service.update(
        s.id, name="New Name", style_contract="new", ref_image_ids=[4, 5]
    )
    assert updated.name == "New Name"
    assert updated.style_contract == "new"
    assert updated.ref_image_ids == [4, 5]


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