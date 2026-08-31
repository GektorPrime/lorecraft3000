"""Tests for configuration loading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import (
    DEFAULT_IMAGE_SIZE,
    DEFAULT_MODEL,
    MODEL_PRICES_CENTS,
    PRICE_TABLE_VERSION,
    PROJECT_ROOT,
    Settings,
)


def test_default_daily_spend_cap():
    s = Settings()
    assert s.daily_spend_cap_usd == 3.0
    assert s.daily_spend_cap_cents == 300


def test_default_model_and_size():
    s = Settings()
    assert s.default_model == "gemini-3.1-flash-image"
    assert s.default_image_size == "1K"


def test_price_table_has_exact_version_and_mappings():
    """Assert the exact price table version and all model->size->price mappings."""
    s = Settings()
    assert s.price_table_version == "2026-08-31.1"

    # Exact mappings for all four models present in app/config.py.
    assert s.model_prices_cents == {
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
        "gemini-2.5-flash-image": {"1K": 0},
    }


def test_default_paths_resolve_to_project_root():
    """Default paths resolve relative to the project root, not CWD."""
    s = Settings()
    assert s.db_path == PROJECT_ROOT / "data" / "lorecraft.db"
    assert s.store_root == PROJECT_ROOT / "store"


def test_price_table_is_independent_per_instance():
    """Mutating one instance's price table must not affect the global or another instance."""
    s1 = Settings()
    s2 = Settings()

    # Mutate s1's nested price table.
    s1.model_prices_cents["gemini-3.1-flash-image"]["1K"] = 999
    s1.model_prices_cents["gemini-3-pro-image"] = {"1K": 999}

    # s2 must be unaffected.
    assert s2.model_prices_cents["gemini-3.1-flash-image"]["1K"] == 7
    assert s2.model_prices_cents["gemini-3-pro-image"]["1K"] == 14

    # The global MODEL_PRICES_CENTS must be unaffected.
    assert MODEL_PRICES_CENTS["gemini-3.1-flash-image"]["1K"] == 7
    assert MODEL_PRICES_CENTS["gemini-3-pro-image"]["1K"] == 14


# ---------------------------------------------------------------------------
# Settings.from_env() coverage
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_env(monkeypatch):
    """Remove all LORECRAFT_* env vars before each test."""
    for key in (
        "LORECRAFT_DAILY_SPEND_CAP_USD",
        "LORECRAFT_DB_PATH",
        "LORECRAFT_STORE_ROOT",
        "LORECRAFT_DEFAULT_MODEL",
        "LORECRAFT_DEFAULT_IMAGE_SIZE",
    ):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_from_env_defaults(clean_env):
    s = Settings.from_env()
    assert s.daily_spend_cap_usd == 3.0
    assert s.daily_spend_cap_cents == 300
    assert s.db_path == PROJECT_ROOT / "data" / "lorecraft.db"
    assert s.store_root == PROJECT_ROOT / "store"
    assert s.default_model == DEFAULT_MODEL
    assert s.default_image_size == DEFAULT_IMAGE_SIZE


def test_from_env_daily_cap(clean_env):
    clean_env.setenv("LORECRAFT_DAILY_SPEND_CAP_USD", "5.5")
    s = Settings.from_env()
    assert s.daily_spend_cap_usd == 5.5
    assert s.daily_spend_cap_cents == 550


def test_from_env_db_path(clean_env):
    clean_env.setenv("LORECRAFT_DB_PATH", "/tmp/custom.db")
    s = Settings.from_env()
    assert s.db_path == Path("/tmp/custom.db")


def test_from_env_store_root(clean_env):
    clean_env.setenv("LORECRAFT_STORE_ROOT", "/tmp/custom-store")
    s = Settings.from_env()
    assert s.store_root == Path("/tmp/custom-store")


def test_from_env_default_model(clean_env):
    clean_env.setenv("LORECRAFT_DEFAULT_MODEL", "gemini-3-pro-image")
    s = Settings.from_env()
    assert s.default_model == "gemini-3-pro-image"


def test_from_env_default_image_size(clean_env):
    clean_env.setenv("LORECRAFT_DEFAULT_IMAGE_SIZE", "2K")
    s = Settings.from_env()
    assert s.default_image_size == "2K"


def test_from_env_relative_paths_resolve_as_given(clean_env):
    """Env overrides are used as-is (relative paths stay relative to CWD)."""
    clean_env.setenv("LORECRAFT_DB_PATH", "data/custom.db")
    s = Settings.from_env()
    assert s.db_path == Path("data/custom.db")
