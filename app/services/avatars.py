"""Deterministic character avatar/icon selection from canonical reference sets.

Selection rule (issue #15):
  1. Prefer roles in this fixed priority order: face_front, face_3q,
     face_profile, full_body, then any other role.
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
from app.storage import ImageStorage

# Fixed role priority (lower sorts first / wins). Roles outside this map
# (currently "expression", "outfit") fall through to _OTHER_ROLE_RANK.
_ROLE_PRIORITY: dict[str, int] = {
    "face_front": 0,
    "face_3q": 1,
    "face_profile": 2,
    "full_body": 3,
}
_OTHER_ROLE_RANK = 4


def _role_rank(role: str) -> int:
    return _ROLE_PRIORITY.get(role, _OTHER_ROLE_RANK)


def select_avatar_image(images: list[RefImage]) -> RefImage | None:
    """Deterministically pick one image for use as an avatar/icon.

    Order: role priority (face_front > face_3q > face_profile > full_body >
    other), then higher weight, then lower (stabler, older) id. Returns None
    for an empty list — callers must fall back to initials, never guess.
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
