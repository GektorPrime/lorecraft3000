# Operations

This is the operator runbook for a running LoreCraft3000 instance: how to back
it up, restore it, recover after a crash or interrupted migration, and check
that it is healthy. LoreCraft3000 runs on one computer, listens on
`127.0.0.1`, and stores everything in two local locations described below.

## The two stores must stay together

LoreCraft3000 keeps its state in two places:

- **The database** — a single SQLite file, `data/lorecraft.db` by default
  (override with `LORECRAFT_DB_PATH`). It holds characters, styles, reference
  sets, panels, generations, candidates, and image provenance rows.
- **The image store** — a content-addressed directory tree, `store/` by
  default (override with `LORECRAFT_STORE_ROOT`). It holds every image file and
  its JSON sidecar, named by the SHA-256 of the image bytes.

These are one logical unit. The database references images by hash; the image
store holds the bytes those hashes point at. **Always back up, restore, copy,
and move them together, and from the same moment in time.**

Restoring a database against a mismatched (older or newer) image store — or
vice versa — produces dangling references: rows that point at images the store
does not have, or images with no owning row. This is unsupported. If you move
the app to another machine, move both directories as a pair.

WAL note: with the default WAL journal mode, the live database is
`data/lorecraft.db` plus its `-wal` and `-shm` sidecar files. A file-copy
backup taken while the app is running must include a consistent snapshot (see
below), not just the main `.db` file.

## Backup

Prefer backing up while the app is **stopped** — it is the simplest way to get a
consistent snapshot of both stores at once.

1. Stop the app (Ctrl-C the `npm run dev` / uvicorn process).
2. Copy both locations together:

   ```bash
   cp data/lorecraft.db "backup/lorecraft-$(date +%Y%m%d-%H%M%S).db"
   cp -R store "backup/store-$(date +%Y%m%d-%H%M%S)"
   ```

If you must back up **without stopping** the app, use SQLite's online backup so
WAL content is folded in consistently, then copy the store immediately
afterward:

```bash
sqlite3 data/lorecraft.db ".backup 'backup/lorecraft.db'"
cp -R store backup/store
```

Because new images can be written between the database backup and the store
copy, a hot backup can contain store files with no matching row yet; that is
harmless (they are simply unreferenced). The dangerous direction — a row with
no image — is avoided by backing up the database first, then the store.

## Restore

1. Stop the app.
2. Replace **both** locations from the **same** backup pair:

   ```bash
   cp backup/lorecraft-YYYYMMDD-HHMMSS.db data/lorecraft.db
   rm -rf store && cp -R backup/store-YYYYMMDD-HHMMSS store
   ```

3. Start the app. Migrations run automatically at startup and are a no-op if the
   restored database is already current.
