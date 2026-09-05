"""Upload-first Base Stage library service."""

from __future__ import annotations

import sqlite3
from fractions import Fraction

from app.domain.models import BaseStage, BaseStageTarget
from app.models import ASPECT_RATIOS
from app.storage import ImageStorage, ImageStorageError

MAX_DESCRIPTION_LENGTH = 2_000
MAX_TARGETS = 8
MAX_TARGET_DESCRIPTION_LENGTH = 500
MAX_IMAGE_WIDTH = 8_192
MAX_IMAGE_HEIGHT = 8_192
MAX_IMAGE_PIXELS = 40_000_000


class BaseStageError(Exception):
    """Base error for Base Stage operations."""


class BaseStageNotFoundError(BaseStageError):
    """Raised when a Base Stage id does not exist."""


class BaseStageValidationError(BaseStageError):
    """Raised when upload metadata or image bytes are invalid."""


class BaseStageNotReadyError(BaseStageError):
    """Raised when content is requested before a stage is ready."""


class BaseStageService:
    def __init__(self, conn: sqlite3.Connection, storage: ImageStorage) -> None:
        self.conn = conn
        self.storage = storage

    def list(self) -> list[BaseStage]:
        return self._list_where("bs.archived_at IS NULL")

    def list_archived(self) -> list[BaseStage]:
        return self._list_where("bs.archived_at IS NOT NULL")

    def get(self, base_stage_id: int) -> BaseStage:
        row = self.conn.execute(
            self._select_sql() + " WHERE bs.id = ?", (base_stage_id,)
        ).fetchone()
        if row is None:
            raise BaseStageNotFoundError(f"base stage {base_stage_id} not found")
        return self._from_row(row)

    def upload(
        self,
        data: bytes,
        description: str,
        targets: list[str],
        *,
        source_name: str | None = None,
    ) -> BaseStage:
        clean_description = self._validate_description(description)
        clean_targets = self._validate_targets(targets)
        try:
            image = self.storage.store(
                data,
                source_name=source_name,
                allowed_formats={"PNG", "JPEG", "WEBP"},
                reject_animated=True,
                max_width=MAX_IMAGE_WIDTH,
                max_height=MAX_IMAGE_HEIGHT,
                max_pixels=MAX_IMAGE_PIXELS,
            )
        except ImageStorageError as exc:
            raise BaseStageValidationError(f"image rejected: {exc}") from exc

        try:
            with self.conn:
                cursor = self.conn.execute(
                    """
                    INSERT INTO base_stage
                        (origin, state, description, aspect_ratio, uploaded_sha256,
                         image_width, image_height)
                    VALUES ('upload', 'ready', ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_description,
                        self._nearest_aspect_ratio(image.width, image.height),
                        image.sha256,
                        image.width,
                        image.height,
                    ),
                )
                base_stage_id = int(cursor.lastrowid)
                self.conn.executemany(
                    "INSERT INTO base_stage_target "
                    "(base_stage_id, position, description) VALUES (?, ?, ?)",
                    [
                        (base_stage_id, position, target)
                        for position, target in enumerate(clean_targets)
                    ],
                )
        except sqlite3.Error as exc:
            raise BaseStageError(f"could not save base stage: {exc}") from exc
        return self.get(base_stage_id)

    def archive(self, base_stage_id: int) -> BaseStage:
        stage = self.get(base_stage_id)
        if stage.archived_at is None:
            with self.conn:
                self.conn.execute(
                    "UPDATE base_stage SET archived_at = datetime('now') WHERE id = ?",
                    (base_stage_id,),
                )
        return self.get(base_stage_id)

    def restore(self, base_stage_id: int) -> BaseStage:
        self.get(base_stage_id)
        with self.conn:
            self.conn.execute(
                "UPDATE base_stage SET archived_at = NULL WHERE id = ?",
                (base_stage_id,),
            )
        return self.get(base_stage_id)

    def content_sha(self, base_stage_id: int) -> str:
        stage = self.get(base_stage_id)
        if stage.state != "ready":
            raise BaseStageNotReadyError(f"base stage {base_stage_id} is not ready")
        if stage.uploaded_sha256 is not None:
            return stage.uploaded_sha256
        if stage.selected_candidate_id is not None:
            row = self.conn.execute(
                "SELECT sha256 FROM candidate WHERE id = ?",
                (stage.selected_candidate_id,),
            ).fetchone()
            if row is not None:
                return str(row["sha256"])
        raise BaseStageNotReadyError(f"base stage {base_stage_id} has no content")

    def _list_where(self, where: str) -> list[BaseStage]:
        rows = self.conn.execute(
            self._select_sql() + f" WHERE {where} ORDER BY bs.created_at DESC, bs.id DESC"
        ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _select_sql() -> str:
        return (
            "SELECT bs.*, (SELECT COUNT(*) FROM scene s "
            "WHERE s.base_stage_id = bs.id) AS usage_count FROM base_stage bs"
        )

    def _from_row(self, row: sqlite3.Row) -> BaseStage:
        targets = self.conn.execute(
            "SELECT * FROM base_stage_target WHERE base_stage_id = ? "
            "ORDER BY position, id",
            (row["id"],),
        ).fetchall()
        return BaseStage(
            id=row["id"],
            origin=row["origin"],
            state=row["state"],
            description=row["description"],
            beat_text=row["beat_text"],
            camera=row["camera"],
            framing=row["framing"],
            mood=row["mood"],
            aspect_ratio=row["aspect_ratio"],
            style_id=row["style_id"],
            model=row["model"],
            image_size=row["image_size"],
            uploaded_sha256=row["uploaded_sha256"],
            selected_candidate_id=row["selected_candidate_id"],
            image_width=row["image_width"],
            image_height=row["image_height"],
            revision=row["revision"],
            created_at=row["created_at"],
            archived_at=row["archived_at"],
            targets=tuple(
                BaseStageTarget(
                    id=target["id"],
                    base_stage_id=target["base_stage_id"],
                    position=target["position"],
                    description=target["description"],
                )
                for target in targets
            ),
            usage_count=row["usage_count"],
        )

    @staticmethod
    def _validate_description(description: str) -> str:
        clean = description.strip()
        if not clean:
            raise BaseStageValidationError("description is required")
        if len(clean) > MAX_DESCRIPTION_LENGTH:
            raise BaseStageValidationError(
                f"description must be at most {MAX_DESCRIPTION_LENGTH} characters"
            )
        return clean

    @staticmethod
    def _validate_targets(targets: list[str]) -> list[str]:
        if not isinstance(targets, list) or any(not isinstance(item, str) for item in targets):
            raise BaseStageValidationError("targets must be an array of strings")
        if len(targets) > MAX_TARGETS:
            raise BaseStageValidationError(f"at most {MAX_TARGETS} targets are allowed")
        clean = [target.strip() for target in targets]
        if any(not target for target in clean):
            raise BaseStageValidationError("target descriptions must not be blank")
        if any(len(target) > MAX_TARGET_DESCRIPTION_LENGTH for target in clean):
            raise BaseStageValidationError(
                "target descriptions must be at most "
                f"{MAX_TARGET_DESCRIPTION_LENGTH} characters"
            )
        folded = [target.casefold() for target in clean]
        if len(set(folded)) != len(folded):
            raise BaseStageValidationError(
                "target descriptions must be unique (case-insensitive)"
            )
        return clean

    @staticmethod
    def _nearest_aspect_ratio(width: int, height: int) -> str:
        actual = Fraction(width, height)
        return min(
            ASPECT_RATIOS,
            key=lambda ratio: abs(
                actual - Fraction(*(int(part) for part in ratio.split(":")))
            ),
        )
