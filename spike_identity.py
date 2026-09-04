"""Feasibility spike: can face embeddings tell LoreCraft3000 characters apart?

THROWAWAY. Not part of the application. Nothing imports this. Delete it once
the question below is answered.

THE QUESTION
------------
Before building an automated identity check on generated candidates, we need to
know whether face recognition works at all on this library's art. Face models
are trained on photographs of real people; this project renders Victorian oil
paintings, often with four characters in a wide panel where each face is only a
few dozen pixels tall. Either of those can make the metric meaningless.

This script answers that empirically, read-only, against the real database and
image store. It writes nothing and never calls a paid API.

THE TIERS (run in order; stop at the first failure)
---------------------------------------------------
Tier 1  Leave-one-out over the canonical reference images only. Hide one
        reference and ask whether its own character still matches it best.
        This is the ceiling: if the model cannot separate the cast using clean
        reference art, it has no chance on generated panels.

Tier 2  Single-character panels, where the expected character is unambiguous.
        Detect the face in each generated candidate and check that the right
        character ranks first. This is the real question.

Tier 3  Multi-character panels. Measures how often a face is found at all and
        — critically — how many pixels tall those faces are. A face below
        roughly 60px carries too little signal for the score to mean anything,
        regardless of model quality. Also sweeps detector input size, so a low
        detection rate can be distinguished from "the detector was fed too
        small an image".

USAGE
-----
    .venv-spike/bin/python spike_identity.py
    .venv-spike/bin/python spike_identity.py --tier 1
    .venv-spike/bin/python spike_identity.py --det-size 1024

Requires the throwaway environment (insightface + onnxruntime), which is
deliberately kept out of pyproject.toml:

    uv venv --python 3.14 .venv-spike
    VIRTUAL_ENV=.venv-spike uv pip install insightface onnxruntime
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

# The spike reads stored bytes exactly the way the app does — same completeness
# and hash checks — instead of reimplementing the layout and drifting from it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.storage import ImageStorage, ImageStorageError  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "lorecraft.db"
STORE_ROOT = PROJECT_ROOT / "store"

# Roles whose images are close-ups of a face. full_body/outfit shots are
# excluded from the gallery: the face is too small to embed reliably and would
# poison the reference vectors.
FACE_ROLES = ("face_front", "face_3q", "face_profile")

# Pass marks, fixed here BEFORE seeing any result so the outcome cannot be
# rationalised after the fact.
TIER1_PASS_RATE = 0.83          # >= 10 of 12 reference images
TIER1_STOP_RATE = 0.66          # below this the feature is dead
TIER2_PASS_RATE = 0.70          # >= 9 of 13 single-character candidates
TIER3_DETECTION_RATE = 0.70     # a face found in 70% of multi-character panels
TIER3_MIN_FACE_PX = 80.0        # median detected face height, in pixels


# ---------------------------------------------------------------------------
# Data loading (read-only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RefImage:
    sha256: str
    character_id: int
    character_name: str
    role: str


@dataclass(frozen=True)
class CandidateImage:
    candidate_id: int
    sha256: str
    scene_id: int
    cast_ids: tuple[int, ...]
    image_size: str
    aspect_ratio: str
    review_status: str


@dataclass
class Detection:
    """One detected face: its 512-d unit vector plus where it was found."""

    vector: np.ndarray
    bbox: tuple[float, float, float, float]
    det_score: float

    @property
    def height_px(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def width_px(self) -> float:
        return self.bbox[2] - self.bbox[0]


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the live database read-only so the spike cannot mutate it."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_characters(conn: sqlite3.Connection) -> dict[int, str]:
    rows = conn.execute(
        "SELECT id, name FROM character WHERE archived_at IS NULL ORDER BY id"
    ).fetchall()
    return {row["id"]: row["name"] for row in rows}


def load_reference_images(conn: sqlite3.Connection) -> list[RefImage]:
    """Canonical, face-role reference images for every active character."""
    placeholders = ", ".join("?" for _ in FACE_ROLES)
    rows = conn.execute(
        f"""
        SELECT ri.sha256      AS sha256,
               rs.character_id AS character_id,
               c.name          AS character_name,
               ri.role         AS role
          FROM ref_image ri
          JOIN ref_set   rs ON rs.id = ri.ref_set_id
          JOIN character c  ON c.id  = rs.character_id
         WHERE rs.status = 'canonical'
           AND ri.role IN ({placeholders})
         ORDER BY rs.character_id, ri.role, ri.id
        """,
        FACE_ROLES,
    ).fetchall()
    return [
        RefImage(r["sha256"], r["character_id"], r["character_name"], r["role"])
        for r in rows
    ]


def _cast_ids(generation_request_json: str, scene_cast_json: str) -> tuple[int, ...]:
    """Character ids that a candidate was actually generated for.

    Prefers the generation's captured request (authoritative for what was sent
    to the provider) and falls back to the panel's current cast.
    """
    for raw, key in ((generation_request_json, "cast"), (scene_cast_json, None)):
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        entries = payload.get(key) if key else payload
        if not isinstance(entries, list) or not entries:
            continue
        ids = [e.get("character_id") for e in entries if isinstance(e, dict)]
        ids = [i for i in ids if isinstance(i, int)]
        if ids:
            return tuple(ids)
    return ()


def load_candidates(conn: sqlite3.Connection) -> list[CandidateImage]:
    rows = conn.execute(
        """
        SELECT cd.id            AS candidate_id,
               cd.sha256        AS sha256,
               cd.review_status AS review_status,
               sc.id            AS scene_id,
               sc.cast_json     AS scene_cast_json,
               sc.image_size    AS image_size,
               sc.aspect_ratio  AS aspect_ratio,
               g.request_json   AS request_json
          FROM candidate  cd
          JOIN generation g  ON g.id  = cd.generation_id
          JOIN scene      sc ON sc.id = g.scene_id
         ORDER BY cd.id
        """
    ).fetchall()
    out: list[CandidateImage] = []
    for r in rows:
        cast = _cast_ids(r["request_json"], r["scene_cast_json"])
        if not cast:
            continue
        out.append(
            CandidateImage(
                candidate_id=r["candidate_id"],
                sha256=r["sha256"],
                scene_id=r["scene_id"],
                cast_ids=cast,
                image_size=r["image_size"] or "?",
                aspect_ratio=r["aspect_ratio"] or "?",
                review_status=r["review_status"],
            )
        )
    return out


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


class Embedder:
    """InsightFace buffalo_l wrapped to the two calls this spike needs."""

    def __init__(self, det_size: int = 640) -> None:
        from insightface.app import FaceAnalysis

        self.det_size = det_size
        # Only detection + recognition; landmarks and gender/age are dead weight.
        # prepare() and the ONNX session setup print a wall of provider noise.
        with contextlib.redirect_stdout(io.StringIO()):
            self.app = FaceAnalysis(
                name="buffalo_l",
                allowed_modules=["detection", "recognition"],
                providers=["CPUExecutionProvider"],
            )
            self.app.prepare(ctx_id=-1, det_size=(det_size, det_size))

    def detect(self, image_bytes: bytes) -> tuple[tuple[Detection, ...], tuple[int, int]]:
        """Return every detected face plus the image's (width, height)."""
        with Image.open(io.BytesIO(image_bytes)) as img:
            rgb = img.convert("RGB")
            size = (rgb.width, rgb.height)
            # insightface follows the OpenCV convention and expects BGR.
            bgr = np.ascontiguousarray(np.asarray(rgb)[:, :, ::-1])
        faces = self.app.get(bgr)
        detections = tuple(
            Detection(
                vector=np.asarray(f.normed_embedding, dtype=np.float32),
                bbox=tuple(float(v) for v in f.bbox),
                det_score=float(f.det_score),
            )
            for f in faces
        )
        return detections, size


