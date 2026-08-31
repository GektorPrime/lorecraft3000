"""End-to-end single-candidate generation orchestration."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from app.assembler.core import AssemblyError, assemble_prompt
from app.config import Settings
from app.domain.generation import CastInput, ReferenceInput, SceneInput
from app.providers.base import ImageProvider, ProviderReference, ProviderRequest
from app.services.characters import CharacterError, CharacterService
from app.services.costs import CostLedger
from app.services.ref_sets import RefSetError, RefSetService
from app.services.styles import StyleError, StyleService
from app.storage import ImageStorage, ImageStorageError


class GenerationError(Exception):
    pass


@dataclass(frozen=True)
class GenerationOutcome:
    generation_id: int
    candidate_id: int
    candidate_sha256: str
    prompt_hash: str
    cost_cents: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class GenerationPreview:
    scene_id: int
    model: str
    image_size: str
    prompt: str
    prompt_hash: str
    attachments: tuple[dict, ...]
    warnings: tuple[str, ...]
    estimated_cost_cents: int
    spent_today_cents: int
    remaining_after_cents: int
    provider_request: ProviderRequest
    request_capture: dict


_FORMAT_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}


class GenerationService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        storage: ImageStorage,
        settings: Settings,
        provider: ImageProvider | None,
    ) -> None:
        self.conn = conn
        self.storage = storage
        self.settings = settings
        self.provider = provider

    def preview(
        self,
        scene_id: int,
        *,
        model: str | None = None,
        image_size: str | None = None,
    ) -> GenerationPreview:
        """Run the exact no-spend preflight used by generate()."""
        selected_model = model or self.settings.default_model
        selected_size = image_size or self.settings.default_image_size
        scene_row = self.conn.execute(
            "SELECT * FROM scene WHERE id = ?", (scene_id,)
        ).fetchone()
        if scene_row is None:
            raise GenerationError(f"scene {scene_id} not found")
        if scene_row["style_id"] is None:
            raise GenerationError("scene has no style")

        try:
            style = StyleService(self.conn).get(scene_row["style_id"])
            cast = self._load_cast(scene_row["cast_json"])
            assembled = assemble_prompt(
                model=selected_model,
                image_size=selected_size,
                cast=cast,
                scene=SceneInput(
                    beat_text=scene_row["beat_text"],
                    camera=scene_row["camera"],
                    framing=scene_row["framing"],
                    mood=scene_row["mood"],
                    aspect_ratio=scene_row["aspect_ratio"],
                ),
                style_contract=style.style_contract,
            )
        except (AssemblyError, CharacterError, RefSetError, StyleError) as exc:
            raise GenerationError(f"scene cannot be generated: {exc}") from exc

        provider_refs: list[ProviderReference] = []
        attachment_capture: list[dict] = []
        for attachment in assembled.attachments:
            try:
                data, metadata = self.storage.read(attachment.sha256)
            except ImageStorageError as exc:
                raise GenerationError(
                    f"reference image {attachment.sha256} is unavailable: {exc}"
                ) from exc
            mime = _FORMAT_MIME.get(metadata.get("format"))
            if mime is None:
                raise GenerationError(
                    f"unsupported stored reference format: {metadata.get('format')}"
                )
            provider_refs.append(
                ProviderReference(
                    attachment.image_number, attachment.sha256, mime, data
                )
            )
            attachment_capture.append(
                {
                    "image_number": attachment.image_number,
                    "sha256": attachment.sha256,
                    "mime_type": mime,
                    "character_id": attachment.character_id,
                    "character_name": attachment.character_name,
                    "ref_set_id": attachment.ref_set_id,
                    "ref_set_version": attachment.ref_set_version,
                    "role": attachment.role,
                }
            )

        request = ProviderRequest(
            model=selected_model,
            prompt=assembled.text,
            references=tuple(provider_refs),
            aspect_ratio=scene_row["aspect_ratio"],
            image_size=selected_size,
            labels={"scene": str(scene_id)},
        )
        request_capture = {
            "schema_version": 1,
            "model": selected_model,
            "image_size": selected_size,
            "aspect_ratio": scene_row["aspect_ratio"],
            "response_format": {
                "type": "image",
                "aspect_ratio": scene_row["aspect_ratio"],
                "image_size": selected_size,
            },
            "prompt": assembled.text,
            "prompt_hash": assembled.prompt_hash,
            "cast": [
                {
                    "character_id": member.character_id,
                    "name": member.name,
                    "scene_role": member.scene_role,
                    "prominence": member.prominence,
                    "ref_set_id": member.ref_set_id,
                    "ref_set_version": member.ref_set_version,
                }
                for member in cast
            ],
            "attachments": attachment_capture,
            "warnings": list(assembled.warnings),
            "labels": {"scene": str(scene_id)},
            "store": False,
        }
        ledger = CostLedger(self.conn, self.settings)
        estimate = ledger.estimate(selected_model, selected_size)
        spent = ledger.spent_today()
        remaining = self.settings.daily_spend_cap_cents - spent - estimate
        if remaining < 0:
            from app.services.costs import BudgetExceededError

            raise BudgetExceededError(
                f"daily budget would be exceeded: {spent} cents spent/reserved, "
                f"{estimate} cents requested, "
                f"{self.settings.daily_spend_cap_cents} cents allowed"
            )
        return GenerationPreview(
            scene_id=scene_id,
            model=selected_model,
            image_size=selected_size,
            prompt=assembled.text,
            prompt_hash=assembled.prompt_hash,
            attachments=tuple(attachment_capture),
            warnings=assembled.warnings,
            estimated_cost_cents=estimate,
            spent_today_cents=spent,
            remaining_after_cents=remaining,
            provider_request=request,
            request_capture=request_capture,
        )

    def generate(
        self,
        scene_id: int,
        *,
        model: str | None = None,
        image_size: str | None = None,
        parent_generation_id: int | None = None,
    ) -> GenerationOutcome:
        if self.provider is None:
            raise GenerationError("generation provider is not configured")
        preview = self.preview(scene_id, model=model, image_size=image_size)
        ledger = CostLedger(self.conn, self.settings)
        generation_id, estimate = ledger.reserve(
            scene_id=scene_id,
            model=preview.model,
            image_size=preview.image_size,
            prompt_hash=preview.prompt_hash,
            request_json=preview.request_capture,
            parent_generation_id=parent_generation_id,
        )

        try:
            result = self.provider.generate(preview.provider_request)
            stored = self.storage.store(
                result.image_bytes, source_name=f"generation-{generation_id}.png"
            )
            provenance = {
                "schema_version": 1,
                "generation_id": generation_id,
                "scene_id": scene_id,
                "cast": preview.request_capture["cast"],
                "model": preview.model,
                "params": {
                    "image_size": preview.image_size,
                    "aspect_ratio": preview.provider_request.aspect_ratio,
                },
                "assembled_prompt": preview.prompt,
                "input_images": list(preview.attachments),
                "slot_allocation": list(preview.attachments),
                "prompt_hash": preview.prompt_hash,
                "interaction_id": result.interaction_id,
                "cost_cents": result.billed_cost_cents or estimate,
                "price_table_version": self.settings.price_table_version,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self.storage.append_provenance(stored.sha256, provenance)
            candidate_id = ledger.succeed(
                generation_id,
                interaction_id=result.interaction_id,
                response_json=result.response_metadata,
                candidate_sha256=stored.sha256,
                actual_cost_cents=result.billed_cost_cents,
            )
        except Exception as exc:
            ledger.fail(generation_id, str(exc))
            raise GenerationError(f"generation {generation_id} failed: {exc}") from exc

        return GenerationOutcome(
            generation_id,
            candidate_id,
            stored.sha256,
            preview.prompt_hash,
            result.billed_cost_cents or estimate,
            preview.warnings,
        )

    def _load_cast(self, cast_json: str) -> tuple[CastInput, ...]:
        try:
            raw_cast = json.loads(cast_json)
        except json.JSONDecodeError as exc:
            raise GenerationError(f"scene cast is not valid JSON: {exc}") from exc
        if not isinstance(raw_cast, list):
            raise GenerationError("scene cast must be an ordered list")

        characters = CharacterService(self.conn)
        ref_sets = RefSetService(self.conn, self.storage)
        result: list[CastInput] = []
        seen: set[int] = set()
        seen_names: set[str] = set()
        for entry in raw_cast:
            if not isinstance(entry, dict) or not isinstance(entry.get("character_id"), int):
                raise GenerationError("each cast entry must contain an integer character_id")
            character_id = entry["character_id"]
            if character_id in seen:
                raise GenerationError(f"character {character_id} appears twice in the cast")
            seen.add(character_id)
            payload = characters.model_payload(character_id)
            normalized_name = payload["name"].strip().casefold()
            if normalized_name in seen_names:
                raise GenerationError(
                    f"cast character name '{payload['name']}' is ambiguous; "
                    "use distinct character names"
                )
            seen_names.add(normalized_name)
            canonical = ref_sets.get_canonical(character_id)
            if canonical is None:
                raise GenerationError(
                    f"{payload['name']} has no canonical reference set"
                )
            refs = tuple(
                ReferenceInput(image.sha256, image.role, image.weight)
                for image in ref_sets.images(canonical.id)
            )
            prominence = entry.get("prominence", 1)
            if not isinstance(prominence, int) or prominence < 1:
                raise GenerationError("cast prominence must be a positive integer")
            result.append(
                CastInput(
                    character_id=character_id,
                    name=payload["name"],
                    visual_contract=payload["visual_contract"],
                    negative_traits=payload["negative_traits"],
                    ref_set_id=canonical.id,
                    ref_set_version=canonical.version,
                    references=refs,
                    scene_role=str(entry.get("role", "")),
                    prominence=prominence,
                )
            )
        return tuple(result)
