"""Scene/panel persistence and form validation."""

from __future__ import annotations

import json
import sqlite3

from app.assembler.core import AssemblyError, capabilities_for
from app.config import Settings
from app.domain.scenes import Scene


class SceneError(Exception):
    pass


class SceneNotFoundError(SceneError):
    pass


ASPECT_RATIOS = ("3:2", "16:9", "4:3", "1:1", "3:4", "9:16")


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
        if not beat_text.strip():
            raise SceneError("panel action/beat is required")
        if not camera.strip() or not framing.strip():
            raise SceneError("camera and framing are required")
        if not cast:
            raise SceneError("select at least one character")
        character_ids = [entry.get("character_id") for entry in cast]
        if any(not isinstance(character_id, int) for character_id in character_ids):
            raise SceneError("every cast entry requires a character")
        if len(character_ids) != len(set(character_ids)):
            raise SceneError("a character may appear only once in a panel")
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

        cursor = self.conn.execute(
            """
            INSERT INTO scene
                (beat_text, camera, framing, mood, aspect_ratio, cast_json,
                 style_id, model, image_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                beat_text.strip(), camera.strip(), framing.strip(), mood.strip(),
                aspect_ratio, json.dumps(cast), style_id, model, image_size,
            ),
        )
        self.conn.commit()
        return self.get(int(cursor.lastrowid))
