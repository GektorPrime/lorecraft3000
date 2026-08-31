"""Character library service: CRUD + the bio != prompt enforcement.

Non-negotiable rules enforced here (agents.md):
  - lore_md is LOCAL-ONLY. It is never included in model_payload(), the
    model-facing representation the prompt assembler (Slice 3) will consume.
  - visual_contract is the model-facing text, hard-capped at 60 words
    (deterministic word count). Submissions over the cap are REJECTED with a
    clear error — never silently truncated.
  - negative_traits is provider-facing and travels with the model payload.
  - slug is unique; collisions fail loudly (never auto-suffixed).
"""

from __future__ import annotations

import sqlite3

from app.domain.models import Character
from app.services.validation import VISUAL_CONTRACT_MAX_WORDS, slugify, word_count


class CharacterError(Exception):
    """Base error for the character service."""


class SlugCollisionError(CharacterError):
    """Raised when a slug is already taken by another character."""


class VisualContractTooLongError(CharacterError):
    """Raised when visual_contract exceeds the 60-word cap."""


class CharacterNotFoundError(CharacterError):
    """Raised when a character id does not exist."""


class InvalidStyleReferenceError(CharacterError):
    """Raised when default_style_id does not reference an existing style.

    Kept distinct from SlugCollisionError so an invalid style reference is
    reported as a style-reference problem, never misclassified as a slug
    collision (the two have different UNIQUE/FK constraint sources).
    """


class CharacterService:
    """CRUD for characters against a SQLite connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def list(self) -> list[Character]:
        rows = self.conn.execute(
            "SELECT * FROM character ORDER BY name COLLATE NOCASE, id"
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get(self, character_id: int) -> Character:
        row = self.conn.execute(
            "SELECT * FROM character WHERE id = ?", (character_id,)
        ).fetchone()
        if row is None:
            raise CharacterNotFoundError(f"character {character_id} not found")
        return self._from_row(row)

    def get_by_slug(self, slug: str) -> Character | None:
        row = self.conn.execute(
            "SELECT * FROM character WHERE slug = ?", (slug,)
        ).fetchone()
        return self._from_row(row) if row is not None else None

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        name: str,
        slug: str | None = None,
        lore_md: str = "",
        visual_contract: str = "",
        negative_traits: str = "",
        default_style_id: int | None = None,
    ) -> Character:
        """Create a character. Raises on slug collision or over-cap contract."""
        self._validate_visual_contract(visual_contract)
        self._validate_style_reference(default_style_id)
        final_slug = self._resolve_slug(name, slug, exclude_id=None)
        try:
            cur = self.conn.execute(
                """
                INSERT INTO character
                    (name, slug, lore_md, visual_contract, negative_traits,
                     default_style_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    final_slug,
                    lore_md,
                    visual_contract,
                    negative_traits,
                    default_style_id,
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            raise SlugCollisionError(
                f"slug '{final_slug}' is already taken — choose a different slug"
            ) from exc
        return self.get(cur.lastrowid)

    def update(
        self,
        character_id: int,
        *,
        name: str,
        slug: str | None = None,
        lore_md: str = "",
        visual_contract: str = "",
        negative_traits: str = "",
        default_style_id: int | None = None,
    ) -> Character:
        """Update a character. Raises on slug collision or over-cap contract."""
        self.get(character_id)  # raises CharacterNotFoundError if missing
        self._validate_visual_contract(visual_contract)
        self._validate_style_reference(default_style_id)
        final_slug = self._resolve_slug(name, slug, exclude_id=character_id)
        try:
            self.conn.execute(
                """
                UPDATE character
                   SET name = ?, slug = ?, lore_md = ?, visual_contract = ?,
                       negative_traits = ?, default_style_id = ?
                 WHERE id = ?
                """,
                (
                    name,
                    final_slug,
                    lore_md,
                    visual_contract,
                    negative_traits,
                    default_style_id,
                    character_id,
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            raise SlugCollisionError(
                f"slug '{final_slug}' is already taken — choose a different slug"
            ) from exc
        return self.get(character_id)

    # ------------------------------------------------------------------
    # model-facing representation (bio != prompt)
    # ------------------------------------------------------------------

    def model_payload(self, character_id: int) -> dict:
        """The model-facing representation of a character.

        This is the assembly-input shape the prompt assembler (Slice 3) will
        consume. lore_md is LOCAL-ONLY and is deliberately ABSENT here — the
        lore never leaves the library.
        """
        c = self.get(character_id)
        self._validate_visual_contract(c.visual_contract)
        return {
            "character_id": c.id,
            "name": c.name,
            "slug": c.slug,
            "visual_contract": c.visual_contract,
            "negative_traits": c.negative_traits,
            "default_style_id": c.default_style_id,
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _validate_visual_contract(self, visual_contract: str) -> None:
        n = word_count(visual_contract)
        if n > VISUAL_CONTRACT_MAX_WORDS:
            raise VisualContractTooLongError(
                f"visual_contract exceeds the {VISUAL_CONTRACT_MAX_WORDS}-word cap "
                f"(got {n} words) — trim it and resubmit"
            )

    def _validate_style_reference(self, default_style_id: int | None) -> None:
        """Reject default_style_id values that reference no existing style.

        This keeps the IntegrityError -> SlugCollisionError mapping honest:
        after this check, the only UNIQUE constraint a character insert/update
        can still violate is the slug, so a real slug collision is the only
        IntegrityError that can surface from the write itself.
        """
        if default_style_id is None:
            return
        row = self.conn.execute(
            "SELECT id FROM style WHERE id = ?", (default_style_id,)
        ).fetchone()
        if row is None:
            raise InvalidStyleReferenceError(
                f"default_style_id {default_style_id} does not reference an "
                "existing style — choose a style from the list"
            )

    def _resolve_slug(self, name: str, slug: str | None, *, exclude_id: int | None) -> str:
        """Use the given slug, or derive one from the name; check collisions."""
        final_slug = slug.strip() if slug and slug.strip() else slugify(name)
        if not final_slug:
            raise CharacterError("slug is required (and could not be derived from name)")
        existing = self.get_by_slug(final_slug)
        if existing is not None and existing.id != exclude_id:
            raise SlugCollisionError(
                f"slug '{final_slug}' is already taken — choose a different slug"
            )
        return final_slug

    @staticmethod
    def _from_row(row) -> Character:
        return Character(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
            lore_md=row["lore_md"],
            visual_contract=row["visual_contract"],
            negative_traits=row["negative_traits"],
            default_style_id=row["default_style_id"],
            created_at=row["created_at"],
        )
