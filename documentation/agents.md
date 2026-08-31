# Character Canon

A locally hosted tool for generating comic panels with **persistent character identity**.
Single user, runs on localhost, no auth, no cloud deployment.

## The problem

Consumer image tools cannot reliably reproduce the same character across images. They
discard reference images between requests, and long text descriptions ("brown hair, blue
eyes, mid-thirties") describe millions of people while actively competing with reference
conditioning.

**This is already proven to work manually.** Attaching a curated reference sheet to a chat
and naming it in the prompt produces consistent characters. This project automates and
versions that workflow — it does not invent a new capability.

## What this app actually provides

Not "context the model lacks." It provides:

1. **Curation** — a frozen canonical reference set per character
2. **Persistence** — reuse the exact same refs and phrasing across months
3. **Discipline** — a prompt assembler that resists description dilution
4. **Selection** — generate N, rank them, keep the best
5. **Provenance** — the exact request behind every image, forever

---

## Verified API facts (checked 2026-08-30 — re-verify before relying on these)

### Models

| Model | ID | Refs | Sizes | ~$/image |
|---|---|---|---|---|
| Nano Banana 2 Lite | `gemini-3.1-flash-lite-image` | 14 object | 1K | 0.034 |
| Nano Banana 2 | `gemini-3.1-flash-image` | ~4 char / 10 object | 512, 1K, 2K, 4K | 0.045–0.151 |
| Nano Banana Pro | `gemini-3-pro-image` | ~5 char / 6 object / 3 style | 1K, 2K, 4K | 0.134–0.24 |
| Nano Banana (legacy) | `gemini-2.5-flash-image` | — | 1K | — |

Default to **3.1 Flash @ 1K** for drafts. Use **3 Pro** for hero panels and scenes with 3+
named characters. Batch API is roughly half price.

**No free tier on any image model.** Billing must be enabled (Tier 1). Every output carries
a SynthID watermark.

### SDK — verified against `google-genai` 2.20.0 by introspection

The image API is the **Interactions API**, not `generate_content`. Do not use
`client.models.generate_content` for images.

```python
from google import genai
client = genai.Client()   # reads GEMINI_API_KEY

interaction = client.interactions.create(
    model="gemini-3.1-flash-image",
    input=[
        {"type": "text", "text": prompt},
        {"type": "image", "data": b64_str, "mime_type": "image/png",
         "resolution": "high"},
    ],
    response_format={"type": "image", "aspect_ratio": "3:2", "image_size": "1K"},
    generation_config={"seed": 12345},
    store=False,
    labels={"scene": "p01_04"},
)
png_bytes = base64.b64decode(interaction.output_image.data)
```

Confirmed field shapes:

- `ImageContentParam`: `data` (base64 str | file-like | path), `mime_type`, `uri`,
  `resolution` ∈ `low|medium|high|ultra_high` — how much detail the model reads from the
  reference.
  - **`gemini-3.1-flash-image` does NOT support per-image `resolution`.** Sending it is
    rejected server-side with HTTP 400 ("Media resolution is not supported for model
    'gemini-3.1-flash-image'"). Omit the `resolution` key for that model; refs are then
    read at the model's default detail.
  - Use `resolution: "high"` only for models that actually support the field (e.g.
    `gemini-3-pro-image`). There is no universal "always high for character refs" rule —
    the supported value depends on the model.
- `ImageResponseFormatParam`: `aspect_ratio` ∈ `1:1 2:3 3:2 3:4 4:3 4:5 5:4 9:16 16:9 21:9
  1:8 8:1 1:4 4:1`, `image_size` ∈ `512 | 1K | 2K | 4K`, `delivery` ∈ `inline|uri`
- `create(...)` top level: `input`, `model`, `system_instruction`, `response_format`,
  `generation_config`, `previous_interaction_id`, `store`, `labels`, `safety_settings`,
  `service_tier`, `response_modalities`, `tools`, `background`, `stream`
- `generation_config`: `seed`, `image_config`, `thinking_level`, `max_output_tokens`, …

### What does NOT exist — do not invent it

- **No role-tagging parameter.** There is no field marking an image as a character vs style
  vs object reference. You declare the role **in the prompt text**: "Image 1–3 are
  reference photographs of the same character, ELIAS." The 4/5/3 numbers above are
  guidance on what the model handles well, not typed slots.
- **No candidate-count parameter.** Best-of-N means N separate calls at N× cost.
- **Seed exists but is unverified for image models.** Test it (same seed twice → compare
  SHA-256). If it pins output, use it everywhere and record it. If not, remove the
  reproducibility claims from the design.
  - **Verified result (2026-08-30):** seed is **NOT deterministic** for
    `gemini-3.1-flash-image` image output (tested twice, same seed + same prompt, compared
    SHA-256 — different both times). Reproducibility-via-seed claims are therefore dropped;
    provenance relies on stored image bytes + the full request, not on re-running a seed.

---

## Non-negotiable design principles

1. **References are the canon, not the model.** The model will be deprecated (2.5 Flash
   Image already is). Your canon is the reference images on disk. Provider goes behind a
   thin adapter interface.
2. **Never auto-promote a generated image into a reference set.** Feeding outputs back in
   makes characters drift into someone else, untraceably. Promotion is manual, deliberate,
   and produces a new immutable ref-set version. Keep v1 forever.
3. **Bio ≠ prompt.** Split `lore_md` (never sent) from `visual_contract` (sent, hard-capped
   at 40–80 tokens, discriminative traits only). Generic attributes belong in the images.
4. **The assembler fails loudly.** If the contract exceeds the token ceiling, or reference
   slots can't fit the cast, raise — never silently truncate or drop a character.
5. **Never generate lettering.** No speech bubbles, captions, or text in-image. Clean art
   only; lettering happens in a separate layer in Krita/Clip Studio.
6. **Rank, don't gate.** Verification orders the review queue. Auto-reject only on
   objective structural failures. A human accepts every panel.
7. **Cost guard before the HTTP call.** Check a daily ceiling in our own code — AI Studio
   spend caps lag ~10 minutes and are not a wall.
8. **No automation of the Gemini web app.** Against its terms, fragile, and risks the
   Google account. API or local models only.

---

## Architecture

```
Character Library ─┐
Style Bible ───────┼─→ Prompt Assembler ─→ Provider Adapter ─→ Gemini Interactions API
Scene / Panel ─────┘         ↑                                          │
                             │                                          ↓
                    (tightened retry)                            N candidates
                             │                                          │
                             └──────────── Verifier (rank) ←────────────┘
                                                  │
                                                  ↓
                                           Review Queue → manual promotion only
```

## Stack

- Python 3.11+, FastAPI, SQLite (stdlib `sqlite3`, no ORM needed at this size), HTMX +
  vanilla CSS for the UI. Pillow for image work.
- `pip install google-genai pillow fastapi uvicorn python-multipart`
- Images are **content-addressed on disk**, never in the DB:
  `store/<sha256[:2]>/<sha256>.png` plus a `.json` sidecar. The DB holds pointers so the
  index can be rebuilt from the filesystem.

## Data model

```sql
character      id, name, slug, lore_md, visual_contract, negative_traits,
               default_style_id, created_at
ref_set        id, character_id, version, status  -- draft|canonical|retired
                                                  -- exactly one canonical per character
ref_image      id, ref_set_id, sha256, role, weight, embedding, quality_flags
               -- role: face_front|face_3q|face_profile|full_body|expression|outfit
style          id, name, style_contract, ref_image_ids
scene          id, project_id, page, panel_no, beat_text, camera, framing,
               mood, aspect_ratio, cast_json
generation     id, scene_id, model, params_json, prompt_hash, request_json,
               cost_usd, parent_generation_id, interaction_id, created_at
candidate      id, generation_id, sha256, idx
verification   id, candidate_id, character_id, method, method_version,
               score, verdict, detail_json
```

`prompt_hash` covers model + params + ref-set version + assembled text. It gives free
deduplication, an honest cost ledger, and the ability to answer "what exactly did I send
when this one came out perfect?" six weeks later.

## Prompt assembly contract

Fixed order, fixed phrasing, one template. Consistency across generations is partly
consistency of our own prompt shape.

1. **Reference declaration** — name every attached image and its role explicitly:
   `"Image 1–3 are reference photographs of the same character, ELIAS. Match this
   character's face and build exactly."` Unlabelled image soup is the main cause of the
   model blending two characters into one.
2. **Visual contract** — the character's discriminative traits, under the token ceiling.
3. **Scene** — action and staging.
4. **Camera** — framing, angle, distance.
5. **Style** — from the style bible, verbatim and identical every time.
6. **Constraints** — `"Single figure. No text, no speech bubbles, no captions, no watermark."`

Slot budgeting: with ~4 usable character refs, a two-hander gets 2 refs each, not 3. If the
cast doesn't fit, tell the user to switch to Pro or split the panel — never silently drop.

## Verification (Phase 2 — not before)

Three tiers, pluggable because the art style is undecided:

- **Tier 1, free, always** — face count vs cast size; reject blurred or sub-64px face
  crops; LAB-space palette check on fixed colours; perceptual hash against prior panels.
- **Tier 2, local, ~50ms** — embedding cosine on the *tight face crop*, never the whole
  panel. ArcFace-class for photoreal; **DINOv2 for stylized art, where face-recognition
  models degrade badly.** Report margin against other characters, not just raw score.
  Note: InsightFace pretrained weights are non-commercial licensed.
- **Tier 3, ~$0.001, on demand** — VLM rubric judge. Send canonical ref + candidate crop to
  a text Gemini model with structured output. Ask **per trait** with boolean + evidence
  ("Is the scar present on the left brow?"). Holistic 1–10 scores from VLMs are noise.

**Calibration is mandatory.** Per character: 20 confirmed-correct renders and 20 hard
negatives (other characters + rejected drifts). Derive the threshold from that data, store
it on the character with a `method_version`. Thresholds do not transfer between characters,
styles, or model versions. Grey out scores whose method_version is stale.

## Build phases

**Phase 0 — spike (do this first, ~$1).** `scripts/validate_refs.py` already exists: three
scenes generated two ways, with references attached vs text-only, plus a seed-determinism
check. Writes a contact sheet and a manifest. *Kill criterion:* if the with-references arm
isn't visibly more consistent, stop and reconsider before building anything.

**Phase 0 result — PASSED (checked 2026-08-30).** The spike was run for real against three
Victorian oil-painting reference images using `validate_refs.py`, model
`gemini-3.1-flash-image` @ 1K. Two separate spike executions were done; each execution
itself contained the A/B comparison (with-references vs text-only). The second execution
used a character description and reference declaration matched to the actual references,
and its decisive contact sheet is at
`/Volumes/dev/LoreCraft3000/out/20260831-014945/` (path date is UTC). ~$0.94 was the cost
of that decisive Victorian execution, not cumulative spend across both executions.
Conclusion: generations **with** references preserve the character's facial features better
than text-only, so the kill-criterion is passed — proceed to build. The kill-criterion pass
was decided by human visual inspection of the decisive contact sheet at
`/Volumes/dev/LoreCraft3000/out/20260831-014945/_compare.png`; there was no automated
metric or manifest verdict. Caveat: the references themselves were not perfectly
identity-consistent (two of the three contained other people/distractors), so this is
"references preserve facial features better than text-only," not a flawless identity lock.
The text-only arm tended to converge toward the same archetype late in a run because the
written description + fixed style are detailed, but that convergence is stylistic, not
identity preservation.

**Phase 1 — library and generate (~1 week).** Character CRUD, reference upload with role
tagging, canonical ref-set versioning, the prompt assembler, generation with full
request/response capture, cost ledger with a hard daily cap. No verification yet — this
alone is most of the value.

**Phase 2 — best-of-N and ranking (~1 week).** N candidates per scene, Tier 1 + Tier 2,
sorted review queue, per-character calibration sets and threshold picker. Tier 3 behind a
button, off by default.

**Phase 3 — continuity and pages (~1 week).** Panel sequences via `previous_interaction_id`
(requires `store=True`), scene templates, outfit and expression variants, batch generation
of a page's shot list, export to a folder an art tool can open.

**Keep a frozen benchmark.** 20 fixed scene prompts × 3 characters, committed to the repo.
Re-run whenever the prompt template, model, or a reference set changes, and diff against
the stored previous run. Without it, changes that feel like improvements can't be
distinguished from noise.

## Conventions

- `GEMINI_API_KEY` from environment only. `.env` and `store/` and `out/` in `.gitignore`
  before the first commit.
- Every provider call goes through the adapter — no direct SDK calls in route handlers.
- Log the full request JSON for every generation. Storage is cheap; a lost prompt isn't.
- Prefer boring, readable code. This is a single-user local tool, not a platform.

## Scope boundaries

Do **not** build: a page-layout editor, a letterer, a canvas, multi-user auth, or cloud
deployment. Export files and let existing art tools do their jobs.

## Open decisions

1. **Art style** — **DECIDED: Victorian-era oil painting.** This is stylized, not photoreal,
   so the Phase 2 Tier-2 verifier should default to the stylized path (DINOv2) rather than
   face-recognition embeddings. Ref sets get bootstrapped accordingly.
2. **Ref-set bootstrap** — generated turnarounds we curate, hand drawings, or photo
   references. Different drift and rights characteristics.
3. **Monthly budget ceiling** — determines N in best-of-N, default resolution, and whether
   Pro is hero-panels-only.
