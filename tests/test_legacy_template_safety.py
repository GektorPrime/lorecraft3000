"""Regression tests for destructive confirmations and legacy privacy copy."""

from __future__ import annotations

from types import SimpleNamespace

from app.deps import templates


PROMOTION_CONFIRMATION = (
    "Promote this draft to canonical? The draft will become immutable, and the "
    "current canonical, if any, will be retired."
)


def test_character_detail_confirms_draft_promotion():
    character = SimpleNamespace(
        id=2,
        name="Elias",
        slug="elias",
        visual_contract="",
        negative_traits="",
        lore_md="local lore",
    )
    draft = SimpleNamespace(id=7, version=1, status="draft")

    html = templates.get_template("characters/detail.html").render(
        character=character,
        default_style=None,
        ref_sets=[SimpleNamespace(ref_set=draft, image_count=1)],
    )

    assert f"return confirm('{PROMOTION_CONFIRMATION}');" in html
    assert "never sent to Gemini" in html


def test_ref_set_detail_confirms_draft_promotion_and_preserves_remove_confirmation():
    character = SimpleNamespace(id=2, name="Elias")
    draft = SimpleNamespace(id=7, version=1, status="draft", created_at="today")

    html = templates.get_template("ref_sets/detail.html").render(
        character=character,
        ref_set=draft,
        canonical=None,
        images=[SimpleNamespace(id=11, role="face_front", sha256="a" * 64, weight=1)],
        error=None,
    )

    assert f"return confirm('{PROMOTION_CONFIRMATION}');" in html
    assert "return confirm('Remove this image from the draft?');" in html


def test_legacy_privacy_copy_names_gemini_and_discloses_paid_payload():
    html = templates.get_template("characters/form.html").render(
        character=None,
        error=None,
        values={
            "name": "",
            "slug": "",
            "lore_md": "",
            "visual_contract": "",
            "negative_traits": "",
            "default_style_id": None,
        },
        styles=[],
    )

    assert "Never sent to Gemini" in html
    assert "Gemini-facing" in html
    assert "Data is stored locally" in html
    assert "displayed assembled prompt and selected canonical reference images to Gemini" in html
    assert "lore notes are excluded" in html
    assert "no data leaves this machine" not in html
