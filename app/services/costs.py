"""Transactional daily cost guard and generation ledger."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import Settings


class CostError(Exception):
    pass


class BudgetExceededError(CostError):
    pass


class UnknownPriceError(CostError):
    pass


class GenerationPendingError(CostError):
    pass


class IdempotencyConflictError(CostError):
    pass


class SceneChangedError(CostError):
    pass


class BaseStageChangedError(CostError):
    pass


@dataclass(frozen=True)
class Reservation:
    generation_id: int
    reserved_cost_cents: int
    created: bool

    def __iter__(self):
        """Keep the existing two-value unpacking API compatible."""
        yield self.generation_id
        yield self.reserved_cost_cents


class CostLedger:
    def __init__(self, conn: sqlite3.Connection, settings: Settings) -> None:
        self.conn = conn
        self.settings = settings

    def estimate(self, model: str, image_size: str) -> int:
        try:
            cents = self.settings.model_prices_cents[model][image_size]
        except KeyError as exc:
            raise UnknownPriceError(
                f"no configured price for {model} at {image_size}"
            ) from exc
        if cents <= 0:
            raise UnknownPriceError(
                f"price for {model} at {image_size} is not verified"
            )
        return cents

    @staticmethod
    def _tz(tz_name: str | None) -> object:
        """Resolve an IANA timezone name, defaulting to UTC.

        Conversions to a user's local calendar day always happen in the browser
        timezone supplied via the request header. When none is available (server
        calls such as budget gating during generation, or tests), UTC is used so
        behaviour never depends on the server's own system timezone.
        """
        if tz_name:
            try:
                return ZoneInfo(tz_name)
            except ZoneInfoNotFoundError:
                return timezone.utc
        return timezone.utc

    @staticmethod
    def _local_date(utc_timestamp: str, tz_name: str | None = None) -> str:
        """Convert a UTC timestamp to YYYY-MM-DD in the given timezone (UTC default)."""
        dt = datetime.strptime(utc_timestamp, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        return dt.astimezone(CostLedger._tz(tz_name)).strftime("%Y-%m-%d")

    def spent_today(self, tz_name: str | None = None) -> int:
        today = self._local_date(
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), tz_name
        )
        rows = self.conn.execute(
            """
            SELECT COALESCE(actual_cost_usd_cents, reserved_cost_usd_cents) AS cost,
                   created_at
              FROM generation
             WHERE cost IS NOT NULL AND cost != 0
            """
        ).fetchall()
        return sum(
            int(row["cost"])
            for row in rows
            if self._local_date(row["created_at"], tz_name) == today
        )

    def reserve(
        self,
        *,
        scene_id: int | None = None,
        base_stage_id: int | None = None,
        model: str,
        image_size: str,
        prompt_hash: str,
        request_json: dict,
        parent_generation_id: int | None = None,
        idempotency_key: str | None = None,
        scene_revision: int | None = None,
        base_stage_revision: int | None = None,
    ) -> Reservation:
        """Reserve budget for one attempt owned by a scene or a Base Stage.

        Exactly one of ``scene_id``/``base_stage_id`` identifies the owner; the
        database enforces the same rule (017_base_stage_generations). Every
        owner-scoped rule below — idempotent replay, stale-preview detection,
        and the single in-flight attempt — is applied against that owner only.
        """
        if (scene_id is None) == (base_stage_id is None):
            raise CostError(
                "a generation must belong to exactly one scene or base stage"
            )
        owner_column = "scene_id" if scene_id is not None else "base_stage_id"
        owner_id = scene_id if scene_id is not None else base_stage_id
        owner_label = "scene" if scene_id is not None else "base stage"
        revision = scene_revision if scene_id is not None else base_stage_revision
        revision_column = "scene_revision" if scene_id is not None else "base_stage_revision"
        owner_table = "scene" if scene_id is not None else "base_stage"
        changed_error = (
            SceneChangedError if scene_id is not None else BaseStageChangedError
        )

        estimate = self.estimate(model, image_size)
        normalized_key = idempotency_key.strip() if idempotency_key else None
        if normalized_key is not None and len(normalized_key) > 200:
            raise IdempotencyConflictError("idempotency key is too long")
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self._recover_stale_pending()

            if normalized_key is not None:
                existing = self.conn.execute(
                    f"""
                    SELECT * FROM generation
                     WHERE {owner_column} = ? AND idempotency_key = ?
                    """,
                    (owner_id, normalized_key),
                ).fetchone()
                if existing is not None:
                    params = json.loads(existing["params_json"] or "{}")
                    if (
                        existing["model"] != model
                        or existing["prompt_hash"] != prompt_hash
                        or params.get("image_size") != image_size
                        or (
                            revision is not None
                            and existing[revision_column] != revision
                        )
                    ):
                        raise IdempotencyConflictError(
                            "idempotency key was already used for a different request"
                        )
                    self.conn.commit()
                    return Reservation(
                        int(existing["id"]),
                        int(existing["reserved_cost_usd_cents"]),
                        False,
                    )

            if revision is not None:
                owner = self.conn.execute(
                    f"SELECT revision FROM {owner_table} WHERE id = ?", (owner_id,)
                ).fetchone()
                if owner is None or int(owner["revision"]) != revision:
                    raise changed_error(
                        f"{owner_label} changed after preview; "
                        "preview it again before generating"
                    )

            pending = self.conn.execute(
                f"SELECT id FROM generation WHERE {owner_column} = ? AND state = 'pending'",
                (owner_id,),
            ).fetchone()
            if pending is not None:
                raise GenerationPendingError(
                    f"{owner_label} {owner_id} already has a generation in progress"
                )

            spent = self.spent_today()
            if spent + estimate > self.settings.daily_spend_cap_cents:
                raise BudgetExceededError(
                    f"daily budget would be exceeded: {spent} cents spent/reserved, "
                    f"{estimate} cents requested, "
                    f"{self.settings.daily_spend_cap_cents} cents allowed"
                )
            cursor = self.conn.execute(
                """
                INSERT INTO generation
                    (scene_id, base_stage_id, model, params_json, prompt_hash,
                     request_json, cost_usd_cents, reserved_cost_usd_cents,
                     parent_generation_id, state, price_table_version,
                     idempotency_key, scene_revision, base_stage_revision)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (
                    scene_id,
                    base_stage_id,
                    model,
                    json.dumps(
                        {
                            "image_size": image_size,
                            "aspect_ratio": request_json.get("aspect_ratio"),
                        },
                        sort_keys=True,
                    ),
                    prompt_hash,
                    json.dumps(request_json, sort_keys=True),
                    estimate,
                    estimate,
                    parent_generation_id,
                    self.settings.price_table_version,
                    normalized_key,
                    scene_revision or 0,
                    base_stage_revision or 0,
                ),
            )
            self.conn.commit()
            return Reservation(int(cursor.lastrowid), estimate, True)
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            if f"generation.{owner_column}" in str(exc):
                raise GenerationPendingError(
                    f"{owner_label} {owner_id} already has a generation in progress"
                ) from exc
            raise
        except Exception:
            self.conn.rollback()
            raise

    def succeed(
        self,
        generation_id: int,
        *,
        interaction_id: str | None,
        response_json: dict,
        candidate_sha256: str,
        actual_cost_cents: int | None = None,
        provenance_record: dict | None = None,
    ) -> int:
        with self.conn:
            row = self.conn.execute(
                "SELECT * FROM generation WHERE id = ? AND state = 'pending'",
                (generation_id,),
            ).fetchone()
            if row is None:
                raise CostError(
                    f"generation {generation_id} is not pending and cannot succeed"
                )
            effective_cost = (
                actual_cost_cents
                if actual_cost_cents is not None
                else int(row["reserved_cost_usd_cents"])
            )
            over_cap = (
                self.spent_today()
                - int(row["reserved_cost_usd_cents"])
                + effective_cost
                > self.settings.daily_spend_cap_cents
            )
            warning = None
            if over_cap:
                warning = (
                    "Provider-reported actual cost exceeded the reserved daily budget. "
                    "The charge is recorded and further generation is blocked."
                )
            updated = self.conn.execute(
                """
                UPDATE generation
                   SET state = 'succeeded', interaction_id = ?, response_json = ?,
                       completed_at = datetime('now'), cost_usd_cents = ?,
                       actual_cost_usd_cents = ?, warning_text = ?
                 WHERE id = ? AND state = 'pending'
                """,
                (
                    interaction_id,
                    json.dumps(response_json, sort_keys=True),
                    effective_cost,
                    actual_cost_cents,
                    warning,
                    generation_id,
                ),
            )
            if updated.rowcount != 1:
                raise CostError(
                    f"generation {generation_id} is not pending and cannot succeed"
                )
            cursor = self.conn.execute(
                "INSERT INTO candidate (generation_id, sha256, idx) VALUES (?, ?, 0)",
                (generation_id, candidate_sha256),
            )
            if provenance_record is not None:
                self.conn.execute(
                    """
                    INSERT INTO image_provenance
                        (sha256, generation_id, interaction_id, prompt_hash,
                         cost_cents, price_table_version, input_images)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_sha256,
                        generation_id,
                        interaction_id,
                        provenance_record["prompt_hash"],
                        effective_cost,
                        provenance_record["price_table_version"],
                        json.dumps(
                            provenance_record["input_images"], sort_keys=True
                        ),
                    ),
                )
        return int(cursor.lastrowid)

    def fail(
        self,
        generation_id: int,
        error: str,
        *,
        charge_expected: bool = True,
        actual_cost_cents: int | None = None,
    ) -> None:
        """Reconcile a failure, retaining cost unless it is known non-billable."""
        with self.conn:
            updated = self.conn.execute(
                """
                UPDATE generation
                   SET state = 'failed', error_text = ?,
                       cost_usd_cents = CASE
                           WHEN ? IS NOT NULL THEN ?
                           WHEN ? THEN reserved_cost_usd_cents ELSE 0
                       END,
                       actual_cost_usd_cents = CASE
                           WHEN ? IS NOT NULL THEN ?
                           WHEN ? THEN NULL ELSE 0
                       END,
                       completed_at = datetime('now')
                 WHERE id = ? AND state = 'pending'
                """,
                (
                    error,
                    actual_cost_cents,
                    actual_cost_cents,
                    charge_expected,
                    actual_cost_cents,
                    actual_cost_cents,
                    charge_expected,
                    generation_id,
                ),
            )
            if updated.rowcount != 1:
                raise CostError(
                    f"generation {generation_id} is not pending and cannot fail"
                )

    def recover_stale_pending(self) -> int:
        """Release scene locks left by interrupted calls, retaining reserved cost."""
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            recovered = self._recover_stale_pending()
            self.conn.commit()
            return recovered
        except Exception:
            self.conn.rollback()
            raise

    def _recover_stale_pending(self) -> int:
        cursor = self.conn.execute(
            """
            UPDATE generation
               SET state = 'failed',
                   error_text = 'Recovered stale pending generation after an interrupted request; reserved cost retained because billing is unknown.',
                   completed_at = datetime('now')
             WHERE state = 'pending'
               AND created_at <= datetime('now', ?)
            """,
            (f"-{self.settings.pending_stale_seconds} seconds",),
        )
        return cursor.rowcount
