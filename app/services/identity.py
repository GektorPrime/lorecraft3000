"""Face-embedding service: detect faces and embed with InsightFace ArcFace.

The module is deliberately importable when insightface is not installed —
every public function returns None / empty on ImportError so the rest of the
application runs without the dependency.  Install it with:

    uv pip install insightface onnxruntime

The model (buffalo_l, ~326 MB) is provisioned explicitly, never downloaded
implicitly: `python -m app.maintenance models install` fetches and verifies it
under ~/.insightface/models/ (see docs/OPERATIONS.md).
"""

from __future__ import annotations

import io
import logging
import os
import struct
import threading
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import urlretrieve

if TYPE_CHECKING:
    import sqlite3

    import numpy as np

log = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------

# Roles that provide reliable identity views. Turnaround sheets intentionally
# contribute every detected face; body, outfit, and head-back images do not.
FACE_ROLES = ("face_front", "face_3q", "face_profile", "turnaround")

# ArcFace output dimensionality.
_VECTOR_DIM = 512

# InsightFace model pack used for detection + recognition.
MODEL_NAME = "buffalo_l"

# Model files provisioned as a unit.  The pack also carries landmark/gender
# models that FaceAnalysis reports as "ignore"; only the files listed here are
# required for detection + recognition scoring.
BUFFALO_L_FILES = ("det_10g.onnx", "w600k_r50.onnx")

# Every pack file is comfortably above 500 KB; anything smaller is corruption.
MIN_MODEL_FILE_BYTES = 512_000

# Upstream release that ships the complete model pack as one zip.
BUFFALO_L_ZIP_URL = (
    "https://github.com/deepinsight/insightface/releases/download/"
    "v0.7/buffalo_l.zip"
)

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
            root=_insightface_root(),
            allowed_modules=["detection", "recognition"],
            providers=["CPUExecutionProvider"],
        )
        self._app.prepare(ctx_id=-1, det_size=(det_size, det_size))

    def _faces(self, image_bytes: bytes) -> tuple[list[np.ndarray], ...]:
        """Detect every face in the image; returns (vectors, bboxes, scores).

        Returns three parallel lists.  Callers needing only the largest face
        use ``embed`` instead.  Pillow decode failures yield empty lists.
        """
        import numpy as np  # required by insightface; import the same way it does
        from PIL import Image

        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                rgb = img.convert("RGB")
                bgr = np.ascontiguousarray(np.asarray(rgb)[:, :, ::-1])
        except Exception:
            return [], [], []
        faces = self._app.get(bgr)
        if not faces:
            return [], [], []
        vectors = [np.asarray(f.normed_embedding, dtype=np.float32) for f in faces]
        bboxes = [tuple(float(v) for v in f.bbox) for f in faces]
        scores = [float(f.det_score) for f in faces]
        return vectors, bboxes, scores

    def embed(self, image_bytes: bytes) -> np.ndarray | None:
        """Return the largest face's 512-d unit vector, or None if none found."""
        vectors, bboxes, _ = self._faces(image_bytes)
        if not vectors:
            return None
        # Largest by bbox area — the subject of a single-character panel.
        best_idx = max(
            range(len(bboxes)),
            key=lambda i: (bboxes[i][2] - bboxes[i][0]) * (bboxes[i][3] - bboxes[i][1]),
        )
        return vectors[best_idx]

    def detect(self, image_bytes: bytes) -> list[np.ndarray]:
        """Return every detected face's 512-d unit vector (empty if none)."""
        vectors, _, _ = self._faces(image_bytes)
        return vectors


def _insightface_root() -> str:
    """Parent of the models directory InsightFace searches."""
    return os.environ.get("INSIGHTFACE_HOME") or os.path.expanduser(
        os.path.join("~", ".insightface")
    )


def _model_root() -> str:
    """Directory where InsightFace looks for local model packs."""
    return os.path.join(_insightface_root(), "models")


def model_dir() -> Path:
    """Path to the buffalo_l pack directory (may not exist yet)."""
    return Path(_model_root()) / MODEL_NAME


def model_installed() -> bool:
    """True when every required pack file is present and plausibly intact."""
    if not model_dir().is_dir():
        return False
    return all(
        (model_dir() / name).is_file()
        and (model_dir() / name).stat().st_size >= MIN_MODEL_FILE_BYTES
        for name in BUFFALO_L_FILES
    )


def model_status() -> dict:
    """Human-usable description of the installed model state.

    Returns the state, the path examined, and the files found so a caller
    (maintenance command, startup, health) can report what is missing.
    """
    directory = model_dir()
    found = {name: (directory / name).is_file() for name in BUFFALO_L_FILES}
    if not Path(_model_root()).is_dir():
        state = "missing"
    elif all(found.values()):
        state = "ok"
    elif any(found.values()):
        state = "incomplete"
    else:
        state = "missing"
    return {"state": state, "path": str(directory), "files": found}


