"""Deterministic character avatar/icon selection from canonical reference sets.

Selection rule (issue #15):
  1. Prefer turnaround, then face views, body/outfit, and remaining roles.
  2. Within the same role, prefer the higher (displayed, immutable) weight.
  3. Break remaining ties by the stable ref_image id (ascending) so the pick
     never changes between calls for unchanged data.

If a character has no canonical reference set, or the canonical set has no
images, there is no avatar image and the caller (API/frontend) falls back to
initials — this module never invents an image.
"""

from __future__ import annotations

import sqlite3

from app.domain.models import RefImage
from app.services.ref_sets import RefSetService
from app.services.validation import ALLOWED_ROLES
from app.storage import ImageStorage

# Fixed role priority (lower sorts first / wins).
_ROLE_PRIORITY = {role: rank for rank, role in enumerate(ALLOWED_ROLES)}
_OTHER_ROLE_RANK = len(ALLOWED_ROLES)


def _role_rank(role: str) -> int:
    return _ROLE_PRIORITY.get(role, _OTHER_ROLE_RANK)


def select_avatar_image(images: list[RefImage]) -> RefImage | None:
    """Deterministically pick one image for use as an avatar/icon.

    Order: role priority (turnaround > face views > body/outfit > remaining roles),
    then higher weight, then lower (stabler, older) id. Returns None for an
    empty list — callers must fall back to initials, never guess.
    """
    if not images:
        return None
    return min(images, key=lambda img: (_role_rank(img.role), -img.weight, img.id))


class AvatarService:
    """Resolves a character's deterministic avatar image, if any."""

    def __init__(self, conn: sqlite3.Connection, storage: ImageStorage) -> None:
        self.conn = conn
        self.ref_sets = RefSetService(conn, storage)

    def avatar_image_for(self, character_id: int) -> RefImage | None:
        """The selected avatar RefImage for a character, or None.

        None means: no canonical ref-set yet, or the canonical set has no
        images. The frontend renders an initials fallback in that case.
        """
        canonical = self.ref_sets.get_canonical(character_id)
        if canonical is None:
            return None
        images = self.ref_sets.images(canonical.id)
        return select_avatar_image(images)
