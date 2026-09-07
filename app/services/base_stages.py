"""Base Stage library service: uploaded artwork and generated compositions."""

from __future__ import annotations

import sqlite3
from fractions import Fraction

from app.assembler.core import AssemblyError, capabilities_for
from app.config import Settings
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


class BaseStageLockedError(BaseStageError):
    """Raised when an immutable or in-flight Base Stage is modified."""


class BaseStageService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        storage: ImageStorage,
        settings: Settings | None = None,
    ) -> None:
        self.conn = conn
        self.storage = storage
        self.settings = settings

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

    def create_generated(
        self,
        *,
        description: str,
        beat_text: str,
        camera: str,
        framing: str,
        mood: str,
        aspect_ratio: str,
        style_id: int,
        model: str,
        image_size: str,
        targets: list[str],
    ) -> BaseStage:
        """Create a generated Base Stage draft; it is not usable until published."""
        fields = self._validate_generated(
            description=description,
            beat_text=beat_text,
            camera=camera,
            framing=framing,
            mood=mood,
            aspect_ratio=aspect_ratio,
            style_id=style_id,
            model=model,
            image_size=image_size,
            targets=targets,
        )
        try:
            with self.conn:
                cursor = self.conn.execute(
                    """
                    INSERT INTO base_stage
                        (origin, state, description, beat_text, camera, framing,
                         mood, aspect_ratio, style_id, model, image_size)
                    VALUES ('generated', 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fields["description"],
                        fields["beat_text"],
                        fields["camera"],
                        fields["framing"],
                        fields["mood"],
                        fields["aspect_ratio"],
                        fields["style_id"],
                        fields["model"],
                        fields["image_size"],
                    ),
                )
                base_stage_id = int(cursor.lastrowid)
                self._replace_targets(base_stage_id, fields["targets"])
        except sqlite3.Error as exc:
            raise BaseStageError(f"could not save base stage: {exc}") from exc
        return self.get(base_stage_id)

    def update(
        self,
        base_stage_id: int,
        *,
        description: str,
        beat_text: str,
        camera: str,
        framing: str,
        mood: str,
        aspect_ratio: str,
        style_id: int,
        model: str,
        image_size: str,
        targets: list[str],
    ) -> BaseStage:
        """Edit a generated draft, bumping its revision so previews cannot drift.

        Mirrors scene immutability: a pending or successful attempt locks the
        composition, and a published stage is permanently immutable because
        scenes already reference its image. Duplicate to make a variant.
        """
        stage = self.get(base_stage_id)
        self._require_editable(stage)
        fields = self._validate_generated(
            description=description,
            beat_text=beat_text,
            camera=camera,
            framing=framing,
            mood=mood,
            aspect_ratio=aspect_ratio,
            style_id=style_id,
            model=model,
            image_size=image_size,
            targets=targets,
        )
        try:
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE base_stage
                       SET description = ?, beat_text = ?, camera = ?, framing = ?,
                           mood = ?, aspect_ratio = ?, style_id = ?, model = ?,
                           image_size = ?, revision = revision + 1
                     WHERE id = ?
                    """,
                    (
                        fields["description"],
                        fields["beat_text"],
                        fields["camera"],
                        fields["framing"],
                        fields["mood"],
                        fields["aspect_ratio"],
                        fields["style_id"],
                        fields["model"],
                        fields["image_size"],
                        base_stage_id,
                    ),
                )
                self.conn.execute(
                    "DELETE FROM base_stage_target WHERE base_stage_id = ?",
                    (base_stage_id,),
                )
                self._replace_targets(base_stage_id, fields["targets"])
        except sqlite3.Error as exc:
            raise BaseStageError(f"could not update base stage: {exc}") from exc
        return self.get(base_stage_id)

    def duplicate(self, base_stage_id: int) -> BaseStage:
        """Copy a generated stage's composition into a fresh, unattempted draft."""
        stage = self.get(base_stage_id)
        if stage.origin != "generated":
            raise BaseStageValidationError(
                "only generated base stages can be duplicated"
            )
        return self.create_generated(
            description=stage.description,
            beat_text=stage.beat_text or "",
            camera=stage.camera or "",
            framing=stage.framing or "",
            mood=stage.mood or "",
            aspect_ratio=stage.aspect_ratio,
            style_id=stage.style_id,
            model=stage.model,
            image_size=stage.image_size,
            targets=[target.description for target in stage.targets],
        )

    def publish(self, base_stage_id: int, candidate_id: int) -> BaseStage:
        """Promote one succeeded candidate to be this stage's permanent image.

        Promotion is explicit and one-way: once ready the source image is
        immutable, so any number of scenes can reference it without a later
        edit silently changing what they generate from.
        """
        stage = self.get(base_stage_id)
        if stage.origin != "generated":
            raise BaseStageValidationError(
                "only generated base stages can be published"
            )
        if stage.state == "ready":
            raise BaseStageLockedError(
                f"base stage {base_stage_id} is already published; "
                "duplicate it to build a variant"
            )
        row = self.conn.execute(
            """
            SELECT c.sha256 AS sha256
              FROM candidate AS c
              JOIN generation AS g ON g.id = c.generation_id
             WHERE c.id = ? AND g.base_stage_id = ? AND g.state = 'succeeded'
            """,
            (candidate_id, base_stage_id),
        ).fetchone()
        if row is None:
            raise BaseStageValidationError(
                f"candidate {candidate_id} is not a succeeded candidate "
                f"of base stage {base_stage_id}"
            )
        try:
            width, height = self.storage.dimensions(str(row["sha256"]))
        except ImageStorageError as exc:
            raise BaseStageError(f"candidate image is unavailable: {exc}") from exc
        try:
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE base_stage
                       SET state = 'ready', selected_candidate_id = ?,
                           image_width = ?, image_height = ?
                     WHERE id = ? AND state = 'draft'
                    """,
                    (candidate_id, width, height, base_stage_id),
                )
        except sqlite3.Error as exc:
            raise BaseStageError(f"could not publish base stage: {exc}") from exc
        return self.get(base_stage_id)

    def locking_generation_count(self, base_stage_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM generation "
            "WHERE base_stage_id = ? AND state IN ('pending', 'succeeded')",
            (base_stage_id,),
        ).fetchone()
        return int(row["n"])

    def is_editable(self, base_stage_id: int) -> bool:
        """Failed attempts stay editable; pending, successful, or ready lock."""
        stage = self.get(base_stage_id)
        if stage.origin != "generated" or stage.state != "draft":
            return False
        return self.locking_generation_count(base_stage_id) == 0

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

    def _require_editable(self, stage: BaseStage) -> None:
        if stage.origin != "generated":
            raise BaseStageValidationError(
                "only generated base stages can be edited"
            )
        if stage.state != "draft":
            raise BaseStageLockedError(
                f"base stage {stage.id} is published and immutable; "
                "duplicate it to build a variant"
            )
        if self.locking_generation_count(stage.id):
            raise BaseStageLockedError(
                f"base stage {stage.id} has a pending or successful generation; "
                "duplicate it to change the composition"
            )

    def _replace_targets(self, base_stage_id: int, targets: list[str]) -> None:
        self.conn.executemany(
            "INSERT INTO base_stage_target "
            "(base_stage_id, position, description) VALUES (?, ?, ?)",
            [
                (base_stage_id, position, target)
                for position, target in enumerate(targets)
            ],
        )

    def _validate_generated(
        self,
        *,
        description: str,
        beat_text: str,
        camera: str,
        framing: str,
        mood: str,
        aspect_ratio: str,
        style_id: int,
        model: str,
        image_size: str,
        targets: list[str],
    ) -> dict:
        clean_targets = self._validate_targets(targets)
        if not clean_targets:
            raise BaseStageValidationError(
                "a generated base stage needs at least one identity target"
            )
        for name, value in (("camera", camera), ("framing", framing)):
            if not isinstance(value, str) or not value.strip():
                raise BaseStageValidationError(f"{name} is required")
        if not isinstance(beat_text, str) or not beat_text.strip():
            raise BaseStageValidationError("action/beat is required")
        if not isinstance(mood, str):
            raise BaseStageValidationError("mood must be text")
        if aspect_ratio not in ASPECT_RATIOS:
            raise BaseStageValidationError(
                f"unsupported aspect ratio: {aspect_ratio}"
            )
        if (
            self.conn.execute(
                "SELECT 1 FROM style WHERE id = ?", (style_id,)
            ).fetchone()
            is None
        ):
            raise BaseStageValidationError(f"style {style_id} not found")
        self._validate_model_and_size(model, image_size)
        for label, value in (
            ("action/beat", beat_text),
            ("camera", camera),
            ("framing", framing),
            ("mood", mood),
        ):
            if len(value.strip()) > MAX_DESCRIPTION_LENGTH:
                raise BaseStageValidationError(
                    f"{label} must be at most {MAX_DESCRIPTION_LENGTH} characters"
                )
        return {
            "description": self._validate_description(description),
            "beat_text": beat_text.strip(),
            "camera": camera.strip(),
            "framing": framing.strip(),
            "mood": mood.strip(),
            "aspect_ratio": aspect_ratio,
            "style_id": style_id,
            "model": model,
            "image_size": image_size,
            "targets": clean_targets,
        }

    def _validate_model_and_size(self, model: str, image_size: str) -> None:
        try:
            capabilities_for(model)
        except AssemblyError as exc:
            raise BaseStageValidationError(str(exc)) from exc
        if self.settings is None:
            return
        if image_size not in self.settings.model_prices_cents.get(model, {}):
            raise BaseStageValidationError(
                f"unsupported image size {image_size} for {model}"
            )

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
