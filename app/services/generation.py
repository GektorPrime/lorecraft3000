"""End-to-end single-candidate generation orchestration."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from app.assembler.core import (
    AssemblyError,
    assemble_base_stage_prompt,
    assemble_prompt,
    assemble_staged_prompt,
)
from app.config import Settings
from app.domain.generation import CastInput, ReferenceInput, SceneInput
from app.providers.base import (
    ImageProvider,
    ProviderEditRequest,
    ProviderReference,
    ProviderRequest,
)
from app.services.base_stages import BaseStageError, BaseStageService
from app.services.characters import CharacterError, CharacterService
from app.services.costs import CostLedger
from app.services.identity import (
    get_embedder,
    load_gallery_for_attachments,
    score_generated_image,
)
from app.services.ref_sets import RefSetError, RefSetService
from app.services.styles import StyleError, StyleService
from app.storage import ImageStorage, ImageStorageError


class GenerationError(Exception):
    pass


class PreviewChangedError(GenerationError):
    """Raised when paid generation no longer matches the reviewed preview."""


class GenerationNotFoundError(GenerationError):
    """Raised when a generation id does not exist."""


@dataclass(frozen=True)
class GenerationOutcome:
    generation_id: int
    candidate_id: int | None
    candidate_sha256: str | None
    prompt_hash: str
    cost_cents: int
    warnings: tuple[str, ...]
    replayed: bool = False


class EditError(GenerationError):
    """Raised when a candidate edit cannot proceed."""


# Version of the request/provenance capture format. Every generate/edit path
# stamps this so historical captures can be interpreted reliably — readers use
# ``schema_version`` to know whether an ``operation``/``input_images`` key is
# guaranteed to be present, and existing records stay readable via the
# fallbacks (``.get("input_images", attachments)``).
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class GenerationPreview:
    """A no-spend preflight for one attempt owned by a panel or a Base Stage.

    Exactly one of ``scene_id``/``base_stage_id`` is set; the matching revision
    is what the ledger checks so a composition edited after preview cannot be
    generated from a stale prompt.
    """

    scene_id: int | None
    scene_revision: int
    model: str
    image_size: str
    prompt: str
    prompt_hash: str
    attachments: tuple[dict, ...]
    warnings: tuple[str, ...]
    estimated_cost_cents: int
    spent_today_cents: int
    remaining_after_cents: int
    provider_request: ProviderRequest | ProviderEditRequest
    request_capture: dict
    base_stage_id: int | None = None
    base_stage_revision: int = 0


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

    def _provider_for(self, model: str) -> ImageProvider:
        """Resolve the provider serving ``model``.

        The route injects a registry (exposing ``for_model``) so selection keys
        on the model string; tests inject a single provider used for every
        model. Both paths funnel through here.
        """
        if self.provider is None:
            raise GenerationError("generation provider is not configured")
        resolver = getattr(self.provider, "for_model", None)
        if callable(resolver):
            return resolver(model)
        return self.provider

    def preview(
        self,
        scene_id: int,
        *,
        model: str | None = None,
        image_size: str | None = None,
        check_budget: bool = True,
        tz_name: str | None = None,
    ) -> GenerationPreview:
        """Run the exact no-spend preflight used by generate()."""
        scene_row = self.conn.execute(
            "SELECT * FROM scene WHERE id = ?", (scene_id,)
        ).fetchone()
        if scene_row is None:
            raise GenerationError(f"scene {scene_id} not found")
        selected_model = model or scene_row["model"] or self.settings.default_model
        selected_size = image_size or scene_row["image_size"] or self.settings.default_image_size
        staged = scene_row["base_stage_id"] is not None
        if not staged and scene_row["style_id"] is None:
            raise GenerationError("scene has no style")

        try:
            cast = self._load_cast(scene_row["cast_json"])
            if staged:
                stages = BaseStageService(self.conn, self.storage)
                stage = stages.get(scene_row["base_stage_id"])
                source_sha256 = stages.content_sha(stage.id)
                raw_cast = json.loads(scene_row["cast_json"])
                target_rows = self.conn.execute(
                    "SELECT id, description FROM base_stage_target "
                    "WHERE base_stage_id = ?",
                    (stage.id,),
                ).fetchall()
                descriptions = {int(row["id"]): row["description"] for row in target_rows}
                target_map = {
                    int(entry["character_id"]): descriptions[
                        int(entry["base_stage_target_id"])
                    ]
                    for entry in raw_cast
                }
                target_ids = {
                    int(entry["character_id"]): int(entry["base_stage_target_id"])
                    for entry in raw_cast
                }
                style_contract = ""
                if stage.style_id is not None:
                    style_contract = StyleService(self.conn).get(stage.style_id).style_contract
                assembled = assemble_staged_prompt(
                    model=selected_model,
                    image_size=selected_size,
                    cast=cast,
                    base_stage_description=stage.description,
                    base_stage_sha256=source_sha256,
                    target_map=target_map,
                    target_ids=target_ids,
                    style_contract=style_contract,
                )
            else:
                style = StyleService(self.conn).get(scene_row["style_id"])
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
        except (AssemblyError, BaseStageError, CharacterError, RefSetError, StyleError, KeyError, TypeError, ValueError) as exc:
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

        source_capture = None
        if staged:
            try:
                source_data, source_metadata = self.storage.read(source_sha256)
            except ImageStorageError as exc:
                raise GenerationError(
                    f"base stage image {stage.id} is unavailable: {exc}"
                ) from exc
            source_mime = _FORMAT_MIME.get(source_metadata.get("format"))
            if source_mime is None:
                raise GenerationError(
                    f"unsupported stored base stage format: {source_metadata.get('format')}"
                )
            source_capture = {
                "image_number": 1,
                "kind": "base_stage",
                "base_stage_id": stage.id,
                "sha256": source_sha256,
                "mime_type": source_mime,
            }
            request = ProviderEditRequest(
                model=selected_model,
                prompt=assembled.text,
                instruction=(
                    "Replace each mapped figure's identity from its canonical "
                    "references while obeying every preservation constraint."
                ),
                source_image=source_data,
                source_mime_type=source_mime,
                references=tuple(provider_refs),
                aspect_ratio=scene_row["aspect_ratio"],
                image_size=selected_size,
                labels={"scene": str(scene_id)},
                source_interaction_id=None,
            )
        else:
            request = ProviderRequest(
                model=selected_model,
                prompt=assembled.text,
                references=tuple(provider_refs),
                aspect_ratio=scene_row["aspect_ratio"],
                image_size=selected_size,
                labels={"scene": str(scene_id)},
            )
        request_capture = {
            "schema_version": SCHEMA_VERSION,
            "operation": "direct_panel_generate",
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
            "input_images": list(attachment_capture),
            "warnings": list(assembled.warnings),
            "labels": {"scene": str(scene_id)},
            "store": False,
            "scene_revision": scene_row["revision"],
        }
        if staged:
            request_capture.update(
                {
                    "operation": "base_stage_panel_generate",
                    "kind": "base_stage_panel_generate",
                    "base_stage": {
                        "id": stage.id,
                        "origin": stage.origin,
                        "description": stage.description,
                        "content_sha256": source_sha256,
                        "aspect_ratio": stage.aspect_ratio,
                        "style_id": stage.style_id,
                    },
                    "target_map": [
                        {
                            "character_id": member.character_id,
                            "character_name": member.name,
                            "base_stage_target_id": raw["base_stage_target_id"],
                            "target_description": target_map[member.character_id],
                        }
                        for member, raw in zip(cast, raw_cast)
                    ],
                    "character_attachments": attachment_capture,
                    "input_images": [source_capture, *attachment_capture],
                }
            )
        ledger = CostLedger(self.conn, self.settings)
        estimate = ledger.estimate(selected_model, selected_size)
        # The hard budget gate is enforced on the UTC boundary (machine
        # independent). The figure surfaced to the UI uses the caller's browser
        # timezone so the dashboard matches what the user sees.
        spent = ledger.spent_today()
        spent_display = ledger.spent_today(tz_name)
        remaining = self.settings.daily_spend_cap_cents - spent - estimate
        if check_budget and remaining < 0:
            from app.services.costs import BudgetExceededError

            raise BudgetExceededError(
                f"daily budget would be exceeded: {spent} cents spent/reserved, "
                f"{estimate} cents requested, "
                f"{self.settings.daily_spend_cap_cents} cents allowed"
            )
        return GenerationPreview(
            scene_id=scene_id,
            scene_revision=scene_row["revision"],
            model=selected_model,
            image_size=selected_size,
            prompt=assembled.text,
            prompt_hash=assembled.prompt_hash,
            attachments=tuple(attachment_capture),
            warnings=assembled.warnings,
            estimated_cost_cents=estimate,
            spent_today_cents=spent_display,
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
        idempotency_key: str | None = None,
        expected_prompt_hash: str | None = None,
    ) -> GenerationOutcome:
        preview = self.preview(
            scene_id, model=model, image_size=image_size, check_budget=False
        )
        return self._execute(
            preview,
            parent_generation_id=parent_generation_id,
            idempotency_key=idempotency_key,
            expected_prompt_hash=expected_prompt_hash,
        )

    def _execute(
        self,
        preview: GenerationPreview,
        *,
        parent_generation_id: int | None = None,
        idempotency_key: str | None = None,
        expected_prompt_hash: str | None = None,
    ) -> GenerationOutcome:
        """Run one reviewed preview as a single paid attempt.

        Shared by panel and Base Stage generation so both owners get identical
        drift protection, reservation, provenance, and failure accounting.
        """
        scene_id = preview.scene_id
        provider = self._provider_for(preview.model)
        if (
            expected_prompt_hash is not None
            and preview.prompt_hash != expected_prompt_hash
        ):
            raise PreviewChangedError(
                "the assembled prompt changed after preview; review the updated prompt before generating"
            )
        ledger = CostLedger(self.conn, self.settings)
        reservation = ledger.reserve(
            scene_id=scene_id,
            base_stage_id=preview.base_stage_id,
            model=preview.model,
            image_size=preview.image_size,
            prompt_hash=preview.prompt_hash,
            request_json=preview.request_capture,
            parent_generation_id=parent_generation_id,
            idempotency_key=idempotency_key,
            scene_revision=preview.scene_revision if scene_id is not None else None,
            base_stage_revision=(
                preview.base_stage_revision if preview.base_stage_id is not None else None
            ),
        )
        generation_id, estimate = reservation

        if not reservation.created:
            return self._replayed_outcome(generation_id)

        result = None
        try:
            if isinstance(preview.provider_request, ProviderEditRequest):
                result = provider.edit(preview.provider_request)
            else:
                result = provider.generate(preview.provider_request)
            stored = self.storage.store(
                result.image_bytes, source_name=f"generation-{generation_id}.png"
            )
            provenance = {
                "schema_version": SCHEMA_VERSION,
                "operation": preview.request_capture.get("operation", "direct_panel_generate"),
                "generation_id": generation_id,
                "scene_id": scene_id,
                "base_stage_id": preview.base_stage_id,
                "cast": preview.request_capture["cast"],
                "model": preview.model,
                "params": {
                    "image_size": preview.image_size,
                    "aspect_ratio": preview.provider_request.aspect_ratio,
                },
                "assembled_prompt": preview.prompt,
                "input_images": list(
                    preview.request_capture.get("input_images", preview.attachments)
                ),
                "slot_allocation": list(preview.attachments),
                "prompt_hash": preview.prompt_hash,
                "interaction_id": result.interaction_id,
                "cost_cents": (
                    result.billed_cost_cents
                    if result.billed_cost_cents is not None
                    else estimate
                ),
                "price_table_version": self.settings.price_table_version,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            candidate_id = ledger.succeed(
                generation_id,
                interaction_id=result.interaction_id,
                response_json=result.response_metadata,
                candidate_sha256=stored.sha256,
                actual_cost_cents=result.billed_cost_cents,
                provenance_record={
                    "prompt_hash": preview.prompt_hash,
                    "price_table_version": self.settings.price_table_version,
                    "input_images": list(
                        preview.request_capture.get("input_images", preview.attachments)
                    ),
                },
            )
            # The authoritative provenance record is committed to
            # image_provenance above, in the same transaction as the candidate.
            # The sidecar is a best-effort mirror; its failure must never turn a
            # successful generation into a failed one.
            try:
                self.storage.append_provenance(stored.sha256, provenance)
            except Exception:
                pass
            # Identity scoring is advisory and equally non-fatal: a face-check
            # failure (or missing insightface) must never fail a paid
            # generation. The cast ids and reference attachments come from the
            # same request_capture that was assembled and reviewed for this
            # generation. Scoring resolves the reference embeddings captured in
            # ``input_images`` rather than the currently-canonical sets, so a
            # generation is compared against the faces it was truly made from.
            try:
                self._score_candidate(
                    candidate_id,
                    stored.sha256,
                    cast_ids=tuple(
                        int(entry["character_id"])
                        for entry in preview.request_capture.get("cast", [])
                        if isinstance(entry, dict)
                        and isinstance(entry.get("character_id"), int)
                    ),
                    attachments=preview.request_capture.get(
                        "input_images", preview.attachments
                    ),
                )
            except Exception:
                pass
        except Exception as exc:
            ledger.fail(
                generation_id,
                str(exc),
                charge_expected=getattr(exc, "charge_expected", True),
                actual_cost_cents=(
                    result.billed_cost_cents if result is not None else None
                ),
            )
            raise GenerationError(f"generation {generation_id} failed: {exc}") from exc

        generation_row = self.conn.execute(
            "SELECT warning_text FROM generation WHERE id = ?", (generation_id,)
        ).fetchone()
        warnings = preview.warnings
        if generation_row["warning_text"]:
            warnings = (*warnings, generation_row["warning_text"])
        return GenerationOutcome(
            generation_id,
            candidate_id,
            stored.sha256,
            preview.prompt_hash,
            (
                result.billed_cost_cents
                if result.billed_cost_cents is not None
                else estimate
            ),
            warnings,
        )

    def preview_base_stage(
        self,
        base_stage_id: int,
        *,
        check_budget: bool = True,
        tz_name: str | None = None,
    ) -> GenerationPreview:
        """Exact no-spend preflight for an identity-neutral Base Stage draft.

        A Base Stage has no cast, so no canonical references are attached and
        the request goes through the plain text-to-image path. Identities are
        applied later, when a panel uses the published image as its source.
        """
        stages = BaseStageService(self.conn, self.storage, self.settings)
        stage = stages.get(base_stage_id)
        if stage.origin != "generated":
            raise GenerationError(
                f"base stage {base_stage_id} was uploaded and is not generated"
            )
        if stage.state != "draft":
            raise GenerationError(
                f"base stage {base_stage_id} is already published"
            )
        if stage.model is None or stage.image_size is None or stage.style_id is None:
            raise GenerationError(
                f"base stage {base_stage_id} is missing generation settings"
            )
        try:
            style = StyleService(self.conn).get(stage.style_id)
            assembled = assemble_base_stage_prompt(
                model=stage.model,
                image_size=stage.image_size,
                description=stage.description,
                beat_text=stage.beat_text or "",
                camera=stage.camera or "",
                framing=stage.framing or "",
                mood=stage.mood or "",
                targets=tuple(target.description for target in stage.targets),
                style_contract=style.style_contract,
            )
        except (AssemblyError, StyleError, ValueError) as exc:
            raise GenerationError(f"base stage cannot be generated: {exc}") from exc

        request = ProviderRequest(
            model=stage.model,
            prompt=assembled.text,
            references=(),
            aspect_ratio=stage.aspect_ratio,
            image_size=stage.image_size,
            labels={"base_stage": str(stage.id)},
        )
        request_capture = {
            "schema_version": SCHEMA_VERSION,
            "operation": "base_stage_generate",
            "kind": "base_stage_generate",
            "model": stage.model,
            "image_size": stage.image_size,
            "aspect_ratio": stage.aspect_ratio,
            "response_format": {
                "type": "image",
                "aspect_ratio": stage.aspect_ratio,
                "image_size": stage.image_size,
            },
            "prompt": assembled.text,
            "prompt_hash": assembled.prompt_hash,
            # No cast: identity is applied later by a panel, so nothing here is
            # identity-bearing and the candidate is never identity-scored.
            "cast": [],
            "attachments": [],
            "input_images": [],
            "base_stage": {
                "id": stage.id,
                "origin": stage.origin,
                "description": stage.description,
                "aspect_ratio": stage.aspect_ratio,
                "style_id": stage.style_id,
                "targets": [
                    {"id": target.id, "position": target.position,
                     "description": target.description}
                    for target in stage.targets
                ],
            },
            "warnings": list(assembled.warnings),
            "labels": {"base_stage": str(stage.id)},
            "store": False,
            "base_stage_revision": stage.revision,
        }

        ledger = CostLedger(self.conn, self.settings)
        estimate = ledger.estimate(stage.model, stage.image_size)
        spent = ledger.spent_today()
        spent_display = ledger.spent_today(tz_name)
        remaining = self.settings.daily_spend_cap_cents - spent - estimate
        if check_budget and remaining < 0:
            from app.services.costs import BudgetExceededError

            raise BudgetExceededError(
                f"daily budget would be exceeded: {spent} cents spent/reserved, "
                f"{estimate} cents requested, "
                f"{self.settings.daily_spend_cap_cents} cents allowed"
            )
        return GenerationPreview(
            scene_id=None,
            scene_revision=0,
            base_stage_id=stage.id,
            base_stage_revision=stage.revision,
            model=stage.model,
            image_size=stage.image_size,
            prompt=assembled.text,
            prompt_hash=assembled.prompt_hash,
            attachments=(),
            warnings=assembled.warnings,
            estimated_cost_cents=estimate,
            spent_today_cents=spent_display,
            remaining_after_cents=remaining,
            provider_request=request,
            request_capture=request_capture,
        )

    def generate_base_stage(
        self,
        base_stage_id: int,
        *,
        idempotency_key: str | None = None,
        expected_prompt_hash: str | None = None,
    ) -> GenerationOutcome:
        preview = self.preview_base_stage(base_stage_id, check_budget=False)
        return self._execute(
            preview,
            idempotency_key=idempotency_key,
            expected_prompt_hash=expected_prompt_hash,
        )

    def edit_candidate(
        self,
        candidate_id: int,
        instruction: str,
        *,
        idempotency_key: str | None = None,
    ) -> GenerationOutcome:
        """Produce a new candidate by editing an existing one in place.

        The edit runs on the same provider/model that produced the source image
        and stays anchored to the panel's canonical character references. The
        new attempt is a child generation (``parent_generation_id`` points at
        the source's generation), so provenance and the panel's attempt history
        remain a connected chain. Cost is reserved and billed exactly like a
        fresh generation, under the same daily budget gate.
        """
        instruction = (instruction or "").strip()
        if not instruction:
            raise EditError("an edit instruction is required")

        source = self.conn.execute(
            """
            SELECT c.id AS candidate_id, c.sha256 AS sha256,
                   g.id AS generation_id, g.scene_id AS scene_id,
                   g.model AS model, g.state AS state,
                   g.request_json AS request_json, g.prompt_hash AS prompt_hash,
                   g.interaction_id AS interaction_id
              FROM candidate c
              JOIN generation g ON g.id = c.generation_id
             WHERE c.id = ?
            """,
            (candidate_id,),
        ).fetchone()
        if source is None:
            raise GenerationNotFoundError(f"candidate {candidate_id} not found")
        if source["state"] != "succeeded":
            raise EditError("only a successful candidate can be edited")

        scene_id = source["scene_id"]
        if scene_id is None:
            raise EditError("candidate has no panel to edit against")
        capture = json.loads(source["request_json"] or "{}")
        model = source["model"]
        image_size = capture.get("image_size") or self.settings.default_image_size
        aspect_ratio = capture.get("aspect_ratio") or "3:2"
        base_prompt = capture.get("prompt", "")

        try:
            source_bytes, source_meta = self.storage.read(source["sha256"])
        except ImageStorageError as exc:
            raise EditError(
                f"source image {source['sha256']} is unavailable: {exc}"
            ) from exc
        source_mime = _FORMAT_MIME.get(source_meta.get("format"), "image/png")

        provider = self._provider_for(model)

        # Rebuild the canonical character references captured on the source
        # generation so identity stays anchored across the edit.
        provider_refs: list[ProviderReference] = []
        attachment_capture: list[dict] = []
        for attachment in capture.get("attachments", []):
            try:
                data, metadata = self.storage.read(attachment["sha256"])
            except ImageStorageError as exc:
                raise EditError(
                    f"reference image {attachment['sha256']} is unavailable: {exc}"
                ) from exc
            mime = _FORMAT_MIME.get(metadata.get("format"), "image/png")
            provider_refs.append(
                ProviderReference(
                    attachment["image_number"], attachment["sha256"], mime, data
                )
            )
            attachment_capture.append(dict(attachment))

        # A distinct hash for the edit keeps idempotent replay working: the same
        # source candidate + instruction replays the same attempt, while a
        # different instruction is a new attempt.
        edit_prompt_hash = hashlib.sha256(
            json.dumps(
                {
                    "source_prompt_hash": source["prompt_hash"],
                    "source_candidate_id": candidate_id,
                    "instruction": instruction,
                    "model": model,
                    "image_size": image_size,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

        edit_request = ProviderEditRequest(
            model=model,
            prompt=base_prompt,
            instruction=instruction,
            source_image=source_bytes,
            source_mime_type=source_mime,
            references=tuple(provider_refs),
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            labels={"scene": str(scene_id)},
            source_interaction_id=source["interaction_id"],
        )

        source_capture = {
            "image_number": 1,
            "kind": "candidate_source",
            "candidate_id": candidate_id,
            "source_candidate_id": candidate_id,
            "generation_id": source["generation_id"],
            "sha256": source["sha256"],
            "mime_type": source_mime,
        }

        request_capture = {
            "schema_version": SCHEMA_VERSION,
            "operation": "candidate_edit",
            "kind": "edit",
            "model": model,
            "image_size": image_size,
            "aspect_ratio": aspect_ratio,
            "prompt": base_prompt,
            "prompt_hash": edit_prompt_hash,
            "edit_instruction": instruction,
            "source_candidate_id": candidate_id,
            "source_generation_id": source["generation_id"],
            "cast": capture.get("cast", []),
            "attachments": attachment_capture,
            "input_images": [source_capture, *attachment_capture],
            "warnings": [],
            "labels": {"scene": str(scene_id)},
            "store": False,
        }

        ledger = CostLedger(self.conn, self.settings)
        reservation = ledger.reserve(
            scene_id=scene_id,
            model=model,
            image_size=image_size,
            prompt_hash=edit_prompt_hash,
            request_json=request_capture,
            parent_generation_id=source["generation_id"],
            idempotency_key=idempotency_key,
        )
        generation_id, estimate = reservation
        if not reservation.created:
            return self._replayed_outcome(generation_id)

        result = None
        try:
            result = provider.edit(edit_request)
            stored = self.storage.store(
                result.image_bytes, source_name=f"generation-{generation_id}.png"
            )
            provenance = {
                "schema_version": SCHEMA_VERSION,
                "kind": "edit",
                "operation": "candidate_edit",
                "generation_id": generation_id,
                "scene_id": scene_id,
                "source_candidate_id": candidate_id,
                "source_generation_id": source["generation_id"],
                "cast": capture.get("cast", []),
                "model": model,
                "params": {"image_size": image_size, "aspect_ratio": aspect_ratio},
                "assembled_prompt": base_prompt,
                "edit_instruction": instruction,
                "input_images": [source_capture, *attachment_capture],
                "prompt_hash": edit_prompt_hash,
                "interaction_id": result.interaction_id,
                "cost_cents": (
                    result.billed_cost_cents
                    if result.billed_cost_cents is not None
                    else estimate
                ),
                "price_table_version": self.settings.price_table_version,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            candidate_new_id = ledger.succeed(
                generation_id,
                interaction_id=result.interaction_id,
                response_json=result.response_metadata,
                candidate_sha256=stored.sha256,
                actual_cost_cents=result.billed_cost_cents,
                provenance_record={
                    "prompt_hash": edit_prompt_hash,
                    "price_table_version": self.settings.price_table_version,
                    "input_images": [source_capture, *attachment_capture],
                },
            )
            try:
                self.storage.append_provenance(stored.sha256, provenance)
            except Exception:
                pass
            # Identity scoring is advisory and equally non-fatal: a face-check
            # failure (or missing insightface) must never fail a paid
            # generation. The cast ids and reference attachments come from the
            # captured source generation the edit is anchored to.
            try:
                self._score_candidate(
                    candidate_new_id,
                    stored.sha256,
                    cast_ids=tuple(
                        int(entry["character_id"])
                        for entry in capture.get("cast", [])
                        if isinstance(entry, dict)
                        and isinstance(entry.get("character_id"), int)
                    ),
                    attachments=attachment_capture,
                )
            except Exception:
                pass
        except Exception as exc:
            ledger.fail(
                generation_id,
                str(exc),
                charge_expected=getattr(exc, "charge_expected", True),
                actual_cost_cents=(
                    result.billed_cost_cents if result is not None else None
                ),
            )
            raise EditError(f"edit {generation_id} failed: {exc}") from exc

        generation_row = self.conn.execute(
            "SELECT warning_text FROM generation WHERE id = ?", (generation_id,)
        ).fetchone()
        warnings: tuple[str, ...] = ()
        if generation_row["warning_text"]:
            warnings = (generation_row["warning_text"],)
        return GenerationOutcome(
            generation_id,
            candidate_new_id,
            stored.sha256,
            edit_prompt_hash,
            (
                result.billed_cost_cents
                if result.billed_cost_cents is not None
                else estimate
            ),
            warnings,
        )

    def _score_candidate(
        self,
        candidate_id: int,
        sha256: str,
        *,
        cast_ids: tuple[int, ...],
        attachments: list[dict] | tuple[dict, ...],
    ) -> None:
        """Advisory identity scoring shared by every candidate path.

        Used by direct panel generation, Base Stage panel generation, and
        candidate edits so all three produce ``candidate.identity_scores``
        through the same code path. The gallery is resolved from the reference
        images actually captured for the request (``attachments`` carrying
        ``character_id`` + ``sha256``) rather than the currently-canonical
        reference sets, so a candidate is compared against the faces it was
        really made from — including versions of a reference set that have
        since been retired.

        A missing embedder, a hash with no stored embedding, or a face-check
        failure all leave the candidate unscored; none may fail a paid
        generation, so this never raises.
        """
        if not cast_ids:
            return
        embedder = get_embedder()
        if embedder is None:
            return
        data, _ = self.storage.read(sha256)
        gallery = load_gallery_for_attachments(self.conn, attachments)
        if not gallery:
            return
        payload = score_generated_image(embedder, gallery, data, cast_ids)
        if payload is not None:
            with self.conn:
                self.conn.execute(
                    "UPDATE candidate SET identity_scores = ? WHERE id = ?",
                    (json.dumps(payload, sort_keys=True), candidate_id),
                )

    def list_for_scene(self, scene_id: int) -> list[sqlite3.Row]:
        """All generation rows for a panel, newest first."""
        return self.conn.execute(
            "SELECT * FROM generation WHERE scene_id = ? ORDER BY id DESC",
            (scene_id,),
        ).fetchall()

    def list_for_scene_with_candidates(
        self, scene_id: int
    ) -> list[tuple[sqlite3.Row, list[sqlite3.Row]]]:
        """Every generation for a panel, newest first, each paired with its
        candidate rows so callers can render previews and review status for all
        attempts without an N+1 query."""
        rows = self.conn.execute(
            "SELECT * FROM generation WHERE scene_id = ? ORDER BY id DESC",
            (scene_id,),
        ).fetchall()
        if not rows:
            return []
        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        candidate_rows = self.conn.execute(
            f"SELECT * FROM candidate WHERE generation_id IN ({placeholders}) ORDER BY generation_id, idx",
            ids,
        ).fetchall()
        grouped: dict[int, list[sqlite3.Row]] = {generation_id: [] for generation_id in ids}
        for candidate in candidate_rows:
            grouped.setdefault(candidate["generation_id"], []).append(candidate)
        return [(row, grouped[row["id"]]) for row in rows]

    def list_for_base_stage_with_candidates(
        self, base_stage_id: int
    ) -> list[tuple[sqlite3.Row, list[sqlite3.Row]]]:
        """Every attempt for a Base Stage, newest first, with its candidates."""
        rows = self.conn.execute(
            "SELECT * FROM generation WHERE base_stage_id = ? ORDER BY id DESC",
            (base_stage_id,),
        ).fetchall()
        if not rows:
            return []
        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        candidate_rows = self.conn.execute(
            f"SELECT * FROM candidate WHERE generation_id IN ({placeholders}) "
            "ORDER BY generation_id, idx",
            ids,
        ).fetchall()
        grouped: dict[int, list[sqlite3.Row]] = {
            generation_id: [] for generation_id in ids
        }
        for candidate in candidate_rows:
            grouped.setdefault(candidate["generation_id"], []).append(candidate)
        return [(row, grouped[row["id"]]) for row in rows]

    def get_with_candidates(self, generation_id: int) -> tuple[sqlite3.Row, list[sqlite3.Row]]:
        """A generation row and its candidates, or GenerationNotFoundError."""
        row = self.conn.execute(
            "SELECT * FROM generation WHERE id = ?", (generation_id,)
        ).fetchone()
        if row is None:
            raise GenerationNotFoundError(f"generation {generation_id} not found")
        candidates = self.conn.execute(
            "SELECT * FROM candidate WHERE generation_id = ? ORDER BY idx",
            (generation_id,),
        ).fetchall()
        return row, candidates

    def _replayed_outcome(self, generation_id: int) -> GenerationOutcome:
        row = self.conn.execute(
            "SELECT * FROM generation WHERE id = ?", (generation_id,)
        ).fetchone()
        candidate = self.conn.execute(
            "SELECT id, sha256 FROM candidate WHERE generation_id = ? ORDER BY idx LIMIT 1",
            (generation_id,),
        ).fetchone()
        request_data = json.loads(row["request_json"] or "{}")
        warnings = tuple(request_data.get("warnings", []))
        if row["warning_text"]:
            warnings = (*warnings, row["warning_text"])
        return GenerationOutcome(
            generation_id=generation_id,
            candidate_id=int(candidate["id"]) if candidate else None,
            candidate_sha256=candidate["sha256"] if candidate else None,
            prompt_hash=row["prompt_hash"],
            cost_cents=row["cost_usd_cents"],
            warnings=warnings,
            replayed=True,
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
