"""Scene/panel persistence and form validation."""

from __future__ import annotations

import json
import sqlite3

from app.assembler.core import AssemblyError, capabilities_for
from app.config import Settings
from app.domain.scenes import Scene
from app.models import ASPECT_RATIOS


class SceneError(Exception):
    pass


class SceneNotFoundError(SceneError):
    pass


class SceneImmutableError(SceneError):
    """Raised when editing a panel with an active or successful generation.

    Failed generations preserve their own request snapshot and do not lock the
    panel. Pending and successful generations lock it so an in-flight request
    or accepted provenance cannot diverge from the panel definition.
    """


# Re-exported from the registry (app/models.py) so existing callers of
# ``from app.services.scenes import ASPECT_RATIOS`` keep working; the registry
# is the single source of truth for the value.


class SceneService:
    def __init__(self, conn: sqlite3.Connection, settings: Settings) -> None:
        self.conn = conn
        self.settings = settings

    def list(self) -> list[Scene]:
        rows = self.conn.execute("SELECT * FROM scene ORDER BY id DESC").fetchall()
        return [Scene.from_row(row) for row in rows]

    def get(self, scene_id: int) -> Scene:
        row = self.conn.execute("SELECT * FROM scene WHERE id = ?", (scene_id,)).fetchone()
        if row is None:
            raise SceneNotFoundError(f"scene {scene_id} not found")
        return Scene.from_row(row)

    def generation_count(self, scene_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM generation WHERE scene_id = ?", (scene_id,)
        ).fetchone()
        return int(row["n"])

    def locking_generation_count(self, scene_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM generation "
            "WHERE scene_id = ? AND state IN ('pending', 'succeeded')",
            (scene_id,),
        ).fetchone()
        return int(row["n"])

    def is_editable(self, scene_id: int) -> bool:
        """Failed attempts remain editable; pending or successful ones lock."""
        return self.locking_generation_count(scene_id) == 0

    def create(
        self,
        *,
        beat_text: str,
        camera: str,
        framing: str,
        mood: str,
        aspect_ratio: str,
        cast: list[dict],
        style_id: int,
        model: str,
        image_size: str,
    ) -> Scene:
        fields = self._validate(
            beat_text=beat_text,
            camera=camera,
            framing=framing,
            mood=mood,
            aspect_ratio=aspect_ratio,
            cast=cast,
            style_id=style_id,
            model=model,
            image_size=image_size,
        )
        cursor = self.conn.execute(
            """
            INSERT INTO scene
                (beat_text, camera, framing, mood, aspect_ratio, cast_json,
                 style_id, model, image_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["beat_text"], fields["camera"], fields["framing"],
                fields["mood"], fields["aspect_ratio"], json.dumps(fields["cast"]),
                fields["style_id"], fields["model"], fields["image_size"],
            ),
        )
        self.conn.commit()
        return self.get(int(cursor.lastrowid))

    def update(
        self,
        scene_id: int,
        *,
        beat_text: str,
        camera: str,
        framing: str,
        mood: str,
        aspect_ratio: str,
        cast: list[dict],
        style_id: int,
        model: str,
        image_size: str,
    ) -> Scene:
        """Update a panel unless a generation is pending or has succeeded.

        The backend is the enforcement point (not just the UI): even a
        request that bypasses a disabled form control is rejected here.
        """
        fields = self._validate(
            beat_text=beat_text,
            camera=camera,
            framing=framing,
            mood=mood,
            aspect_ratio=aspect_ratio,
            cast=cast,
            style_id=style_id,
            model=model,
            image_size=image_size,
        )
        cursor = self.conn.execute(
            """
            UPDATE scene
               SET beat_text = ?, camera = ?, framing = ?, mood = ?,
                    aspect_ratio = ?, cast_json = ?, style_id = ?, model = ?,
                    image_size = ?, revision = revision + 1
             WHERE id = ?
               AND NOT EXISTS (
                   SELECT 1 FROM generation
                    WHERE scene_id = scene.id
                      AND state IN ('pending', 'succeeded')
               )
            """,
            (
                fields["beat_text"], fields["camera"], fields["framing"],
                fields["mood"], fields["aspect_ratio"], json.dumps(fields["cast"]),
                fields["style_id"], fields["model"], fields["image_size"],
                scene_id,
            ),
        )
        if cursor.rowcount != 1:
            self.conn.rollback()
            if self.conn.execute(
                "SELECT 1 FROM scene WHERE id = ?", (scene_id,)
            ).fetchone() is None:
                raise SceneNotFoundError(f"scene {scene_id} not found")
            raise SceneImmutableError(
                f"panel {scene_id} has a pending or successful generation and can "
                "no longer be edited; duplicate it instead"
            )
        self.conn.commit()
        return self.get(scene_id)

    def duplicate(self, scene_id: int) -> Scene:
        """Create a new panel prefilled from an existing one (new ID).

        The source panel — including its full generation history — is left
        untouched; this only inserts a new row. Used to let a panel with
        generations be "edited" without losing provenance: duplicate, then
        edit the fresh (zero-generation) copy.
        """
        source = self.get(scene_id)
        cursor = self.conn.execute(
            """
            INSERT INTO scene
                (beat_text, camera, framing, mood, aspect_ratio, cast_json,
                 style_id, model, image_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.beat_text, source.camera, source.framing, source.mood,
                source.aspect_ratio, json.dumps(source.cast), source.style_id,
                source.model, source.image_size,
            ),
        )
        self.conn.commit()
        return self.get(int(cursor.lastrowid))

    def _validate(
        self,
        *,
        beat_text: str,
        camera: str,
        framing: str,
        mood: str,
        aspect_ratio: str,
        cast: list[dict],
        style_id: int,
        model: str,
        image_size: str,
    ) -> dict:
        if not beat_text.strip():
            raise SceneError("panel action/beat is required")
        if not camera.strip() or not framing.strip():
            raise SceneError("camera and framing are required")
        if not cast:
            raise SceneError("select at least one character")
        character_ids = [entry.get("character_id") for entry in cast]
        if any(
            not isinstance(character_id, int) or isinstance(character_id, bool)
            for character_id in character_ids
        ):
            raise SceneError("every cast entry requires a character")
        if len(character_ids) != len(set(character_ids)):
            raise SceneError("a character may appear only once in a panel")
        normalized_cast = self._normalize_cast(cast)
        if aspect_ratio not in ASPECT_RATIOS:
            raise SceneError(f"unsupported aspect ratio: {aspect_ratio}")
        try:
            capabilities_for(model)
        except AssemblyError as exc:
            raise SceneError(str(exc)) from exc
        if image_size not in self.settings.model_prices_cents.get(model, {}):
            raise SceneError(f"unsupported image size {image_size} for {model}")
        if self.conn.execute("SELECT 1 FROM style WHERE id = ?", (style_id,)).fetchone() is None:
            raise SceneError(f"style {style_id} not found")
        existing = {
            row["id"]
            for row in self.conn.execute(
                f"SELECT id FROM character WHERE id IN ({','.join('?' for _ in character_ids)})",
                character_ids,
            ).fetchall()
        }
        missing = [character_id for character_id in character_ids if character_id not in existing]
        if missing:
            raise SceneError(f"characters not found: {missing}")
        return {
            "beat_text": beat_text.strip(),
            "camera": camera.strip(),
            "framing": framing.strip(),
            "mood": mood.strip(),
            "aspect_ratio": aspect_ratio,
            "cast": normalized_cast,
            "style_id": style_id,
            "model": model,
            "image_size": image_size,
        }

    @staticmethod
    def _normalize_cast(cast: list[dict]) -> list[dict]:
        """Validate and normalize each cast entry's role/prominence.

        Authoritative on the backend regardless of caller: cast prominence is
        enforced here in the service, not in any route, so the /api/v1 JSON API
        and any future caller are protected equally. Every cast entry that
        reaches persistence is validated and normalized here.
        """
        normalized: list[dict] = []
        for entry in cast:
            role = entry.get("role", "")
            if role is None:
                role = ""
            if not isinstance(role, str):
                raise SceneError("cast role must be text")
            prominence = entry.get("prominence", 1)
            if (
                not isinstance(prominence, int)
                or isinstance(prominence, bool)
                or prominence < 1
            ):
                raise SceneError("cast prominence must be a positive integer")
            normalized.append(
                {
                    "character_id": entry["character_id"],
                    "role": role.strip(),
                    "prominence": prominence,
                }
            )
        return normalized
