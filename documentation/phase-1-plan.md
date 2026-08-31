# LoreCraft3000 — Phase 1 Implementation Plan

## Objective

Build the smallest useful local application around the Phase 0-validated workflow:

Select the cast of characters and their canonical references -> describe a panel -> assemble a disciplined multi-character prompt -> enforce spending limits -> generate one image -> preserve complete provenance -> review it manually.

No automated verification, best-of-N, page layout, lettering, authentication, or cloud deployment yet.

## Scope decisions (locked)

- Multi-character panels are first-class from day one, both architecturally and functionally. The data model, prompt assembler, and reference-slot budgeter all treat a panel's cast as an ordered list of N characters from the start.
- Daily spend cap: $3/day, configurable via .env, hard-enforced in our own code before every paid provider call.
- Visual-contract ceiling: 60 words per character (deterministic, no tokenizer dependency for MVP).
- Default model gemini-3.1-flash-image @ 1K for small casts; recommend/select Pro (gemini-3-pro-image) when the cast is large (>=3 named characters) or reference capacity requires it, subject to the daily cap.

## Foundation from Phase 0

- Victorian oil-painting references materially improved facial consistency (kill-criterion passed by human inspection).
- Seeds proven NON-deterministic for gemini-3.1-flash-image; provenance relies on stored image bytes + full request, never on re-running a seed.
- gemini-3.1-flash-image rejects per-image `resolution`; the provider must apply model-specific capabilities (omit resolution for Flash; allow it for Pro).
- Project already has git, uv, .venv, dotenv loading, and secret hygiene.

## Definition: panel

A panel is one illustrated comic frame — one drawn box on a comic page, showing one camera shot of one moment. In this tool, one panel = one image-generation request. The app does NOT arrange panels into page layouts; that is out of scope. Finished images are exported for a separate art tool.

## Multi-character requirement

- A panel's cast is an ordered list of characters, each with its own canonical ref-set version and a role/prominence.
- The prompt assembler declares EACH character's reference images explicitly with non-overlapping image ranges (e.g. "Images 1-2 are CHARACTER A ... Images 3-4 are CHARACTER B ...") to prevent the model from blending identities.
- A reference-slot budgeter allocates the model's finite reference capacity across the whole cast. When the cast cannot fit, it FAILS LOUDLY with an actionable recommendation (switch to Pro, or split the panel) — it never silently drops a character or truncates refs.
- The generation preview shows the per-character slot allocation before any spend.
- Provenance records the full cast, each character's ref-set version, and the exact slot allocation used.

## Milestones

### Milestone 0 — preserve Phase 0 baseline as history-free experiment
Phase 0 is treated as a discarded experiment; the new repo starts fresh (no Phase 0 commit history). Keep out/ ignored locally.

### Milestone 1 — application skeleton
Add Phase 1 runtime/dev dependencies (FastAPI, Uvicorn, python-multipart, template engine, pytest + HTTP test support). Establish a clear structure by responsibility: app startup/routes, domain/services, SQLite persistence + migrations, provider adapters, prompt assembly, content-addressed storage, templates/static CSS, tests. Keep validate_refs.py as a separate Phase 0 utility. Deliverable: server starts, DB initializes, home route works.

### Milestone 2 — SQLite schema and invariants
Migrations for character, ref_set, ref_image, style, scene, generation, candidate (verification deferred to Phase 2). Enforce: character slug uniqueness; ref-set version uniqueness per character; exactly one canonical set per character; canonical sets immutable; referential integrity on; monetary values stored as integer minor units (not float); generation state distinguishes pending/succeeded/failed. Deliverable: migration + repository tests.

### Milestone 3 — content-addressed image storage
Storage service: validate uploads, decode/verify with Pillow, SHA-256 of original bytes, store under store/<sha256[:2]>/<sha256>.<ext>, dedupe, atomic JSON sidecars, return metadata for DB, never store bytes in SQLite. Sidecars carry enough to rebuild the index (no secrets). Deliverable: upload/storage/dedupe/rebuild tests.

