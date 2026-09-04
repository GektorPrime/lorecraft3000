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


def make_unit_vector(value: float) -> list[float]:
    """A deterministic 512-d unit vector whose cosine similarity to another
    vector of the same shape is monotonic in the two values.

    Entries are (value, 0, ..., 0, sqrt(1-value^2)): the norm is 1 and the
    dot product of two such vectors is cos(arccos(v1)-arccos(v2)), which
    equals 1 only when v1 == v2.  Needs no numpy.
    """
    tail = (1.0 - value * value) ** 0.5
    return [value] + [0.0] * 510 + [tail]


class FakeEmbedder:
    """Numpy-free stand-in for FaceEmbedder used by identity-scoring tests.

    ``embed()`` returns the configured vector (or None when no_face is set);
    ``detect()`` returns one vector per entry in ``faces``. Pass ``faces=[]``
    for a candidate that carries no detectable face. Set ``error`` to make
    every call raise (both paths must swallow it).
    """

    def __init__(
        self,
        faces: list[list[float]] | None = None,
        *,
        no_face: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.face = make_unit_vector(0.7)
        self.faces = faces if faces is not None else ([] if no_face else [self.face])
        self.error = error

    def _raise_if_needed(self) -> None:
        if self.error:
            raise self.error

    def embed(self, image_bytes: bytes):
        self._raise_if_needed()
        if not self.faces:
            return None
        return self.faces[0]

    def detect(self, image_bytes: bytes) -> list[list[float]]:
        self._raise_if_needed()
        return list(self.faces)


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    """A default FakeEmbedder returning one detectable unit vector."""
    return FakeEmbedder()


@pytest.fixture(autouse=True)
def _no_real_face_model(monkeypatch):
    """Keep the suite model-independent.

    The real FaceEmbedder loads the ~320MB buffalo_l model on first use (and
    every module that calls get_embedder imports it into its own namespace,
    so all call sites must be patched). Tests exercise identity behaviour
    explicitly with FakeEmbedder instead; stubbing get_embedder to None keeps
    local runs fast and identical to CI, which has no model downloaded.
    """
    for module in (
        "app.services.identity",
        "app.services.ref_sets",
        "app.services.generation",
        "app.maintenance",
    ):
        monkeypatch.setattr(f"{module}.get_embedder", lambda: None)
