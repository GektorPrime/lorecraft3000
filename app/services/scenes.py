"""Scene/scene persistence and form validation."""

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
    """Raised when editing a scene with an active or successful generation.

    Failed generations preserve their own request snapshot and do not lock the
    scene. Pending and successful generations lock it so an in-flight request
    or accepted provenance cannot diverge from the scene definition.
    """


class SceneDeleteConflictError(SceneError):
    """Raised when a comic page still references one of the scene's candidates."""


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

    def list_for_base_stage(self, base_stage_id: int) -> list[Scene]:
        rows = self.conn.execute(
            "SELECT * FROM scene WHERE base_stage_id = ? ORDER BY id DESC",
            (base_stage_id,),
        ).fetchall()
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

    def latest_attempt_candidate_id(self, scene_id: int) -> int | None:
        row = self.conn.execute(
            "SELECT c.id AS candidate_id FROM generation AS g "
            "LEFT JOIN candidate AS c ON c.generation_id = g.id "
            "WHERE g.scene_id = ? ORDER BY g.id DESC, c.idx ASC LIMIT 1",
            (scene_id,),
        ).fetchone()
        if row is None or row["candidate_id"] is None:
            return None
        return int(row["candidate_id"])

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
        beat_text: str | None,
        camera: str | None,
        framing: str | None,
        mood: str | None,
        aspect_ratio: str,
        cast: list[dict],
        style_id: int | None,
        model: str,
        image_size: str,
        base_stage_id: int | None = None,
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
            base_stage_id=base_stage_id,
            existing_base_stage_id=None,
        )
        cursor = self.conn.execute(
            """
            INSERT INTO scene
                (beat_text, camera, framing, mood, aspect_ratio, cast_json,
                 style_id, model, image_size, base_stage_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["beat_text"], fields["camera"], fields["framing"],
                fields["mood"], fields["aspect_ratio"], json.dumps(fields["cast"]),
                fields["style_id"], fields["model"], fields["image_size"],
                fields["base_stage_id"],
            ),
        )
        self.conn.commit()
        return self.get(int(cursor.lastrowid))

    def update(
        self,
        scene_id: int,
        *,
        beat_text: str | None,
        camera: str | None,
        framing: str | None,
        mood: str | None,
        aspect_ratio: str,
        cast: list[dict],
        style_id: int | None,
        model: str,
        image_size: str,
        base_stage_id: int | None = None,
    ) -> Scene:
        """Update a scene unless a generation is pending or has succeeded.

        The backend is the enforcement point (not just the UI): even a
        request that bypasses a disabled form control is rejected here.
        """
        current = self.get(scene_id)
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
            base_stage_id=base_stage_id,
            existing_base_stage_id=current.base_stage_id,
        )
        cursor = self.conn.execute(
            """
            UPDATE scene
               SET beat_text = ?, camera = ?, framing = ?, mood = ?,
                    aspect_ratio = ?, cast_json = ?, style_id = ?, model = ?,
                     image_size = ?, base_stage_id = ?, revision = revision + 1
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
                fields["base_stage_id"],
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
                f"scene {scene_id} has a pending or successful generation and can "
                "no longer be edited; duplicate it instead"
            )
        self.conn.commit()
        return self.get(scene_id)

    def update_model(self, scene_id: int, *, model: str) -> Scene:
        """Change the model for future attempts unless one is in progress."""
        scene = self.get(scene_id)
        self._validate_model_and_size(model, scene.image_size)
        cursor = self.conn.execute(
            """
            UPDATE scene
               SET model = ?, revision = revision + 1
             WHERE id = ?
               AND NOT EXISTS (
                   SELECT 1 FROM generation
                    WHERE scene_id = scene.id AND state = 'pending'
               )
            """,
            (model, scene_id),
        )
        if cursor.rowcount != 1:
            self.conn.rollback()
            raise SceneImmutableError(
                f"scene {scene_id} has a generation in progress; its model cannot be changed"
            )
        self.conn.commit()
        return self.get(scene_id)

    def duplicate(self, scene_id: int) -> Scene:
        """Create a new scene prefilled from an existing one (new ID).

        The source scene — including its full generation history — is left
        untouched; this only inserts a new row. Used to let a scene with
        generations be "edited" without losing provenance: duplicate, then
        edit the fresh (zero-generation) copy.
        """
        source = self.get(scene_id)
        cursor = self.conn.execute(
            """
            INSERT INTO scene
                (beat_text, camera, framing, mood, aspect_ratio, cast_json,
                 style_id, model, image_size, base_stage_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.beat_text, source.camera, source.framing, source.mood,
                source.aspect_ratio, json.dumps(source.cast), source.style_id,
                source.model, source.image_size,
                source.base_stage_id,
            ),
        )
        self.conn.commit()
        return self.get(int(cursor.lastrowid))

    def delete(self, scene_id: int) -> None:
        """Permanently delete a scene and its full generation history.

        Scenes are hard-deleted (unlike characters/styles, which archive): the
        scene row plus every ``generation`` and its ``candidate`` rows are
        removed together in one transaction so no orphaned provenance is left
        behind. Content-addressed image blobs are shared and are not touched
        here (a candidate row is the only thing removed, not the stored bytes).
        """
        if self.conn.execute(
            "SELECT 1 FROM scene WHERE id = ?", (scene_id,)
        ).fetchone() is None:
            raise SceneNotFoundError(f"scene {scene_id} not found")
        referenced = self.conn.execute(
            """
            SELECT 1 FROM comic_page_panel cpp
            JOIN candidate c ON c.id = cpp.candidate_id
            JOIN generation g ON g.id = c.generation_id
            WHERE g.scene_id = ? LIMIT 1
            """,
            (scene_id,),
        ).fetchone()
        if referenced:
            raise SceneDeleteConflictError(
                f"scene {scene_id} cannot be deleted while a comic page uses one of its candidates"
            )
        try:
            self.conn.execute(
                """
                DELETE FROM candidate
                 WHERE generation_id IN (
                     SELECT id FROM generation WHERE scene_id = ?
                 )
                """,
                (scene_id,),
            )
            # image_provenance also references generation(id). It is otherwise
            # append-only, but a hard scene delete removes the scene's entire
            # history, provenance included, so nothing is left dangling.
            self.conn.execute(
                """
                DELETE FROM image_provenance
                 WHERE generation_id IN (
                     SELECT id FROM generation WHERE scene_id = ?
                 )
                """,
                (scene_id,),
            )
            # generation.parent_generation_id self-references generation(id)
            # (a retried/replayed attempt points at its parent). Clear those
            # links first so deleting the rows can't trip the self-referencing
            # foreign key mid-statement.
            self.conn.execute(
                "UPDATE generation SET parent_generation_id = NULL WHERE scene_id = ?",
                (scene_id,),
            )
            self.conn.execute("DELETE FROM generation WHERE scene_id = ?", (scene_id,))
            self.conn.execute("DELETE FROM scene WHERE id = ?", (scene_id,))
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            referenced = self.conn.execute(
                """
                SELECT 1 FROM comic_page_panel cpp
                JOIN candidate c ON c.id = cpp.candidate_id
                JOIN generation g ON g.id = c.generation_id
                WHERE g.scene_id = ? LIMIT 1
                """,
                (scene_id,),
            ).fetchone()
            if referenced:
                raise SceneDeleteConflictError(
                    f"scene {scene_id} cannot be deleted while a comic page uses one of its candidates"
                ) from exc
            raise
        except sqlite3.Error:
            self.conn.rollback()
            raise

    def _validate(
        self,
        *,
        beat_text: str | None,
        camera: str | None,
        framing: str | None,
        mood: str | None,
        aspect_ratio: str,
        cast: list[dict],
        style_id: int | None,
        model: str,
        image_size: str,
        base_stage_id: int | None,
        existing_base_stage_id: int | None,
    ) -> dict:
        staged = base_stage_id is not None
        if not staged and (not isinstance(beat_text, str) or not beat_text.strip()):
            raise SceneError("scene action/beat is required")
        if not staged and (
            not isinstance(camera, str)
            or not camera.strip()
            or not isinstance(framing, str)
            or not framing.strip()
        ):
            raise SceneError("camera and framing are required")
        if not staged and not isinstance(mood, str):
            raise SceneError("mood must be text")
        if not cast:
            raise SceneError("select at least one character")
        character_ids = [entry.get("character_id") for entry in cast]
        if any(
            not isinstance(character_id, int) or isinstance(character_id, bool)
            for character_id in character_ids
        ):
            raise SceneError("every cast entry requires a character")
        if len(character_ids) != len(set(character_ids)):
            raise SceneError("a character may appear only once in a scene")
        normalized_cast = self._normalize_cast(cast)
        if not staged and aspect_ratio not in ASPECT_RATIOS:
            raise SceneError(f"unsupported aspect ratio: {aspect_ratio}")
        self._validate_model_and_size(model, image_size)
        if not staged and style_id is None:
            raise SceneError("style is required")
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
        if staged:
            stage = self.conn.execute(
                "SELECT * FROM base_stage WHERE id = ?", (base_stage_id,)
            ).fetchone()
            if stage is None:
                raise SceneError(f"base stage {base_stage_id} not found")
            if stage["state"] != "ready":
                raise SceneError(f"base stage {base_stage_id} is not ready")
            if stage["archived_at"] is not None and base_stage_id != existing_base_stage_id:
                raise SceneError(f"base stage {base_stage_id} is archived")
            targets = self.conn.execute(
                "SELECT id FROM base_stage_target WHERE base_stage_id = ?",
                (base_stage_id,),
            ).fetchall()
            target_ids = {int(row["id"]) for row in targets}
            if not target_ids:
                raise SceneError("a base stage scene requires at least one target")
            mapped_ids = [entry.get("base_stage_target_id") for entry in normalized_cast]
            if len(mapped_ids) != len(target_ids):
                raise SceneError("cast count must equal base stage target count")
            if any(not isinstance(target_id, int) or isinstance(target_id, bool) for target_id in mapped_ids):
                raise SceneError("every cast member must map to a base stage target")
            if len(mapped_ids) != len(set(mapped_ids)):
                raise SceneError("a base stage target may be mapped only once")
            if set(mapped_ids) != target_ids:
                raise SceneError("every mapping target must belong to the selected base stage")
            normalized_cast = [
                {**entry, "role": ""} for entry in normalized_cast
            ]
            beat_text = stage["description"]
            camera = framing = mood = ""
            aspect_ratio = stage["aspect_ratio"]
            if style_id is None:
                style_id = stage["style_id"]
        if style_id is not None and self.conn.execute(
            "SELECT 1 FROM style WHERE id = ?", (style_id,)
        ).fetchone() is None:
            raise SceneError(f"style {style_id} not found")
        return {
            "beat_text": beat_text.strip(),
            "camera": camera.strip(),
            "framing": framing.strip(),
            "mood": (mood or "").strip(),
            "aspect_ratio": aspect_ratio,
            "cast": normalized_cast,
            "style_id": style_id,
            "model": model,
            "image_size": image_size,
            "base_stage_id": base_stage_id,
        }

    def _validate_model_and_size(self, model: str, image_size: str) -> None:
        try:
            capabilities_for(model)
        except AssemblyError as exc:
            raise SceneError(str(exc)) from exc
        if image_size not in self.settings.model_prices_cents.get(model, {}):
            raise SceneError(f"unsupported image size {image_size} for {model}")

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
                    "base_stage_target_id": entry.get("base_stage_target_id"),
                }
            )
        return normalized
