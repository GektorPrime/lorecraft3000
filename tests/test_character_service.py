"""Tests for the character library service.

Proves: CRUD, slug auto-derivation + loud collision failure, the 60-word
visual_contract cap (accept at/under, reject over), and the bio != prompt rule
(lore_md is absent from the model-facing payload).
"""

from __future__ import annotations

import json

import pytest

from app.services.characters import (
    CharacterNotFoundError,
    CharacterService,
    InvalidStyleReferenceError,
    SlugCollisionError,
    VisualContractTooLongError,
)
from app.services.validation import VISUAL_CONTRACT_MAX_WORDS


def _words(n: int) -> str:
    """A deterministic n-word string (trailing space is fine for split())."""
    return "word " * n


def _service(conn) -> CharacterService:
    return CharacterService(conn)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_create_character_round_trip(conn):
    c = _service(conn).create(
        name="Elias Thorne",
        slug="elias",
        lore_md="# Backstory\nGrew up in the fog.",
        visual_contract="Sharp jaw, pale grey eyes, scar over left brow.",
        negative_traits="no smile, no modern clothing",
        default_style_id=None,
    )
    assert c.id > 0
    assert c.name == "Elias Thorne"
    assert c.slug == "elias"
    assert c.lore_md == "# Backstory\nGrew up in the fog."
    assert c.visual_contract == "Sharp jaw, pale grey eyes, scar over left brow."
    assert c.negative_traits == "no smile, no modern clothing"

    fetched = _service(conn).get(c.id)
    assert fetched == c


def test_list_characters_ordered_by_name(conn):
    service = _service(conn)
    service.create(name="Zed", slug="zed")
    service.create(name="Ada", slug="ada")
    names = [c.name for c in service.list()]
    assert names == ["Ada", "Zed"]


def test_update_character(conn):
    service = _service(conn)
    c = service.create(name="Elias", slug="elias")
    updated = service.update(
        c.id,
        name="Elias Thorne",
        slug="elias-thorne",
        lore_md="new lore",
        visual_contract="new contract",
        negative_traits="new negatives",
    )
    assert updated.name == "Elias Thorne"
    assert updated.slug == "elias-thorne"
    assert updated.lore_md == "new lore"
    assert updated.visual_contract == "new contract"
    assert updated.negative_traits == "new negatives"


def test_get_missing_character_raises(conn):
    with pytest.raises(CharacterNotFoundError):
        _service(conn).get(99999)


def test_update_missing_character_raises(conn):
    with pytest.raises(CharacterNotFoundError):
        _service(conn).update(99999, name="x", slug="x")


# ---------------------------------------------------------------------------
# slug: auto-derivation + loud collision failure
# ---------------------------------------------------------------------------

def test_slug_auto_derived_from_name(conn):
    c = _service(conn).create(name="Elias Thorne")
    assert c.slug == "elias-thorne"


def test_slug_auto_derived_normalizes_case_and_punctuation(conn):
    c = _service(conn).create(name="  Dr. Margaret 'Maggie' O'Neil!  ")
    assert c.slug == "dr-margaret-maggie-o-neil"


def test_explicit_slug_wins_over_derivation(conn):
    c = _service(conn).create(name="Elias Thorne", slug="the-warden")
    assert c.slug == "the-warden"


def test_slug_collision_fails_loudly(conn):
    service = _service(conn)
    service.create(name="Elias", slug="elias")
    with pytest.raises(SlugCollisionError) as excinfo:
        service.create(name="Elias", slug="elias")
    assert "elias" in str(excinfo.value)


def test_derived_slug_collision_fails_loudly(conn):
    """Two characters with the same name must collide on the derived slug."""
    service = _service(conn)
    service.create(name="Elias Thorne")
    with pytest.raises(SlugCollisionError):
        service.create(name="Elias Thorne")


