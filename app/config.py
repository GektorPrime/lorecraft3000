"""Application configuration loaded from environment / .env.

Settings are read from the environment (with .env loaded via python-dotenv at
startup). Secrets such as GEMINI_API_KEY are never printed or hard-coded here;
they are read from the environment only.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load project-local .env (does not override already-exported env vars).
load_dotenv()

# ---------------------------------------------------------------------------
# Model price table (USD per image, by model and image size).
#
# Prices are stored as INTEGER minor units (cents) to avoid float drift.
# Values are conservatively rounded UP from the verified API facts in
# documentation/agents.md so the local hard cap never undercounts a call.
# Bump PRICE_TABLE_VERSION only if any value in the table changes.
# Version identifier lets us detect when the table changes so provenance can
# record which price table was in effect for a given generation.
# ---------------------------------------------------------------------------

# price_table_version: bump whenever the table below changes.
PRICE_TABLE_VERSION = "2026-08-31.1"

# Prices in cents (minor units) per image.
MODEL_PRICES_CENTS: dict[str, dict[str, int]] = {
    "gemini-3.1-flash-lite-image": {"1K": 4},
    "gemini-3.1-flash-image": {
        "512": 5,
        "1K": 7,
        "2K": 11,
        "4K": 16,
    },
    "gemini-3-pro-image": {
        "1K": 14,
        "2K": 20,
        "4K": 24,
    },
    "gemini-2.5-flash-image": {"1K": 0},  # legacy, price unverified
}

DEFAULT_MODEL = "gemini-3.1-flash-image"
DEFAULT_IMAGE_SIZE = "1K"

# Project root: the directory containing pyproject.toml. Default paths resolve
# relative to this so running the server from another directory does not
# silently create data/store elsewhere.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _deep_copy_price_table() -> dict[str, dict[str, int]]:
    """Return an independent deep copy of the global price table.

    Each Settings instance gets its own copy so mutating one instance's price
    table never leaks into the global MODEL_PRICES_CENTS or other instances.
    """
    return copy.deepcopy(MODEL_PRICES_CENTS)


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the LoreCraft3000 app."""

    # Daily spend cap in USD (hard ceiling, enforced in our own code).
    daily_spend_cap_usd: float = 3.0

    # Model price table (cents per image) + version identifier.
    # Each instance gets an independent deep copy (see _deep_copy_price_table).
    model_prices_cents: dict[str, dict[str, int]] = field(
        default_factory=_deep_copy_price_table
    )
    price_table_version: str = PRICE_TABLE_VERSION

    # Default model and image size.
    default_model: str = DEFAULT_MODEL
    default_image_size: str = DEFAULT_IMAGE_SIZE

    # SQLite database path (resolved relative to project root by default).
    db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "lorecraft.db")

    # Content-addressed store root (resolved relative to project root by default).
    store_root: Path = field(default_factory=lambda: PROJECT_ROOT / "store")

    # Bound provider calls and recover attempts left pending by process failure.
    provider_timeout_seconds: int = 120
    pending_stale_seconds: int = 600

    # SQLite concurrency and durability tuning. WAL lets one writer and many
    # readers proceed without blocking each other; the busy timeout makes a
    # second writer wait briefly instead of failing immediately with
    # "database is locked"; synchronous=NORMAL is the safe, standard pairing
    # with WAL.
    sqlite_journal_mode: str = "wal"
    sqlite_busy_timeout_ms: int = 5000
    sqlite_synchronous: str = "normal"

    # When True, run a lightweight storage consistency scan during app startup
    # and log a summary. The scan never modifies anything; operators who want
    # repairs run `python -m app.maintenance repair` explicitly.
    consistency_check_on_startup: bool = False

    @property
    def daily_spend_cap_cents(self) -> int:
        """Daily spend cap expressed as integer minor units (cents)."""
        return int(round(self.daily_spend_cap_usd * 100))

    @classmethod
    def from_env(cls) -> "Settings":
        """Build Settings from environment variables (with .env already loaded)."""
        daily_cap = float(os.environ.get("LORECRAFT_DAILY_SPEND_CAP_USD", "3.0"))
        db_env = os.environ.get("LORECRAFT_DB_PATH", "")
        db_path = Path(db_env) if db_env else (PROJECT_ROOT / "data" / "lorecraft.db")
        store_env = os.environ.get("LORECRAFT_STORE_ROOT", "")
        store_root = Path(store_env) if store_env else (PROJECT_ROOT / "store")
        default_model = os.environ.get("LORECRAFT_DEFAULT_MODEL", DEFAULT_MODEL)
        default_image_size = os.environ.get(
            "LORECRAFT_DEFAULT_IMAGE_SIZE", DEFAULT_IMAGE_SIZE
        )
        provider_timeout_seconds = int(
            os.environ.get("LORECRAFT_PROVIDER_TIMEOUT_SECONDS", "120")
        )
        pending_stale_seconds = int(
            os.environ.get("LORECRAFT_PENDING_STALE_SECONDS", "600")
        )
        journal_mode = os.environ.get(
            "LORECRAFT_SQLITE_JOURNAL_MODE", "wal"
        ).strip().lower()
        busy_timeout_ms = int(
            os.environ.get("LORECRAFT_SQLITE_BUSY_TIMEOUT_MS", "5000")
        )
        synchronous = os.environ.get(
            "LORECRAFT_SQLITE_SYNCHRONOUS", "normal"
        ).strip().lower()
        consistency_check = os.environ.get(
            "LORECRAFT_CONSISTENCY_CHECK_ON_STARTUP", "false"
        ).strip().lower() in {"1", "true", "yes", "on"}
        if provider_timeout_seconds <= 0:
            raise ValueError("LORECRAFT_PROVIDER_TIMEOUT_SECONDS must be positive")
        allowed_journal_modes = {
            "delete", "truncate", "persist", "memory", "wal", "off"
        }
        if journal_mode not in allowed_journal_modes:
            raise ValueError(
                "LORECRAFT_SQLITE_JOURNAL_MODE must be one of "
                + ", ".join(sorted(allowed_journal_modes))
            )
        allowed_synchronous = {"off", "normal", "full", "extra"}
        if synchronous not in allowed_synchronous:
            raise ValueError(
                "LORECRAFT_SQLITE_SYNCHRONOUS must be one of "
                + ", ".join(sorted(allowed_synchronous))
            )
        if busy_timeout_ms < 0:
            raise ValueError("LORECRAFT_SQLITE_BUSY_TIMEOUT_MS must not be negative")
        # Gemini capacity retries can make up to four calls with 11 seconds of
        # total backoff. Recovery must not expire an attempt still in that loop.
        minimum_stale_seconds = provider_timeout_seconds * 4 + 11
        if pending_stale_seconds <= minimum_stale_seconds:
            raise ValueError(
                "LORECRAFT_PENDING_STALE_SECONDS must exceed the maximum provider "
                "retry duration"
            )
        return cls(
            daily_spend_cap_usd=daily_cap,
            db_path=db_path,
            store_root=store_root,
            default_model=default_model,
            default_image_size=default_image_size,
            provider_timeout_seconds=provider_timeout_seconds,
            pending_stale_seconds=pending_stale_seconds,
            sqlite_journal_mode=journal_mode,
            sqlite_busy_timeout_ms=busy_timeout_ms,
            sqlite_synchronous=synchronous,
            consistency_check_on_startup=consistency_check,
        )
