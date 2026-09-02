---
name: stage-new-panel
description: Use when the user asks for the text artifacts to fill the "Stage new panel" form in LoreCraft3000 (also triggered by "new panel", "panel text", "stage a panel", "create a panel for <character>"). Produces ready-to-paste text for Action, Camera, Shot framing, Mood, and a recommended aspect ratio / style / model / image size / cast, after verifying which characters and styles already exist so the artifacts reference real data.
---

# Stage new panel — text artifacts

Produce the per-field copy a user can paste into the **Stage new panel** form
(`frontend/src/pages/panels/PanelFormPage.tsx`) so the panel can be generated.
The output is TEXT ARTIFACTS — never a route call, never a DB write. The user
pastes each block into the matching form field themselves.

## Field semantics (fixed by the form, do not deviate)

| Form field | Field name | Meaning | Required |
| ---------- | ---------- | ------- | -------- |
| Action | `beat_text` | What IS happening — the beat/action. NOT the camera. Example: "Elias draws his sword as Mara backs toward the door." | yes |
| Camera | `camera` | Viewer's position + angle. NOT the crop. Example: "low angle, looking up", "eye level, three-quarter view from the left". | yes |
| Shot framing | `framing` | How tightly cropped. NOT the angle. Example: "medium close-up, head and shoulders only", "wide shot, full room visible". | yes |
| Mood | `mood` | Optional tone/atmosphere. Example: "tense, candlelit". | no |
| Aspect ratio | `aspect_ratio` | Shape of the image, from the options list. | yes |
| Style | `style_id` | A style that already exists; its contract is sent verbatim. | yes |
| Model | `model` | One of the configured models. Higher-capacity = bigger casts/more cost. | yes |
| Image size | `image_size` | Output resolution. Example: "1K" draft, "2K"/"4K" final. | yes |
| Cast | `cast` | Existing characters + per-member role and prominence. | yes (unless deliberately empty) |

## Workflow

1. **Verify real data before writing artifacts.** Read the current characters,
   styles, and options so the recommendations are grounded:
   - Characters: GET `/api/v1/characters` (see `listCharacters` in
     `frontend/src/api/client.ts`)
   - Styles: GET `/api/v1/styles` (see `listStyles`)
   - Options: GET `/api/v1/options/summary` (models, aspect_ratios, image_sizes,
     default_model, default_image_size)
   - Offline fallback: `python -c "import sqlite3;c=sqlite3.connect('data/lorecraft.db');print(c.execute('select name,slug from character').fetchall())"` and the same for `style`. If the server is unreachable and the DB is unreadable, say so and use the user's intent directly.
2. If a character the user names is NOT in the list, flag it: the Cast selector
   only offers existing characters, and each character needs its ref-set
   portrait upload before generation. Do not silently invent a cast member.
3. Generate the artifacts. For a **portrait**, recommend `3:4`; for a wide
   cinematic beat recommend `16:9`; for a typical panel keep the current aspect.
4. Ask nothing unless truly ambiguous (e.g. unnamed characters). Prefer
   proceeding with sensible defaults the user can tweak.

## Output format

Return the artifacts as a short field-by-field list with one **bold** field
label followed by a paste-ready block. Keep prose to a minimum.

**Action**
```
<1–3 sentences: the concrete action/beat. Present scene, nouns and verbs, no camera direction.>
```

**Camera**
```
<viewer position + angle, e.g. "eye level, straight-on, directly facing the viewer">
```

**Shot framing**
```
<frame crop, e.g. "tight portrait framing, head and shoulders only, subject centered">
```

**Mood**
```
<tone/atmosphere, omit the block entirely if none>
```

**Aspect ratio / Style / Model / Image size / Cast**
```
<one clear value each, drawn from the verified lists>
```

## Constraints

- Never fabricate API endpoints or field names; they are fixed in
  `PanelFormPage.tsx` and `PanelInput` in `app/schemas.py`.
- The character's dress/face contract lives on the Character (`visual_contract`,
  hard-capped at ≤ 60 words) — do NOT re-inject appearance into `beat_text`
  unless the user asks. The panel text is action + camera + framing + mood.
- `beat_text` is action, `camera` is position/angle, `framing` is crop; mixing
  these up is the most common failure mode.
- Suggest `model`/`image_size` from `options/summary` defaults unless the cast
  size or budget calls for an upgrade.