def test_slug_collision_on_update_fails_loudly(conn):
    service = _service(conn)
    a = service.create(name="Ada", slug="ada")
    service.create(name="Zed", slug="zed")
    with pytest.raises(SlugCollisionError):
        service.update(a.id, name="Ada", slug="zed")


def test_update_keeping_own_slug_is_allowed(conn):
    service = _service(conn)
    c = service.create(name="Ada", slug="ada")
    updated = service.update(c.id, name="Ada Lovelace", slug="ada")
    assert updated.slug == "ada"


# ---------------------------------------------------------------------------
# archive / restore (soft delete)
# ---------------------------------------------------------------------------

def test_archive_hides_from_list_but_get_still_resolves(conn):
    service = _service(conn)
    c = service.create(name="Alice", slug="alice")
    service.archive(c.id)
    assert all(x.slug != "alice" for x in service.list())
    # Existing panels reference characters by id, so archived characters must
    # still resolve — the display slug is preserved.
    fetched = service.get(c.id)
    assert fetched.slug == "alice"
    assert fetched.archived_at is not None


def test_archive_frees_slug_for_reuse(conn):
    service = _service(conn)
    c = service.create(name="Alice", slug="alice")
    service.archive(c.id)
    reused = service.create(name="Alice", slug="alice")
    assert reused.id != c.id
    assert reused.slug == "alice"
    assert reused.archived_at is None


def test_archive_is_idempotent(conn):
    service = _service(conn)
    c = service.create(name="Alice", slug="alice")
    service.archive(c.id)
    again = service.archive(c.id)
    assert again.archived_at is not None


def test_archive_missing_character_raises(conn):
    with pytest.raises(CharacterNotFoundError):
        _service(conn).archive(99999)


def test_restore_reclaims_original_slug(conn):
    service = _service(conn)
    c = service.create(name="Alice", slug="alice")
    service.archive(c.id)
    restored = service.restore(c.id)
    assert restored.slug == "alice"
    assert restored.archived_at is None
    assert any(x.id == c.id for x in service.list())


def test_restore_blocked_when_slug_taken_by_active(conn):
    service = _service(conn)
    c = service.create(name="Alice", slug="alice")
    service.archive(c.id)
    service.create(name="Alice", slug="alice")  # reclaims the freed slug
    with pytest.raises(SlugCollisionError):
        service.restore(c.id)


def test_list_archived_returns_only_archived(conn):
    service = _service(conn)
    active = service.create(name="Active", slug="active")
    archived = service.create(name="Gone", slug="gone")
    service.archive(archived.id)
    archived_slugs = [c.slug for c in service.list_archived()]
    assert "gone" in archived_slugs
    assert "active" not in archived_slugs
    assert active.id not in {c.id for c in service.list_archived()}


# ---------------------------------------------------------------------------
# default_style_id: invalid references are a style error, not a slug collision
# ---------------------------------------------------------------------------

def _first_style_id(conn) -> int:
    """The seeded default style (migration 002) is the first style row."""
    return conn.execute("SELECT id FROM style ORDER BY id LIMIT 1").fetchone()["id"]


def test_create_invalid_style_reference_rejected(conn):
    """A nonexistent default_style_id must raise a style-reference error, not
    be misclassified as a slug collision."""
    service = _service(conn)
    with pytest.raises(InvalidStyleReferenceError) as excinfo:
        service.create(name="Elias", slug="elias", default_style_id=99999)
    message = str(excinfo.value)
    assert "99999" in message
    assert "style" in message.lower()
    # No partial write.
    assert service.list() == []


def test_update_invalid_style_reference_rejected(conn):
    """An invalid default_style_id on update must raise and leave the
    character untouched (no partial write)."""
    service = _service(conn)
    c = service.create(name="Elias", slug="elias", visual_contract="Pale eyes.")
    with pytest.raises(InvalidStyleReferenceError):
        service.update(c.id, name="Elias", slug="elias", default_style_id=99999)
    fetched = service.get(c.id)
    assert fetched.name == "Elias"
    assert fetched.slug == "elias"
    assert fetched.default_style_id is None


