"""Shared pytest fixtures.

Tests never hit the network. All DB and storage paths are isolated per test
via tmp_path.
"""

from __future__ import annotations

import io
import pytest
from PIL import Image

from app.config import Settings
from app.db import connect
from app.migrate import run_migrations
from app.storage import ImageStorage


def make_png_bytes(color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    """Return a small valid PNG as bytes."""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def png_bytes() -> bytes:
    return make_png_bytes()


@pytest.fixture
def db_path(tmp_path):
    """A fresh, migrated SQLite DB in a temp dir."""
    path = tmp_path / "test.db"
    run_migrations(path)
    return path


@pytest.fixture
def conn(db_path):
    """An open connection to the migrated test DB."""
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def store_root(tmp_path):
    """A fresh content-addressed store root in a temp dir."""
    return tmp_path / "store"


@pytest.fixture
def storage(store_root):
    """An ImageStorage rooted at a temp dir."""
    return ImageStorage(store_root)


@pytest.fixture
def settings(tmp_path):
    """A Settings instance with temp paths (no env dependence)."""
    return Settings(
        db_path=tmp_path / "test.db",
        store_root=tmp_path / "store",
    )