4. Verify with a consistency scan (read-only):

   ```bash
   python -m app.maintenance check
   ```

   A clean report exits `0`. If it reports issues, see
   [Storage consistency](#storage-consistency).

Never restore only one of the two stores.

## Shutdown during generation

A paid Gemini request may be in flight when the process stops. When that
happens the affected generation row is left in the `pending` state with its
budget reservation still held, and its panel stays locked (only one pending
generation is allowed per panel).

Recovery is automatic. On the next startup, the app runs stale-pending
recovery: any generation that has been `pending` longer than
`LORECRAFT_PENDING_STALE_SECONDS` (default 600s) is marked `failed`, which
releases the panel lock and stops the reservation from blocking new work.

- The reserved cost is retained on the failed row on purpose: after a process
  interruption the app cannot know whether the provider actually charged, so it
  does not silently reclaim the budget.
- The stale threshold is deliberately longer than the maximum provider retry
  duration, so an attempt that is legitimately still retrying is never expired.

To recover immediately instead of waiting for the threshold, simply restart the
app after the threshold has elapsed, or inspect the pending rows directly:

```bash
sqlite3 data/lorecraft.db \
  "SELECT id, scene_id, state, created_at FROM generation WHERE state='pending';"
```

## Migration recovery

Migrations run automatically when the backend starts. The entire run executes
inside a single `BEGIN IMMEDIATE` transaction:

- If two processes start at once, one applies all pending migrations and the
  other waits and then observes them already applied. No migration is ever
  applied twice.
- If a run is interrupted or fails partway, the whole transaction rolls back.
  Nothing is left partially applied, and restarting resumes cleanly from the
  same state.

Inspect which migrations are applied:

```bash
sqlite3 data/lorecraft.db "SELECT version, applied_at FROM schema_migrations;"
```

If startup fails with a migration error, the database is unchanged from before
that run. Fix the underlying cause (for example, a conflicting hand-created
table reported in the error) and restart; the migration re-runs from a clean
state.

## Storage consistency

The store can be scanned and repaired with the maintenance command. `check` is
read-only; `repair` changes nothing unless you pass `--yes`.

```bash
# Read-only report (exit 0 = clean, 1 = issues found).
python -m app.maintenance check

# Show what a repair would do, without changing anything.
python -m app.maintenance repair

# Apply safe repairs: rebuild missing/malformed sidecars from the image bytes
# and the database, and remove stale .tmp-* files.
python -m app.maintenance repair --yes
```

`check`/`repair` accept `--db` and `--store` to target a specific pair; without
them they use the configured settings. Repair never fabricates image bytes: a
missing or hash-mismatched image is reported as unfixable rather than guessed.

You can also have the app run a read-only scan at startup and log a summary by
setting `LORECRAFT_CONSISTENCY_CHECK_ON_STARTUP=true`. This never repairs
anything and never blocks startup.

## Character identity scoring

Every generated candidate is checked against the canonical reference gallery
for its panel's cast, and the best per-character similarity is stored as an
advisory score on the candidate (shown in the UI; it never blocks promotion).
Scoring needs InsightFace's `buffalo_l` model pack present locally. The pip
dependencies are installed normally by `uv sync`, but the ~320MB model pack is
a runtime asset that is provisioned once, explicitly — it is never downloaded
implicitly.

Provision it on a fresh machine:

```bash
# Check whether the pack is installed (exit 0 when ready).
python -m app.maintenance models status

# Fetch, verify, and install the pack under ~/.insightface/models/.
python -m app.maintenance models install
```

`install` is idempotent: it is a no-op when the pack is already present and
in one piece, and it downloads a new copy over a detected-truncated or missing
pack. The download is unpacked and verified off to the side and only then
swapped into place — a failed download or a pack that fails to load leaves the
previous install untouched. Re-fetch an already-installed pack with `--force`.

The app also checks the pack at startup (warn-only, never blocking) and skips
scoring with a logged warning if it is missing, rather than attempting a
background download on the hot path. Generation still succeeds; candidates
just carry no scores until the model is present.

Pre-feature data can be scored without regenerating anything:

```bash
# Embed canonical face references and score every candidate still lacking
# scores (references that predate the feature are embedded first).
python -m app.maintenance identity backfill

# Re-score everything, even already-scored candidates.
python -m app.maintenance identity backfill --force

# Only embed missing references, or only score candidates.
python -m app.maintenance identity backfill --scope refs
python -m app.maintenance identity backfill --scope candidates
```

The command exits `2` (after printing the reason) when insightface is not
installed or the model pack is missing, and `1` if any image could not be
processed — individual failures are logged and never abort the run.

## Health checks

The backend exposes two endpoints (both local-only, like the rest of the API):

- `GET /health/live` — liveness. Returns `200 {"status":"ok"}` whenever the
  process is up. Use this to answer "is it running?".
- `GET /health` — readiness. Verifies that the database is reachable, all
  migrations are applied, and the image store is present and writable, then
  returns `200` with a per-check breakdown, or `503` with the failing checks
  named. Use this to answer "can it actually serve requests?".

```bash
curl -s http://127.0.0.1:8000/health | python -m json.tool
```

Example not-ready response (HTTP 503):

```json
{
  "status": "not_ready",
  "checks": {
    "database": {"status": "ok"},
    "migrations": {"status": "error", "detail": "pending migrations: 011_..."},
    "storage": {"status": "ok"}
  }
}
```

Readiness is intentionally cheap and read-only: it runs a `SELECT 1`, compares
applied migrations against the expected set, and writes/removes a small probe
file under `store/.health/`. It never runs the full consistency scan and never
modifies your data.
