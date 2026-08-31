"""Transactional daily cost guard and generation ledger."""

from __future__ import annotations

import json
import sqlite3

from app.config import Settings


class CostError(Exception):
    pass


class BudgetExceededError(CostError):
    pass


class UnknownPriceError(CostError):
    pass


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

    def spent_today(self) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(cost_usd_cents), 0) AS spent
              FROM generation
             WHERE date(created_at) = date('now')
            """
        ).fetchone()
        return int(row["spent"])

    def reserve(
        self,
        *,
        scene_id: int,
        model: str,
        image_size: str,
        prompt_hash: str,
        request_json: dict,
        parent_generation_id: int | None = None,
    ) -> tuple[int, int]:
        estimate = self.estimate(model, image_size)
        try:
            self.conn.execute("BEGIN IMMEDIATE")
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
                    (scene_id, model, params_json, prompt_hash, request_json,
                     cost_usd_cents, parent_generation_id, state,
                     price_table_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    scene_id,
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
                    parent_generation_id,
                    self.settings.price_table_version,
                ),
            )
            self.conn.commit()
            return int(cursor.lastrowid), estimate
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
    ) -> int:
        with self.conn:
            if actual_cost_cents is not None:
                self.conn.execute(
                    "UPDATE generation SET cost_usd_cents = ? WHERE id = ?",
                    (actual_cost_cents, generation_id),
                )
            updated = self.conn.execute(
                """
                UPDATE generation
                   SET state = 'succeeded', interaction_id = ?, response_json = ?,
                       completed_at = datetime('now')
                 WHERE id = ? AND state = 'pending'
                """,
                (interaction_id, json.dumps(response_json, sort_keys=True), generation_id),
            )
            if updated.rowcount != 1:
                raise CostError(
                    f"generation {generation_id} is not pending and cannot succeed"
                )
            cursor = self.conn.execute(
                "INSERT INTO candidate (generation_id, sha256, idx) VALUES (?, ?, 0)",
                (generation_id, candidate_sha256),
            )
        return int(cursor.lastrowid)

    def fail(
        self, generation_id: int, error: str, *, charge_expected: bool = True
    ) -> None:
        """Reconcile a failure, retaining cost unless it is known non-billable."""
        with self.conn:
            updated = self.conn.execute(
                """
                UPDATE generation
                   SET state = 'failed', error_text = ?,
                       cost_usd_cents = CASE WHEN ? THEN cost_usd_cents ELSE 0 END,
                       completed_at = datetime('now')
                 WHERE id = ? AND state = 'pending'
                """,
                (error, charge_expected, generation_id),
            )
            if updated.rowcount != 1:
                raise CostError(
                    f"generation {generation_id} is not pending and cannot fail"
                )