### Milestone 4 — character and style library
HTMX server-rendered pages: character list/create/edit/detail, style create/edit, a Victorian oil-painting default style. Enforce lore_md (local only, never sent) vs visual_contract (model-facing, 60-word cap) vs negative_traits (provider-facing). Deliverable: character/style CRUD via UI + service tests.

### Milestone 5 — reference-set versioning
Draft ref-set creation, image upload + role assignment (face_front|face_3q|face_profile|full_body|expression|outfit), draft editing, canonical promotion (single transaction), prior-canonical retirement, immutable canonical history, new-draft-from-existing. Deliverable: a user can create and canonize a usable multi-character-ready Victorian ref set.

### Milestone 6 — multi-character prompt assembler
Pure, provider-independent. Input: model capabilities, ordered cast, per-character canonical ref-sets + visual contracts, scene, camera/framing, style contract, output constraints. Output: exact assembled text, ordered image attachments with declared roles and non-overlapping per-character ranges, ref-set versions, validation metadata, stable prompt_hash material. Requirements: fixed section order/phrasing; every image explicitly declared and attributed to exactly one character; lore excluded; no silent truncation; no silently dropped characters/refs; always prohibit lettering; model-aware reference capacity via the slot budgeter; deterministic for identical inputs. Deliverable: unit tests incl. golden multi-character prompt fixtures and slot-budget failure cases.

### Milestone 7 — provider boundary
Thin provider interface; Gemini adapter behind it. Adapter owns SDK request construction, model capability differences (Flash omits resolution; Pro allows it), base64/reference serialization, Interactions API call, response extraction, interaction IDs, error normalization, sanitized request capture (no secrets/keys). Routes never call google-genai directly. One candidate per request; no seed-reproducibility reliance. Deliverable: fake-provider tests + a separately-marked live integration test that never runs by default.

### Milestone 8 — cost guard and ledger
Before every provider call: estimate cost, sum current-day recorded/reserved spend, reject if new call exceeds the $3 daily ceiling, reserve the estimate transactionally, reconcile after success/failure. Config: daily ceiling, model price table + version, default model, default image size. UI shows estimated spend before confirmation. Deliverable: concurrent/repeated requests cannot bypass the hard cap.

### Milestone 9 — generation and provenance
Orchestration: validate scene + per-character canonical refs, assemble prompt, compute prompt_hash, check/reserve cost, persist pending generation, call provider, store output bytes + sidecar, create candidate, persist sanitized request/response metadata, mark success/failure + reconcile cost. Sidecar identifies at least: sha256, generation id, full cast + per-character ref-set versions, model + params, assembled prompt, ordered input-image hashes with per-character attribution, slot allocation used, prompt_hash, interaction id, timestamp, cost, provider/request schema version. No secret-bearing headers in provenance. Deliverable: full vertical path on a fake provider, then one manually authorized live smoke test.

### Milestone 10 — manual review UI
Scene create form (multi-character cast), prompt/cost/slot-allocation preview, explicit generate action, generation detail, candidate image, accept/reject status (accept does NOT promote to ref set), full provenance view, daily spend summary. No ranking or identity scoring in Phase 1.

### Milestone 11 — stabilization
Unit tests (assembler incl. multi-character + slot budgeter, storage, cost guard, invariants); route/service integration tests; provider error/timeout handling; file/DB consistency; upload size + MIME validation; basic form error states; README with exact uv startup instructions; frozen benchmark fixture structure (no full benchmark spend yet).

## Reviewable slices (implementation order)

1. Foundation — app skeleton, config, SQLite migrations, content-addressed storage.
2. Library — character/style CRUD and immutable multi-character-ready reference-set workflow.
3. Generation core — multi-character assembler, slot budgeter, provider adapter, cost guard, provenance.
4. Vertical UI — multi-character scene form, preview (with slot allocation), generate, review, end-to-end tests.

Each slice remains runnable and independently testable. Each slice has a GitHub issue opened before its implementation starts.

## Locked parameters

- Daily budget cap: $3/day (configurable via .env).
- Visual-contract ceiling: 60 words per character.
- Cast handling: multi-character from day one; slot budgeter fails loudly when the cast cannot fit, recommending Pro or a panel split.