def test_valid_style_reference_accepted(conn):
    style_id = _first_style_id(conn)
    c = _service(conn).create(name="Elias", slug="elias", default_style_id=style_id)
    assert c.default_style_id == style_id


def test_slug_collision_with_valid_style_still_raises_slug_collision(conn):
    """A real slug uniqueness violation must still surface as SlugCollisionError
    even when the style reference is valid (style validation must not mask it)."""
    service = _service(conn)
    style_id = _first_style_id(conn)
    service.create(name="Elias", slug="elias", default_style_id=style_id)
    with pytest.raises(SlugCollisionError):
        service.create(name="Elias 2", slug="elias", default_style_id=style_id)


# ---------------------------------------------------------------------------
# visual_contract: 60-word cap (deterministic word count)
# ---------------------------------------------------------------------------

def test_visual_contract_at_cap_accepted(conn):
    contract = _words(VISUAL_CONTRACT_MAX_WORDS)
    c = _service(conn).create(name="Elias", visual_contract=contract)
    assert c.visual_contract == contract


def test_visual_contract_under_cap_accepted(conn):
    c = _service(conn).create(name="Elias", visual_contract="Just a few words.")
    assert c.visual_contract == "Just a few words."


def test_visual_contract_empty_accepted(conn):
    c = _service(conn).create(name="Elias", visual_contract="")
    assert c.visual_contract == ""


def test_visual_contract_over_cap_rejected(conn):
    contract = _words(VISUAL_CONTRACT_MAX_WORDS + 1)
    with pytest.raises(VisualContractTooLongError) as excinfo:
        _service(conn).create(name="Elias", visual_contract=contract)
    message = str(excinfo.value)
    assert str(VISUAL_CONTRACT_MAX_WORDS) in message
    assert str(VISUAL_CONTRACT_MAX_WORDS + 1) in message
    assert "trim" in message.lower()


def test_visual_contract_over_cap_rejected_on_update(conn):
    service = _service(conn)
    c = service.create(name="Elias", visual_contract="Fine.")
    with pytest.raises(VisualContractTooLongError):
        service.update(c.id, name="Elias", slug="elias", visual_contract=_words(61))


def test_over_cap_rejection_leaves_no_row(conn):
    """A rejected create must not leave a partial character behind."""
    service = _service(conn)
    with pytest.raises(VisualContractTooLongError):
        service.create(name="Elias", visual_contract=_words(61))
    assert service.list() == []


# ---------------------------------------------------------------------------
# bio != prompt: lore_md never leaves the library
# ---------------------------------------------------------------------------

def test_model_payload_excludes_lore_md(conn):
    """The model-facing payload must not contain lore_md under any key."""
    service = _service(conn)
    c = service.create(
        name="Elias",
        lore_md="# SECRET BACKSTORY\nBetrayed by his brother.",
        visual_contract="Pale grey eyes, scar over left brow.",
        negative_traits="no smile",
    )
    payload = service.model_payload(c.id)
    assert "lore_md" not in payload
    # No key may smuggle lore under a different name.
    assert not any("lore" in key.lower() for key in payload)
    # The lore text itself must not appear anywhere in the serialized payload.
    assert "SECRET BACKSTORY" not in json.dumps(payload)
    assert "Betrayed" not in json.dumps(payload)


def test_model_payload_contains_model_facing_fields(conn):
    service = _service(conn)
    c = service.create(
        name="Elias",
        visual_contract="Pale grey eyes, scar over left brow.",
        negative_traits="no smile",
    )
    payload = service.model_payload(c.id)
    assert payload["character_id"] == c.id
    assert payload["name"] == "Elias"
    assert payload["slug"] == "elias"
    assert payload["visual_contract"] == "Pale grey eyes, scar over left brow."
    assert payload["negative_traits"] == "no smile"
    assert set(payload) == {
        "character_id",
        "name",
        "slug",
        "visual_contract",
        "negative_traits",
        "default_style_id",
    }