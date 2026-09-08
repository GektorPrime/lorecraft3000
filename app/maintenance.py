"""Storage consistency scan, repair, identity backfill, and model commands.

Usage::

    python -m app.maintenance check                  # read-only report
    python -m app.maintenance repair [--yes]         # apply safe repairs
    python -m app.maintenance identity backfill      # embed refs + score candidates
    python -m app.maintenance models status          # face-model state
    python -m app.maintenance models install         # fetch + verify the model pack

``check`` scans the store and the database, reports each defect class, and
exits nonzero when inconsistencies are found (so it can gate a backup or a
manual review). It never writes.

``repair`` is opt-in: without ``--yes`` it prints what it would do and changes
nothing; with ``--yes`` it removes stale ``.tmp-*`` files and reconstructs
missing or damaged sidecars — base metadata derived from the image file plus an
extension map, with the ``provenance`` list rebuilt from the authoritative
``image_provenance`` rows (Work Package 3). It never deletes user image bytes
and clearly reports every defect it declines to fix.

``identity backfill`` embeds face-role reference images that grew into the
library before face embedding existed — the canonical set plus any references
captured on past generations (so retired reference versions can still be scored
against) — then scores every candidate that lacks a stored identity payload (or
all of them with ``--force``), matching each candidate against the references
its request actually used. It requires the InsightFace model pack and leaves
candidates unfetchable without a face untouched instead of failing the whole
run.

``models`` provisions the ~326MB buffalo_l model pack that face embedding
needs: ``status`` reports whether it is installed, ``install`` fetches,
verifies, and atomically swaps it into place.  The model is never downloaded
implicitly, so a fresh environment uses ``models install`` as its first
identity-scoring step.

The scanner reuses ``ImageStorage``'s completeness definition so the scan and
the store always agree about what a readable image looks like.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.db import connect
from app.migrate import run_migrations
from app.services.identity import (
    BUFFALO_L_ZIP_URL,
    FACE_ROLES,
    MODEL_NAME,
    get_embedder,
    install_model,
    load_gallery_for_attachments,
    model_dir,
    model_status,
    score_generated_image,
    store_embeddings,
)
from app.storage import ImageStorage, _FORMAT_FROM_EXT

# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsistencyReport:
    """Results of a read-only consistency scan."""

    missing_sidecar: tuple[str, ...] = ()
    malformed_sidecar: tuple[str, ...] = ()
    hash_mismatch: tuple[str, ...] = ()
    sidecar_without_image: tuple[str, ...] = ()
    dangling_db_hashes: tuple[str, ...] = ()
    stale_temp_files: tuple[str, ...] = ()

    @property
    def issue_count(self) -> int:
        return (
            len(self.missing_sidecar)
            + len(self.malformed_sidecar)
            + len(self.hash_mismatch)
            + len(self.sidecar_without_image)
            + len(self.dangling_db_hashes)
            + len(self.stale_temp_files)
        )


@dataclass(frozen=True)
class RepairReport:
    """Results of a repair pass (``apply=False`` reports the plan only)."""

    sidecars_rebuilt: tuple[str, ...] = ()
    provenance_rebuilt_for: tuple[str, ...] = ()
    temp_files_removed: int = 0
    unfixable: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


def _sidecar_exists(storage: ImageStorage, sha256: str) -> bool:
    return (storage.root / sha256[:2] / f"{sha256}.json").is_file()


def _read_sidecar(
    storage: ImageStorage, sha256: str
) -> tuple[bool, dict | None]:
    """Load a sidecar as (exists, metadata).

    ``exists`` is True whenever the file is present, even when it cannot be
    parsed — so an unreadable sidecar is reported as *malformed*, not as
    *missing*.
    """
    sidecar_path = storage.root / sha256[:2] / f"{sha256}.json"
    try:
        text = sidecar_path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return False, None
    try:
        metadata = json.loads(text)
    except json.JSONDecodeError:
        return True, None
    return True, metadata if isinstance(metadata, dict) else None


def _bytes_match_hash(path: Path, sha256: str) -> bool:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == sha256
    except OSError:
        return False


def run_check(conn: sqlite3.Connection, storage: ImageStorage) -> ConsistencyReport:
    """Scan the store and database and classify every inconsistency found.

    The database hashes come from every table that references stored objects
    (``candidate``, ``ref_image``, uploaded ``base_stage`` rows, page renders,
    and the authoritative ``image_provenance``).
    """
    db_hashes = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT sha256 FROM candidate "
            "UNION SELECT DISTINCT sha256 FROM ref_image "
            "UNION SELECT uploaded_sha256 FROM base_stage "
            "WHERE uploaded_sha256 IS NOT NULL "
            "UNION SELECT DISTINCT sha256 FROM image_provenance"
            " UNION SELECT DISTINCT sha256 FROM page_render"
        ).fetchall()
    }

    missing: list[str] = []
    malformed: list[str] = []
    hash_mismatch: list[str] = []
    sidecar_orphans: list[str] = []

    for sha in storage.iter_hashes():
        image = storage.find_image(sha)
        if image is None:
            if _sidecar_exists(storage, sha):
                sidecar_orphans.append(sha)
            continue
        exists, metadata = _read_sidecar(storage, sha)
        if not exists:
            missing.append(sha)
            continue
        if metadata is None:
            malformed.append(sha)
            continue
        extension = metadata.get("extension")
        if not isinstance(extension, str) or not extension:
            malformed.append(sha)
            continue
        if image.name != f"{sha}.{extension}":
            malformed.append(sha)
            continue
        if not _bytes_match_hash(image, sha):
            hash_mismatch.append(sha)

    dangling = [sha for sha in db_hashes if storage.find_image(sha) is None]

    temp_files = (
        [str(p) for p in storage.root.rglob(".tmp-*") if p.is_file()]
        if storage.root.exists()
        else []
    )

    return ConsistencyReport(
        missing_sidecar=tuple(sorted(missing)),
        malformed_sidecar=tuple(sorted(malformed)),
        hash_mismatch=tuple(sorted(hash_mismatch)),
        sidecar_without_image=tuple(sorted(sidecar_orphans)),
        dangling_db_hashes=tuple(sorted(dangling)),
        stale_temp_files=tuple(sorted(temp_files)),
    )


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------


def _provenance_from_db(conn: sqlite3.Connection, sha256: str) -> list[dict]:
    """Rebuild a sidecar provenance list from the authoritative DB rows.

    The database persists only the fields needed for accountability, so rebuilt
    records are a subset of the full generation-time record. Order follows the
    insert order (``id``); the sidecar is a mirror, never the source of truth.
    """
    rows = conn.execute(
        "SELECT generation_id, interaction_id, prompt_hash, cost_cents, "
        "price_table_version, input_images, created_at "
        "FROM image_provenance WHERE sha256=? ORDER BY id",
        (sha256,),
    ).fetchall()
    records: list[dict] = []
    for row in rows:
        try:
            input_images = json.loads(row[5])
        except (TypeError, ValueError, json.JSONDecodeError):
            input_images = []
        records.append(
            {
                "generation_id": row[0],
                "interaction_id": row[1],
                "prompt_hash": row[2],
                "cost_cents": row[3],
                "price_table_version": row[4],
                "input_images": input_images,
                "created_at": row[6],
            }
        )
    return records


def _derive_sidecar(
    sha256: str, image: Path, existing: dict | None
) -> dict | None:
    """Reconstruct parseable base sidecar metadata from the image file.

    Returns None when the extension is unknown (no way to name the reconstructed
    sidecar safely), leaving the object to be reported as unfixable.
    """
    ext = image.suffix.lower().lstrip(".")
    fmt = _FORMAT_FROM_EXT.get(ext)
    if fmt is None:
        return None
    source_name = existing.get("source_name") if existing else None
    try:
        size = image.stat().st_size
    except OSError:
        return None
    return {
        "sha256": sha256,
        "extension": ext,
        "size": size,
        "format": fmt,
        "source_name": source_name,
    }


def run_repair(
    conn: sqlite3.Connection, storage: ImageStorage, *, apply: bool = False
) -> RepairReport:
    """Repair what is safe; report everything that is not.

    With ``apply=False`` (the default, matching the read-only bias of the
    command), nothing on disk is modified; the returned report describes what
    ``apply=True`` would do. Repairs never delete user image bytes.
    """
    report = run_check(conn, storage)

    rebuilt: list[str] = []
    provenance_rebuilt: list[str] = []
    for sha in sorted(set(report.missing_sidecar) | set(report.malformed_sidecar)):
        image = storage.find_image(sha)
        existing = _read_sidecar(storage, sha)[1]
        metadata = _derive_sidecar(sha, image, existing) if image else None
        if metadata is None:
            # Unrecoverable: no image file, or an extension no map entry names.
            continue
        provenance = _provenance_from_db(conn, sha)
        metadata["provenance"] = provenance
        if apply:
            storage.write_sidecar(sha, metadata)
        rebuilt.append(sha)
        if provenance:
            provenance_rebuilt.append(sha)

    temp_files = (
        [p for p in storage.root.rglob(".tmp-*") if p.is_file()]
        if storage.root.exists()
        else []
    )
    temp_removed = 0
    if apply:
        for path in temp_files:
            try:
                path.unlink()
                temp_removed += 1
            except OSError:
                pass

    unfixable = set()
    for sha in report.hash_mismatch:
        unfixable.add(f"{sha}: stored bytes fail the hash check (restore from originals)")
    for sha in set(report.dangling_db_hashes) | set(report.sidecar_without_image):
        unfixable.add(f"{sha}: image bytes are absent (restore from back-up)")
    for sha in sorted(set(report.missing_sidecar) | set(report.malformed_sidecar)):
        image = storage.find_image(sha)
        if image is None or _derive_sidecar(sha, image, None) is None:
            unfixable.add(
                f"{sha}: cannot reconstruct a sidecar (image missing or "
                "extension unknown)"
            )

    return RepairReport(
        sidecars_rebuilt=tuple(sorted(rebuilt)),
        provenance_rebuilt_for=tuple(sorted(provenance_rebuilt)),
        temp_files_removed=temp_removed,
        unfixable=tuple(sorted(unfixable)),
    )


# ---------------------------------------------------------------------------
# Identity backfill
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentityBackfillReport:
    """Results of an identity backfill pass."""

    refs_embedded: int = 0
    refs_no_face: tuple[str, ...] = ()
    candidates_scored: int = 0
    candidates_no_face: int = 0
    candidates_no_refs: int = 0
    candidates_skipped_bad_cast: int = 0
    errors: tuple[str, ...] = ()


def _candidate_cast_ids(
    request_json: str, scene_cast_json: str
) -> tuple[int, ...]:
    """Character ids a candidate was generated for, from captured request."""
    for raw in (request_json, scene_cast_json):
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        entries = payload.get("cast", []) if isinstance(payload, dict) else []
        ids = [
            int(entry["character_id"])
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("character_id"), int)
        ]
        if ids:
            return tuple(ids)
    return ()


def _candidate_attachments(request_json: str) -> list[dict]:
    """Reference-image captures recorded on a candidate's request.

    ``attachments`` carries ``character_id`` and ``sha256`` for every
    canonical reference the request used, on every path (direct scene, Base
    Stage scene, and candidate edit). These hashes let a candidate be scored
    against the exact references it was generated from, including references
    whose set has since been retired. Returns only dict entries.
    """
    if not request_json:
        return []
    try:
        payload = json.loads(request_json)
    except json.JSONDecodeError:
        return []
    attachments = payload.get("attachments", []) if isinstance(payload, dict) else []
    return [entry for entry in attachments if isinstance(entry, dict)]


def _referenced_ref_shas(conn: sqlite3.Connection) -> set[str]:
    """sha256 of every reference image any captured request used.

    Pulled from the ``attachments`` arrays of all stored ``request_json``
    payloads. Used to embed the references a candidate was scored against even
    after their reference set has been retired.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT json_extract(j.value, '$.sha256')
          FROM generation g
          JOIN json_each(g.request_json, '$.attachments') j
         WHERE g.request_json IS NOT NULL
           AND json_valid(g.request_json) = 1
        """
    ).fetchall()
    return {row[0] for row in rows if row[0] and isinstance(row[0], str)}


def run_identity_backfill(
    conn: sqlite3.Connection,
    storage: ImageStorage,
    *,
    scope: str = "all",
    force: bool = False,
) -> IdentityBackfillReport:
    """Embed canonical face references and score candidates without scores.

    Requires the optional InsightFace dependency (see app/services/identity.py);
    without it the report is returned empty and the caller reports the miss.
    Failures to embed or read a single image are counted as errors and never
    abort the run, mirroring the non-fatal bias of generation-time scoring.
    """
    embedder = get_embedder()
    if embedder is None:
        raise RuntimeError(
            "face checking is unavailable (insightface not installed, or the "
            "buffalo_l model pack is missing); run "
            "`python -m app.maintenance models install` first"
        )

    refs_embedded = 0
    refs_no_face: list[str] = []
    errors: list[str] = []

    if scope in ("all", "refs"):
        placeholders = ", ".join("?" for _ in FACE_ROLES)
        referenced = _referenced_ref_shas(conn)
        missing_refs = conn.execute(
            f"""
            SELECT ri.sha256, ri.role
              FROM ref_image ri
              JOIN ref_set rs ON rs.id = ri.ref_set_id
              LEFT JOIN face_embedding fe ON fe.sha256 = ri.sha256
             WHERE ri.role IN ({placeholders})
               AND fe.sha256 IS NULL
               AND (
                     rs.status = 'canonical'
                     OR ri.sha256 IN ({", ".join("?" for _ in referenced)})
               )
            """,
            (*FACE_ROLES, *sorted(referenced)),
        ).fetchall()
        for row in missing_refs:
            sha, role = row["sha256"], row["role"]
            try:
                data, _ = storage.read(sha)
            except Exception as exc:
                errors.append(f"ref {sha[:12]} unreadable: {exc}")
                continue
            vectors = (
                embedder.detect(data) if role == "turnaround" else [embedder.embed(data)]
            )
            vectors = [vector for vector in vectors if vector is not None]
            if not vectors:
                refs_no_face.append(f"{sha[:12]} ({role})")
                continue
            store_embeddings(conn, sha, vectors)
            refs_embedded += 1
            conn.commit()

    candidates_scored = 0
    candidates_no_face = 0
    candidates_no_refs = 0
    candidates_skipped_bad_cast = 0

    if scope in ("all", "candidates"):
        if force:
            where = ""
        else:
            where = "WHERE cd.identity_scores = '{}'"
        rows = conn.execute(
            f"""
            SELECT cd.id AS candidate_id, cd.sha256, g.request_json,
                   sc.cast_json
              FROM candidate cd
              JOIN generation g ON g.id = cd.generation_id
              JOIN scene sc ON sc.id = g.scene_id
            {where}
            """,
        ).fetchall()
        for row in rows:
            cast_ids = _candidate_cast_ids(row["request_json"], row["cast_json"])
            if not cast_ids:
                candidates_skipped_bad_cast += 1
                continue
            # Score against the references captured on the request, not the
            # currently-canonical sets: a candidate is compared with the faces
            # it was actually generated from, regardless of later retirement.
            gallery = load_gallery_for_attachments(
                conn, _candidate_attachments(row["request_json"])
            )
            if not gallery:
                candidates_no_refs += 1
                continue
            try:
                data, _ = storage.read(row["sha256"])
            except Exception as exc:
                errors.append(f"candidate {row['candidate_id']} unreadable: {exc}")
                continue
            payload = score_generated_image(
                embedder, gallery, data, tuple(cast_ids)
            )
            if payload is None:
                candidates_no_face += 1
                continue
            with conn:
                conn.execute(
                    "UPDATE candidate SET identity_scores = ? WHERE id = ?",
                    (json.dumps(payload, sort_keys=True), row["candidate_id"]),
                )
            candidates_scored += 1

    return IdentityBackfillReport(
        refs_embedded=refs_embedded,
        refs_no_face=tuple(sorted(refs_no_face)),
        candidates_scored=candidates_scored,
        candidates_no_face=candidates_no_face,
        candidates_no_refs=candidates_no_refs,
        candidates_skipped_bad_cast=candidates_skipped_bad_cast,
        errors=tuple(sorted(errors)),
    )


def _print_identity_backfill(report: IdentityBackfillReport) -> None:
    print(f"  reference embeddings written:  {report.refs_embedded}")
    if report.refs_no_face:
        print(f"  references with no face:      {len(report.refs_no_face)}")
        for item in report.refs_no_face:
            print(f"    no face: {item}")
    print(f"  candidates scored:             {report.candidates_scored}")
    print(f"  candidates with no face:       {report.candidates_no_face}")
    print(f"  candidates with no refs:       {report.candidates_no_refs}")
    print(f"  candidates skipped (no cast):  {report.candidates_skipped_bad_cast}")
    if report.errors:
        print(f"  errors:                        {len(report.errors)}")
        for error in report.errors:
            print(f"    {error}")


# ---------------------------------------------------------------------------
# Model provisioning
# ---------------------------------------------------------------------------


def _print_model_status() -> int:
    """Print the face-model state; returns a process exit code."""
    status = model_status()
    if status["state"] == "ok":
        print(f"{MODEL_NAME} model pack installed ({status['path']})")
        return 0
    print(f"{MODEL_NAME} model pack is {status['state']} ({status['path']})")
    missing = [name for name, present in status["files"].items() if not present]
    present = [name for name, present in status["files"].items() if present]
    if present:
        print(f"  present: {', '.join(present)}")
    if missing:
        print(f"  missing: {', '.join(missing)}")
    print("  run `python -m app.maintenance models install` to fix this")
    return 1


def _download_hook():
    """URL-retrieve reporthook that prints a throttled percentage."""
    last = {"pct": -1}

    def hook(count: int, block_size: int, total_size: int) -> None:
        if total_size <= 0:
            return
        pct = int(count * block_size * 100 / total_size)
        if pct >= last["pct"] + 10 or pct >= 100:
            print(f"  {min(pct, 100):3d}%", flush=True)
            last["pct"] = pct

    return hook


def _run_models_install(force: bool, url: str | None) -> int:
    print(f"installing {MODEL_NAME} model pack ...")
    try:
        install_model(
            url=url or BUFFALO_L_ZIP_URL,
            progress=_download_hook(),
            verify=True,
            force=force,
        )
    except Exception as exc:
        print(f"model install failed: {exc}", file=sys.stderr)
        return 1
    print(f"installed {MODEL_NAME} to {model_dir()}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_report(report: ConsistencyReport) -> None:
    """Print a human-readable consistency report; count lines match issues."""
    def emit(label: str, items) -> None:
        for item in items:
            print(f"  {label}: {item}")

    if report.issue_count == 0:
        print("store is consistent: no issues found")
        return
    print(f"{report.issue_count} issue(s) found:")
    emit("missing sidecar", report.missing_sidecar)
    emit("malformed sidecar", report.malformed_sidecar)
    emit("hash mismatch", report.hash_mismatch)
    emit("sidecar without image", report.sidecar_without_image)
    emit("dangling database hash", report.dangling_db_hashes)
    emit("stale temp file", report.stale_temp_files)


def _print_repair(report: RepairReport) -> None:
    if report.unfixable:
        print(f"declined to fix {len(report.unfixable)} item(s):")
        for item in report.unfixable:
            print(f"  unfixable: {item}")
    if report.sidecars_rebuilt:
        print(f"rebuilt {len(report.sidecars_rebuilt)} sidecar(s):")
        for sha in report.sidecars_rebuilt:
            print(f"  sidecar: {sha}")
    if report.provenance_rebuilt_for:
        print(f"rebuilt provenance from database for {len(report.provenance_rebuilt_for)} object(s)")
    if report.temp_files_removed:
        print(f"removed {report.temp_files_removed} stale temp file(s)")


def _describe_repair_plan(report: RepairReport) -> None:
    if report.sidecars_rebuilt:
        print(f"would rebuild {len(report.sidecars_rebuilt)} sidecar(s)")
    if report.provenance_rebuilt_for:
        print(f"would rebuild provenance for {len(report.provenance_rebuilt_for)} object(s)")
    if report.temp_files_removed:
        print(f"would remove {len(report.temp_files_removed)} stale temp file(s)")
    if report.unfixable:
        print(f"would decline to fix {len(report.unfixable)} item(s)")


def main(argv: list[str] | None = None) -> int:
    """Entrypoint for ``python -m app.maintenance``. Returns an exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m app.maintenance",
        description="LoreCraft3000 storage consistency scan and repair.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    parser_check = subparsers.add_parser("check", help="read-only consistency report")
    parser_repair = subparsers.add_parser("repair", help="safe repairs (opt-in)")
    for command_parser in (parser_check, parser_repair):
        command_parser.add_argument("--db", help="SQLite database path (defaults to settings)")
        command_parser.add_argument("--store", help="store root (defaults to settings)")
    parser_check.set_defaults(apply=False)
    parser_repair.add_argument(
        "--yes",
        action="store_true",
        help="apply repairs; without this flag only a dry-run plan is printed",
    )
    parser_identity = subparsers.add_parser(
        "identity", help="face-embedding and identity-score maintenance"
    )
    identity_sub = parser_identity.add_subparsers(dest="identity_command", required=True)
    parser_backfill = identity_sub.add_parser(
        "backfill",
        help="embed references and score candidates that predate face checking",
    )
    parser_backfill.add_argument("--db", help="SQLite database path (defaults to settings)")
    parser_backfill.add_argument("--store", help="store root (defaults to settings)")
    parser_backfill.add_argument(
        "--scope", choices=("all", "refs", "candidates"), default="all",
        help="which objects to process (default all)",
    )
    parser_backfill.add_argument(
        "--force",
        action="store_true",
        help="recompute identity scores for every candidate, not just unscored ones",
    )
    parser_models = subparsers.add_parser(
        "models", help="provision the InsightFace model pack used for identity scoring"
    )
    models_sub = parser_models.add_subparsers(dest="models_command", required=True)
    models_sub.add_parser("status", help="report whether the model pack is installed")
    parser_models_install = models_sub.add_parser(
        "install", help="fetch, verify, and install the model pack"
    )
    parser_models_install.add_argument(
        "--url", help="override the model pack download URL",
    )
    parser_models_install.add_argument(
        "--force",
        action="store_true",
        help="re-download even if the pack is already installed",
    )
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if args.command == "models":
        if args.models_command == "status":
            return _print_model_status()
        return _run_models_install(force=args.force, url=args.url)

    db_path = Path(args.db) if args.db else settings.db_path
    store_root = Path(args.store) if args.store else settings.store_root

    run_migrations(
        db_path,
        journal_mode=settings.sqlite_journal_mode,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        synchronous=settings.sqlite_synchronous,
    )
    conn = connect(
        db_path,
        journal_mode=settings.sqlite_journal_mode,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        synchronous=settings.sqlite_synchronous,
    )
    try:
        storage = ImageStorage(store_root)
        if args.command == "check":
            report = run_check(conn, storage)
            _print_report(report)
            return 1 if report.issue_count else 0
        if args.command == "identity":
            try:
                report = run_identity_backfill(
                    conn,
                    storage,
                    scope=args.scope,
                    force=args.force,
                )
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            _print_identity_backfill(report)
            return 1 if report.errors else 0
        plan = run_repair(conn, storage, apply=False)
        if not args.yes:
            print("dry run; pass --yes to apply")
            _describe_repair_plan(plan)
            return 0
        result = run_repair(conn, storage, apply=True)
        _print_repair(result)
        return 1 if result.unfixable else 0
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
