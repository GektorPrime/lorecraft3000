"""Face-embedding service: detect faces and embed with InsightFace ArcFace.

The module is deliberately importable when insightface is not installed —
every public function returns None / empty on ImportError so the rest of the
application runs without the optional dependency.  Install it with:

    uv pip install insightface onnxruntime

The model (buffalo_l, ~326 MB) downloads on first use to ~/.insightface/models/.
"""

from __future__ import annotations

import io
import logging
import struct
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

    import numpy as np

log = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------

# Roles whose images are close-ups of a face.  full_body/outfit shots are
# excluded from the gallery: the face is too small to embed reliably and
# would poison the reference vectors.  Mirrors the spike's FACE_ROLES.
FACE_ROLES = ("face_front", "face_3q", "face_profile")

# ArcFace output dimensionality.
_VECTOR_DIM = 512

# -----------------------------------------------------------------------
# Optional InsightFace import — degrade to a no-op when absent.
# -----------------------------------------------------------------------

_insightface_available = True
try:
    from insightface.app import FaceAnalysis  # noqa: F401
except ImportError:
    _insightface_available = False

# -----------------------------------------------------------------------
# Embedder singleton (lazy, thread-safe)
# -----------------------------------------------------------------------

_embedder: FaceEmbedder | None = None
_embedder_lock = threading.Lock()


class FaceEmbedder:
    """InsightFace buffalo_l for detection + recognition only.

    Loads once and is reused.  Thread-safe after construction.
    """

    def __init__(self, *, det_size: int = 640) -> None:
        if not _insightface_available:
            raise RuntimeError(
                "insightface is not installed — "
                "install with: uv pip install insightface onnxruntime"
            )
        self.det_size = det_size
        self._app = FaceAnalysis(
            name="buffalo_l",
            allowed_modules=["detection", "recognition"],
            providers=["CPUExecutionProvider"],
        )
        self._app.prepare(ctx_id=-1, det_size=(det_size, det_size))

    def embed(self, image_bytes: bytes) -> np.ndarray | None:
        """Return a 512-d L2-normalised unit vector, or None if no face found.

        The vector is returned as float32 for compact BLOB storage.
        """
        import numpy as np  # required by insightface; import the same way it does
        from PIL import Image

        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                rgb = img.convert("RGB")
                bgr = np.ascontiguousarray(np.asarray(rgb)[:, :, ::-1])
        except Exception:
            return None
        faces = self._app.get(bgr)
        if not faces:
            return None
        # Take the largest detected face (highest bbox area).
        best = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        return np.asarray(best.normed_embedding, dtype=np.float32)


def get_embedder() -> FaceEmbedder | None:
    """Return the global embedder, constructing it on first call.

    Returns None if insightface is not installed (the dependency is optional).
    """
    global _embedder
    if _embedder is not None:
        return _embedder
    if not _insightface_available:
        return None
    with _embedder_lock:
        if _embedder is not None:
            return _embedder
        try:
            _embedder = FaceEmbedder()
            log.info("InsightFace buffalo_l loaded successfully")
        except Exception:
            log.exception("Failed to load InsightFace model — face embedding disabled")
            return None
        return _embedder


# -----------------------------------------------------------------------
# BLOB codec
# -----------------------------------------------------------------------


def encode_embedding(vector: np.ndarray) -> bytes:
    """Encode a float32 vector to a compact BLOB (4 bytes per dimension)."""
    return struct.pack(f"<{_VECTOR_DIM}f", *vector.tolist())


def decode_embedding(blob: bytes) -> np.ndarray | None:
    """Decode a BLOB back to a float32 vector, or None on wrong size."""
    import numpy as np

    expected = _VECTOR_DIM * 4
    if len(blob) != expected:
        return None
    values = struct.unpack(f"<{_VECTOR_DIM}f", blob)
    return np.array(values, dtype=np.float32)


# -----------------------------------------------------------------------
# Database helpers
# -----------------------------------------------------------------------


def store_embedding(conn: sqlite3.Connection, sha256: str, vector: np.ndarray) -> None:
    """Insert or replace an embedding into the face_embedding table."""
    blob = encode_embedding(vector)
    conn.execute(
        "INSERT OR REPLACE INTO face_embedding (sha256, embedding) VALUES (?, ?)",
        (sha256, blob),
    )


def load_gallery(conn: sqlite3.Connection) -> dict[int, list[tuple[str, np.ndarray]]]:
    """Load all embeddings grouped by character id.

    Returns ``{character_id: [(sha256, vector), ...]}`` from the canonical
    ref_images joined against the face_embedding table.
    """
    rows = conn.execute(
        """
        SELECT ri.sha256, ri.role, rs.character_id, fe.embedding
          FROM ref_image   ri
          JOIN ref_set     rs ON rs.id = ri.ref_set_id
          JOIN face_embedding fe ON fe.sha256 = ri.sha256
         WHERE rs.status   = 'canonical'
           AND ri.role     IN (?, ?, ?)
        """,
        FACE_ROLES,
    ).fetchall()
    gallery: dict[int, list[tuple[str, np.ndarray]]] = {}
    for row in rows:
        vec = decode_embedding(row["embedding"])
        if vec is None:
            continue
        gallery.setdefault(row["character_id"], []).append((row["sha256"], vec))
    return gallery


def score_against_gallery(
    probe: np.ndarray,
    gallery: dict[int, list[tuple[str, np.ndarray]]],
    *,
    exclude_sha: str | None = None,
) -> dict[int, float]:
    """Best cosine similarity from a probe vector to each character.

    ``exclude_sha`` holds out one reference image so a leave-one-out trial
    cannot match an image against itself.  Both probe and gallery vectors are
    L2-normalised, so dot product equals cosine similarity.
    """
    import numpy as np

    scores: dict[int, float] = {}
    for character_id, entries in gallery.items():
        sims = [
            float(np.dot(probe, vec))
            for sha, vec in entries
            if sha != exclude_sha
        ]
        if sims:
            scores[character_id] = max(sims)
    return scores
