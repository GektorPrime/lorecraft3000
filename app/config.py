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
# Each value is round(price_usd * 100) cents from the verified API facts in
# documentation/agents.md (e.g. Flash @ 1K ~= $0.067 -> 7 cents).
# Bump PRICE_TABLE_VERSION only if any value in the table changes.
# Version identifier lets us detect when the table changes so provenance can
# record which price table was in effect for a given generation.
# ---------------------------------------------------------------------------

# price_table_version: bump whenever the table below changes.
PRICE_TABLE_VERSION = "2026-08-30.1"

# Prices in cents (minor units) per image.
MODEL_PRICES_CENTS: dict[str, dict[str, int]] = {
    "gemini-3.1-flash-lite-image": {"1K": 3},
    "gemini-3.1-flash-image": {
        "512": 5,
        "1K": 7,
        "2K": 10,
        "4K": 15,
    },
    "gemini-3-pro-image": {
        "1K": 13,
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
        return cls(
            daily_spend_cap_usd=daily_cap,
            db_path=db_path,
            store_root=store_root,
            default_model=default_model,
            default_image_size=default_image_size,
        )