def install_model(
    *,
    url: str = BUFFALO_L_ZIP_URL,
    progress=None,
    verify: bool = True,
    force: bool = False,
) -> str:
    """Provision the buffalo_l pack under the InsightFace model root.

    Downloads the pack zip to a staging location inside the model root, unpacks
    it, checks all required files are present (and, by default, that the pack
    actually loads), then atomically swaps it into place.  An already-installed
    pack is a no-op unless ``force`` is set.  A failed verification restores
    the previous install if there was one, so the live path is never left
    half-populated.
    """
    target = model_dir()
    if verify and model_installed() and not force:
        return str(target)

    root = Path(_model_root())
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".{MODEL_NAME}.staging-{os.getpid()}"
    zip_path = root / f".{MODEL_NAME}.download-{os.getpid()}.zip"
    try:
        zip_path.unlink(missing_ok=True)
        print(f"fetching {MODEL_NAME} model pack from {url}")
        urlretrieve(url, zip_path, reporthook=progress)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(staging)
        # _verify_staging normalises root-vs-nested layouts in place.
        _verify_staging(staging)
        _swap_live(staging, target)
        if verify:
            try:
                FaceEmbedder()
            except Exception as exc:
                _restore(target)
                raise RuntimeError(
                    f"downloaded {MODEL_NAME} pack failed to load: {exc}"
                ) from exc
        return str(target)
    finally:
        zip_path.unlink(missing_ok=True)
        _rmtree(staging)
        _rmtree(root / f".{MODEL_NAME}.old-{os.getpid()}")


def _rmtree(path: Path) -> None:
    import shutil

    if path.exists():
        shutil.rmtree(path)


def _swap_live(staging: Path, target: Path) -> None:
    aside = target.parent / f".{MODEL_NAME}.old-{os.getpid()}"
    _rmtree(aside)
    if target.exists():
        target.rename(aside)
    staging.rename(target)


def _restore(target: Path) -> None:
    """Undo a swap: move any retired install back into place."""
    aside = target.parent / f".{MODEL_NAME}.old-{os.getpid()}"
    _rmtree(target)
    if aside.exists():
        aside.rename(target)


def _verify_staging(staging: Path) -> None:
    """Reject a freshly unpacked pack that is incomplete or truncated."""
    if not all((staging / name).is_file() for name in BUFFALO_L_FILES):
        nested = staging / MODEL_NAME
        if nested.is_dir() and all(
            (nested / name).is_file() for name in BUFFALO_L_FILES
        ):
            # Some archives nest the files under ./buffalo_l/ — flatten it.
            for child in list(nested.iterdir()):
                child.rename(staging / child.name)
            _rmtree(nested)
    missing = [name for name in BUFFALO_L_FILES if not (staging / name).is_file()]
    if missing:
        raise RuntimeError(
            f"downloaded model pack is missing required files: {', '.join(missing)}"
        )
    undersized = [
        name
        for name in BUFFALO_L_FILES
        if (staging / name).stat().st_size < MIN_MODEL_FILE_BYTES
    ]
    if undersized:
        raise RuntimeError(
            f"downloaded model pack has truncated files: {', '.join(undersized)}"
        )


def get_embedder() -> FaceEmbedder | None:
    """Return the global embedder, constructing it on first call.

    Returns None when insightface is not installed or the buffalo_l pack is not
    installed — never downloads implicitly.  The pack is provisioned once via
    `python -m app.maintenance models install`.
    """
    global _embedder
    if _embedder is not None:
        return _embedder
    if not _insightface_available:
        return None
    if not model_installed():
        log.warning(
            "InsightFace model pack %s not installed under %s — face embedding "
            "disabled (run `python -m app.maintenance models install`)",
            MODEL_NAME,
            _model_root(),
        )
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
    """Encode a vector to a compact BLOB (4 bytes per dimension).

    Accepts numpy arrays (production) and plain sequences (tests), so the
    encoder needs no numpy import of its own.
    """
    values = vector.tolist() if hasattr(vector, "tolist") else list(vector)
    return struct.pack(f"<{_VECTOR_DIM}f", *values)


def decode_embedding(blob: bytes) -> np.ndarray | None:
    """Decode a BLOB back to a float32 vector, or None on wrong size.

    The size check runs before importing numpy so a malformed blob is
    rejected even in environments without numpy installed.
    """
    expected = _VECTOR_DIM * 4
    if len(blob) != expected:
        return None
    import numpy as np

    values = struct.unpack(f"<{_VECTOR_DIM}f", blob)
    return np.array(values, dtype=np.float32)


# -----------------------------------------------------------------------
# Database helpers
# -----------------------------------------------------------------------