def largest(detections: tuple[Detection, ...]) -> Detection | None:
    """The most prominent face — the subject of a single-character panel."""
    return max(detections, key=lambda d: d.height_px * d.width_px, default=None)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity. Both vectors are already L2-normalised."""
    return float(np.dot(a, b))


# ---------------------------------------------------------------------------
# Gallery
# ---------------------------------------------------------------------------


@dataclass
class Gallery:
    """Reference vectors per character, and what failed to embed."""

    vectors: dict[int, list[tuple[str, np.ndarray]]] = field(default_factory=dict)
    no_face: list[RefImage] = field(default_factory=list)
    multi_face: list[tuple[RefImage, int]] = field(default_factory=list)
    unreadable: list[tuple[RefImage, str]] = field(default_factory=list)

    def score(self, probe: np.ndarray, *, exclude_sha: str | None = None) -> dict[int, float]:
        """Best similarity from a probe vector to each character.

        ``exclude_sha`` holds out one reference image so a leave-one-out trial
        cannot match an image against itself.
        """
        out: dict[int, float] = {}
        for character_id, entries in self.vectors.items():
            scores = [
                similarity(probe, vec)
                for sha, vec in entries
                if sha != exclude_sha
            ]
            if scores:
                out[character_id] = max(scores)
        return out


def build_gallery(
    embedder: Embedder, storage: ImageStorage, refs: list[RefImage]
) -> Gallery:
    gallery = Gallery()
    for ref in refs:
        try:
            data, _ = storage.read(ref.sha256)
        except ImageStorageError as exc:
            gallery.unreadable.append((ref, str(exc)))
            continue
        detections, _ = embedder.detect(data)
        if not detections:
            gallery.no_face.append(ref)
            continue
        if len(detections) > 1:
            gallery.multi_face.append((ref, len(detections)))
        face = largest(detections)
        gallery.vectors.setdefault(ref.character_id, []).append((ref.sha256, face.vector))
    return gallery


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------


def heading(text: str) -> None:
    print(f"\n{text}")
    print("=" * len(text))


def percentiles(values: list[float]) -> str:
    if not values:
        return "n/a"
    arr = np.asarray(values)
    return (
        f"min {arr.min():.3f} | p25 {np.percentile(arr, 25):.3f} | "
        f"median {np.median(arr):.3f} | p75 {np.percentile(arr, 75):.3f} | "
        f"p95 {np.percentile(arr, 95):.3f} | max {arr.max():.3f}"
    )


def verdict(passed: bool, detail: str) -> str:
    return f"{'PASS' if passed else 'FAIL'} — {detail}"


# ---------------------------------------------------------------------------
# Tier 1 — leave-one-out over reference images
# ---------------------------------------------------------------------------


def tier1(gallery: Gallery, characters: dict[int, str], refs: list[RefImage]) -> bool:
    heading("TIER 1 — leave-one-out over canonical reference images")
    print(
        "Hide one reference image, then ask which character matches it best.\n"
        f"Chance level with {len(characters)} characters is "
        f"{100.0 / max(len(characters), 1):.0f}%.\n"
    )

    for ref in gallery.no_face:
        print(f"  no face detected in {ref.character_name} / {ref.role} ({ref.sha256[:12]})")
    for ref, count in gallery.multi_face:
        print(f"  {count} faces in {ref.character_name} / {ref.role} — used the largest")
    for ref, error in gallery.unreadable:
        print(f"  unreadable: {ref.character_name} / {ref.role}: {error}")

    by_sha = {r.sha256: r for r in refs}
    correct = 0
    trials = 0
    margins: list[float] = []

    for character_id, entries in sorted(gallery.vectors.items()):
        for sha, vector in entries:
            ref = by_sha[sha]
            scores = gallery.score(vector, exclude_sha=sha)
            # A character with a single reference has no gallery left once its
            # only image is held out; that is an untestable trial, not a miss.
            if character_id not in scores:
                print(f"  skipped {ref.character_name} / {ref.role}: no other reference")
                continue
            trials += 1
            ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
            winner_id, winner_score = ranked[0]
            runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
            hit = winner_id == character_id
            correct += hit
            margins.append(scores[character_id] - max(
                (s for cid, s in scores.items() if cid != character_id), default=0.0
            ))
            flag = "ok  " if hit else "MISS"
            print(
                f"  {flag} {ref.character_name:<20} {ref.role:<11} "
                f"own {scores[character_id]:.3f} | "
                f"best {characters.get(winner_id, '?'):<20} {winner_score:.3f} | "
                f"runner-up {runner_up:.3f}"
            )

    if not trials:
        print("\n  No testable reference images. Cannot judge.")
        return False

    rate = correct / trials
    print(f"\n  Correct: {correct}/{trials} ({rate:.0%})")
    print(f"  Margin (own minus best rival): {percentiles(margins)}")
    print(f"  A positive median margin means the right character wins on average.")
    passed = rate >= TIER1_PASS_RATE
    print(
        "\n  "
        + verdict(passed, f"needed {TIER1_PASS_RATE:.0%}, got {rate:.0%}")
    )
    if rate < TIER1_STOP_RATE:
        print("  STOP. The model cannot separate this cast on clean reference art.")
    return passed


# ---------------------------------------------------------------------------
# Tier 2 — single-character generated candidates
# ---------------------------------------------------------------------------


def tier2(
    embedder: Embedder,
    storage: ImageStorage,
    gallery: Gallery,
    characters: dict[int, str],
    candidates: list[CandidateImage],
) -> bool:
    heading("TIER 2 — generated candidates from single-character panels")
    singles = [c for c in candidates if len(c.cast_ids) == 1]
    print(
        f"{len(singles)} candidates where the expected character is unambiguous.\n"
        "Detect the largest face, then check the right character ranks first.\n"
    )
    if not singles:
        print("  No single-character panels. Tier 2 cannot run.")
        return False

    correct = 0
    tested = 0
    no_face = 0
    own_scores: list[float] = []
    rival_scores: list[float] = []
    face_heights: list[float] = []

    for candidate in singles:
        expected_id = candidate.cast_ids[0]
        name = characters.get(expected_id, f"#{expected_id}")
        try:
            data, _ = storage.read(candidate.sha256)
        except ImageStorageError as exc:
            print(f"  unreadable candidate {candidate.candidate_id}: {exc}")
            continue
        detections, (width, height) = embedder.detect(data)
        face = largest(detections)
        if face is None:
            no_face += 1
            print(
                f"  no face  candidate {candidate.candidate_id:<4} {name:<20} "
                f"({candidate.image_size} {candidate.aspect_ratio}, {width}x{height})"
            )
            continue

        scores = gallery.score(face.vector)
        if expected_id not in scores:
            print(f"  skipped candidate {candidate.candidate_id}: {name} has no references")
            continue

        tested += 1
        face_heights.append(face.height_px)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        winner_id, winner_score = ranked[0]
        hit = winner_id == expected_id
        correct += hit
        own_scores.append(scores[expected_id])
        rival_scores.extend(s for cid, s in scores.items() if cid != expected_id)
        flag = "ok  " if hit else "MISS"
        print(
            f"  {flag} candidate {candidate.candidate_id:<4} {name:<20} "
            f"own {scores[expected_id]:.3f} | best {characters.get(winner_id, '?'):<20} "
            f"{winner_score:.3f} | face {face.height_px:.0f}px"
        )

    detected = tested + no_face
    if detected:
        print(f"\n  Face found in {tested}/{detected} ({tested / detected:.0%})")
    if not tested:
        print("  No candidate produced both a face and a usable reference. Cannot judge.")
        return False

    rate = correct / tested
    print(f"  Correct character ranked first: {correct}/{tested} ({rate:.0%})")
    print(f"  Detected face height (px): {percentiles(face_heights)}")
    print(f"  Similarity to the right character:  {percentiles(own_scores)}")
    print(f"  Similarity to the wrong characters: {percentiles(rival_scores)}")
    if own_scores and rival_scores:
        gap = float(np.median(own_scores) - np.percentile(rival_scores, 95))
        print(
            f"  Separation (median correct minus p95 wrong): {gap:+.3f}"
            f"  {'— a threshold exists' if gap > 0 else '— the two overlap'}"
        )
    passed = rate >= TIER2_PASS_RATE
    print("\n  " + verdict(passed, f"needed {TIER2_PASS_RATE:.0%}, got {rate:.0%}"))
    return passed


# ---------------------------------------------------------------------------
# Tier 3 — multi-character panels, detection and face size
# ---------------------------------------------------------------------------


def tier3(
    embedder: Embedder,
    storage: ImageStorage,
    gallery: Gallery,
    characters: dict[int, str],
    candidates: list[CandidateImage],
    det_sizes: list[int],
) -> bool:
    heading("TIER 3 — multi-character panels: is there enough face to measure?")
    multi = [c for c in candidates if len(c.cast_ids) > 1]
    print(
        f"{len(multi)} candidates from panels with more than one character.\n"
        "This is the case the feature exists for, and the hardest one.\n"
    )
    if not multi:
        print("  No multi-character panels. Tier 3 cannot run.")
        return False

    # Sweep detector input size, so a poor detection rate can be told apart
    # from "the detector was handed too small an image".
    sweep: dict[int, tuple[int, int, list[float]]] = {}
    for det_size in det_sizes:
        probe = embedder if det_size == embedder.det_size else Embedder(det_size=det_size)
        found = 0
        total_faces = 0
        heights: list[float] = []
        for candidate in multi:
            try:
                data, _ = storage.read(candidate.sha256)
            except ImageStorageError:
                continue
            detections, _ = probe.detect(data)
            if detections:
                found += 1
                total_faces += len(detections)
                heights.extend(d.height_px for d in detections)
        sweep[det_size] = (found, total_faces, heights)
        rate = found / len(multi)
        median_px = float(np.median(heights)) if heights else 0.0
        print(
            f"  detector input {det_size:>4}px: face found in {found}/{len(multi)} "
            f"({rate:.0%}), {total_faces} faces total, median height {median_px:.0f}px"
        )

    best_size = max(sweep, key=lambda s: sweep[s][0])
    found, total_faces, heights = sweep[best_size]
    detection_rate = found / len(multi)
    median_px = float(np.median(heights)) if heights else 0.0

    print(f"\n  Best detector input size: {best_size}px")
    print(f"  Detected face height (px): {percentiles(heights)}")

    # Expected-vs-found face counts, and in-cast vs out-of-cast similarity.
    probe = embedder if best_size == embedder.det_size else Embedder(det_size=best_size)
    in_cast: list[float] = []
    out_cast: list[float] = []
    count_match = 0
    counted = 0
    for candidate in multi:
        try:
            data, _ = storage.read(candidate.sha256)
        except ImageStorageError:
            continue
        detections, _ = probe.detect(data)
        counted += 1
        count_match += len(detections) == len(candidate.cast_ids)
        for face in detections:
            scores = gallery.score(face.vector)
            for character_id, score in scores.items():
                (in_cast if character_id in candidate.cast_ids else out_cast).append(score)

    if counted:
        print(
            f"  Face count matched the cast size in {count_match}/{counted} "
            f"({count_match / counted:.0%}) of panels"
        )
    print(f"  Similarity to characters in the cast:     {percentiles(in_cast)}")
    print(f"  Similarity to characters not in the cast: {percentiles(out_cast)}")
    if in_cast and out_cast:
        gap = float(np.median(in_cast) - np.median(out_cast))
        print(
            f"  Separation (median in-cast minus median out-of-cast): {gap:+.3f}"
            f"  {'— usable signal' if gap > 0.05 else '— little or no signal'}"
        )

    detection_ok = detection_rate >= TIER3_DETECTION_RATE
    size_ok = median_px >= TIER3_MIN_FACE_PX
    print(
        "\n  "
        + verdict(
            detection_ok,
            f"detection needed {TIER3_DETECTION_RATE:.0%}, got {detection_rate:.0%}",
        )
    )
    print(
        "  "
        + verdict(
            size_ok,
            f"median face height needed {TIER3_MIN_FACE_PX:.0f}px, got {median_px:.0f}px",
        )
    )
    if not size_ok and median_px:
        print(
            "  Faces this small carry little identity signal. Generating "
            "multi-character panels at a larger image size would raise it."
        )
    return detection_ok and size_ok


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Feasibility spike for face-embedding identity scoring."
    )
    parser.add_argument(
        "--tier", type=int, choices=(1, 2, 3), help="run a single tier"
    )
    parser.add_argument(
        "--det-size", type=int, default=640, help="detector input size (default 640)"
    )
    parser.add_argument(
        "--det-sweep",
        type=str,
        default="640,1024",
        help="comma-separated detector sizes to compare in tier 3",
    )
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--store", type=Path, default=STORE_ROOT)
    args = parser.parse_args()

    if not args.db.exists():
        print(f"database not found: {args.db}", file=sys.stderr)
        return 2
    if not args.store.exists():
        print(f"image store not found: {args.store}", file=sys.stderr)
        return 2

    conn = open_readonly(args.db)
    storage = ImageStorage(args.store)
    characters = load_characters(conn)
    refs = load_reference_images(conn)
    candidates = load_candidates(conn)

    heading("LIBRARY")
    print(f"  characters                {len(characters)}")
    print(f"  canonical face references {len(refs)}")
    print(f"  candidates                {len(candidates)}")
    print(f"  detector input size       {args.det_size}px")
    for character_id, name in characters.items():
        roles = [r.role for r in refs if r.character_id == character_id]
        print(f"    {name:<22} {len(roles)} refs ({', '.join(roles) or 'none'})")

    if len(characters) < 2:
        print("\nFewer than two characters. There is nothing to tell apart.")
        return 2

    print("\nLoading buffalo_l …")
    embedder = Embedder(det_size=args.det_size)
    print("Embedding reference images …")
    gallery = build_gallery(embedder, storage, refs)

    results: dict[str, bool] = {}
    if args.tier in (None, 1):
        results["tier 1"] = tier1(gallery, characters, refs)
        if args.tier is None and not results["tier 1"]:
            heading("SUMMARY")
            print("  Tier 1 failed. Later tiers cannot succeed. Stopping.")
            return 1
    if args.tier in (None, 2):
        results["tier 2"] = tier2(embedder, storage, gallery, characters, candidates)
        if args.tier is None and not results["tier 2"]:
            heading("SUMMARY")
            print(
                "  Tier 2 failed: the model cannot identify characters in generated\n"
                "  images even when only one is present. Running tier 3 anyway to\n"
                "  show whether face size is the cause."
            )
    if args.tier in (None, 3):
        det_sizes = sorted({int(s) for s in args.det_sweep.split(",") if s.strip()})
        results["tier 3"] = tier3(
            embedder, storage, gallery, characters, candidates, det_sizes
        )

    heading("SUMMARY")
    for tier_name, passed in results.items():
        print(f"  {tier_name}: {'PASS' if passed else 'FAIL'}")
    all_passed = all(results.values())
    print(
        "\n  "
        + (
            "Build the feature."
            if all_passed
            else "Do not build the feature as specified; see the failing tier above."
        )
    )
    return 0 if all_passed else 1


if __name__ == "__main__":
    # insightface writes progress and provider noise straight to stdout.
    os.environ.setdefault("ORT_LOGGING_LEVEL", "3")
    sys.exit(main())
