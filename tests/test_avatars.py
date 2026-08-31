"""Tests for deterministic character avatar/icon selection (issue #15)."""

from __future__ import annotations

from app.services.avatars import AvatarService, select_avatar_image
from app.services.characters import CharacterService
from app.services.ref_sets import RefSetService
from tests.conftest import make_png_bytes


def _make_image(role, weight, image_id):
    """Build a minimal RefImage-like object for select_avatar_image tests."""
    from app.domain.models import RefImage

    return RefImage(
        id=image_id,
        ref_set_id=1,
        sha256="0" * 64,
        role=role,
        weight=weight,
        embedding=None,
        quality_flags=[],
        created_at="2026-08-31T00:00:00",
    )


def test_role_priority_face_front_wins_over_all_others():
    images = [
        _make_image("outfit", 1.0, 1),
        _make_image("full_body", 1.0, 2),
        _make_image("face_profile", 1.0, 3),
        _make_image("face_3q", 1.0, 4),
        _make_image("face_front", 1.0, 5),
    ]
    picked = select_avatar_image(images)
    assert picked.id == 5
    assert picked.role == "face_front"


def test_role_priority_order_face_3q_then_face_profile_then_full_body():
    images = [_make_image("full_body", 1.0, 1), _make_image("face_3q", 1.0, 2)]
    assert select_avatar_image(images).role == "face_3q"

    images = [_make_image("face_profile", 1.0, 1), _make_image("full_body", 1.0, 2)]
    assert select_avatar_image(images).role == "face_profile"


def test_other_roles_fall_through_after_named_priority_roles():
    images = [_make_image("expression", 1.0, 1), _make_image("full_body", 1.0, 2)]
    assert select_avatar_image(images).role == "full_body"


def test_same_role_breaks_tie_by_higher_weight():
    images = [
        _make_image("face_front", 0.5, 1),
        _make_image("face_front", 2.0, 2),
        _make_image("face_front", 1.0, 3),
    ]
    picked = select_avatar_image(images)
    assert picked.id == 2
    assert picked.weight == 2.0


def test_same_role_same_weight_breaks_tie_by_stable_lower_id():
    images = [
        _make_image("face_front", 1.0, 42),
        _make_image("face_front", 1.0, 7),
        _make_image("face_front", 1.0, 99),
    ]
    picked = select_avatar_image(images)
    assert picked.id == 7


def test_empty_list_returns_none_for_initials_fallback():
    assert select_avatar_image([]) is None


def test_selection_is_deterministic_across_repeated_calls():
    images = [
        _make_image("outfit", 1.0, 1),
        _make_image("face_3q", 1.0, 2),
        _make_image("face_profile", 1.0, 3),
    ]
    first = select_avatar_image(images)
    second = select_avatar_image(list(reversed(images)))
    assert first.id == second.id == 2


# ---------------------------------------------------------------------------
# AvatarService: integration against real canonical ref-set data
# ---------------------------------------------------------------------------

def test_avatar_service_returns_none_without_canonical_ref_set(conn, storage):
    character = CharacterService(conn).create(name="Elias", slug="elias")
    result = AvatarService(conn, storage).avatar_image_for(character.id)
    assert result is None


def test_avatar_service_returns_none_for_canonical_set_with_no_images(conn, storage):
    character = CharacterService(conn).create(name="Elias", slug="elias")
    ref_sets = RefSetService(conn, storage)
    draft = ref_sets.create_draft(character.id)
    ref_sets.promote(draft.id)
    result = AvatarService(conn, storage).avatar_image_for(character.id)
    assert result is None


def test_avatar_service_picks_face_front_from_canonical_set(conn, storage):
    character = CharacterService(conn).create(name="Elias", slug="elias")
    ref_sets = RefSetService(conn, storage)
    draft = ref_sets.create_draft(character.id)
    ref_sets.add_image(draft.id, make_png_bytes((10, 10, 10)), "outfit")
    face = ref_sets.add_image(draft.id, make_png_bytes((20, 20, 20)), "face_front")
    ref_sets.add_image(draft.id, make_png_bytes((30, 30, 30)), "full_body")
    ref_sets.promote(draft.id)

    result = AvatarService(conn, storage).avatar_image_for(character.id)
    assert result is not None
    assert result.id == face.id
    assert result.role == "face_front"


def test_avatar_service_uses_canonical_set_not_drafts(conn, storage):
    """A newer draft must never be used for the avatar — only canonical."""
    character = CharacterService(conn).create(name="Elias", slug="elias")
    ref_sets = RefSetService(conn, storage)
    draft1 = ref_sets.create_draft(character.id)
    ref_sets.add_image(draft1.id, make_png_bytes((1, 1, 1)), "face_front")
    ref_sets.promote(draft1.id)

    draft2 = ref_sets.create_draft(character.id)
    ref_sets.add_image(draft2.id, make_png_bytes((2, 2, 2)), "face_front")
    # draft2 is NOT promoted — still a draft.

    result = AvatarService(conn, storage).avatar_image_for(character.id)
    assert result is not None
    assert result.ref_set_id == draft1.id