def store_embedding(conn: sqlite3.Connection, sha256: str, vector: np.ndarray) -> None:
    """Replace an image's embeddings with one face vector."""
    store_embeddings(conn, sha256, [vector])


def store_embeddings(
    conn: sqlite3.Connection, sha256: str, vectors: list[np.ndarray]
) -> None:
    """Replace an image's embeddings with all detected identity views."""
    conn.execute("DELETE FROM face_embedding WHERE sha256 = ?", (sha256,))
    conn.executemany(
        "INSERT INTO face_embedding (sha256, face_index, embedding) VALUES (?, ?, ?)",
        [
            (sha256, face_index, encode_embedding(vector))
            for face_index, vector in enumerate(vectors)
        ],
    )


def load_gallery(conn: sqlite3.Connection) -> dict[int, list[tuple[str, np.ndarray]]]:
    """Load all embeddings grouped by character id.

    Returns ``{character_id: [(sha256, vector), ...]}`` from the canonical
    ref_images joined against the face_embedding table.
    """
    placeholders = ", ".join("?" for _ in FACE_ROLES)
    rows = conn.execute(
        f"""
        SELECT ri.sha256, ri.role, rs.character_id, fe.embedding
          FROM ref_image   ri
          JOIN ref_set     rs ON rs.id = ri.ref_set_id
          JOIN face_embedding fe ON fe.sha256 = ri.sha256
         WHERE rs.status   = 'canonical'
            AND ri.role     IN ({placeholders})
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


def load_gallery_for_attachments(
    conn: sqlite3.Connection,
    attachments: list[dict] | tuple[dict, ...],
) -> dict[int, list[tuple[str, np.ndarray]]]:
    """Load the reference embeddings that a captured request actually used.

    ``attachments`` are the reference-image captures written into a
    ``request_json`` (each carries ``character_id`` and ``sha256``). This loads
    exactly those hashes — including images belonging to *retired* reference
    sets, whose versions were preserved specifically so a generation can be
    re-scored against the references it was really made from. A hash with no
    stored embedding (e.g. a face-less ref) is simply skipped.

    Returns ``{character_id: [(sha256, vector), ...]}``, mirroring
    ``load_gallery``'s shape so ``score_generated_image`` needs no change.
    """
    wanted: dict[int, list[str]] = {}
    for entry in attachments:
        if not isinstance(entry, dict):
            continue
        character_id = entry.get("character_id")
        sha256 = entry.get("sha256")
        if not isinstance(character_id, int) or not isinstance(sha256, str):
            continue
        wanted.setdefault(character_id, []).append(sha256)
    if not wanted:
        return {}

    placeholders = []
    params: list[str] = []
    for character_id, hashes in wanted.items():
        for sha in hashes:
            placeholders.append("?")
            params.append(sha)
    role_placeholders = ", ".join("?" for _ in FACE_ROLES)
    rows = conn.execute(
        f"""
        SELECT ri.sha256, ri.role, rs.character_id, fe.embedding
          FROM ref_image ri
          JOIN ref_set rs ON rs.id = ri.ref_set_id
          JOIN face_embedding fe ON fe.sha256 = ri.sha256
         WHERE ri.sha256 IN ({", ".join(placeholders)})
            AND ri.role   IN ({role_placeholders})
        """,
        (*params, *FACE_ROLES),
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
    L2-normalised, so cosine similarity is their dot product; computed as a
    plain zip-sum so the function needs no numpy import of its own.
    """
    scores: dict[int, float] = {}
    for character_id, entries in gallery.items():
        sims = [
            sum(p * v for p, v in zip(probe, vec))
            for sha, vec in entries
            if sha != exclude_sha
        ]
        if sims:
            scores[character_id] = float(max(sims))
    return scores


def score_generated_image(
    embedder: FaceEmbedder,
    gallery: dict[int, list[tuple[str, np.ndarray]]],
    image_bytes: bytes,
    cast_ids: tuple[int, ...],
) -> dict[str, object] | None:
    """Score a generated image against the cast's reference gallery.

    Every detected face is matched against every character.  The returned
    payload maps each cast character to its best similarity across all faces:

        {"cast": {"<character_id>": score, ...}, "faces_detected": <n>}

    Returns None when no face is found or insightface is unavailable.
    """
    faces = embedder.detect(image_bytes)
    if not faces:
        return None
    scores: dict[int, float] = {}
    for face in faces:
        per_character = score_against_gallery(face, gallery)
        for character_id, score in per_character.items():
            if character_id in cast_ids:
                scores[character_id] = max(
                    scores.get(character_id, score), score
                )
    if not scores:
        return None
    return {"cast": {str(k): round(v, 4) for k, v in sorted(scores.items())},
            "faces_detected": len(faces)}
