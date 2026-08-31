#!/usr/bin/env python3
"""
validate_refs.py - Phase 0 spike for the character-consistency app.

Answers three questions before you build anything:
  1. Do reference images through the API beat a text-only description?
  2. Does the `seed` parameter actually make image output reproducible?
  3. What does a real request/response cost and look like?

Usage:
    cp .env.example .env   # then fill in GEMINI_API_KEY (or export it instead)
    mkdir refs && cp your_character_refs/*.png refs/
    python validate_refs.py            # dry run, prints plan + cost, sends nothing
    python validate_refs.py --go       # actually spends money

Everything is written to out/<timestamp>/ with a manifest recording the exact
request behind every image.
"""

import argparse, base64, hashlib, json, mimetypes, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

try:
    from google import genai
except ImportError:
    sys.exit("pip install google-genai pillow")

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("pip install python-dotenv")

# ---------------------------------------------------------------- config

MODEL       = "gemini-3.1-flash-image"
IMAGE_SIZE  = "1K"            # "512" | "1K" | "2K" | "4K"
ASPECT      = "3:2"           # 3:2 landscape, not square
REF_DIR     = Path("refs")
OUT_ROOT    = Path("out")
RUNS_PER_ARM = 2              # repeats per scene per arm
MAX_IMAGES   = 20             # hard stop. refuses to run past this.
COST_PER_IMAGE = {"512": 0.045, "1K": 0.067, "2K": 0.101, "4K": 0.151}

CHARACTER = "the subject"

# Discriminative traits only. No "brown hair, blue eyes" - that describes
# ten million people and competes with the reference images.
VISUAL_CONTRACT = (
    "the subject: an older Victorian man, narrow serious face, deep-set eyes, "
    "prominent nose, long full beard dark at the sides with a strong grey/white "
    "centre, receding dark hair combed back, lean build."
)

STYLE = "Victorian-era oil painting, warm dark palette, soft candlelit light, visible brushwork"

SCENES = [
    "standing beside a fireplace in a dim Victorian study, turned at a three-quarter angle with the face clearly visible",
    "seated in a wingback chair facing the viewer, hands resting on the armrests",
    "walking away down a lamplit Victorian street at dusk, seen from behind at a three-quarter angle, head turned slightly so part of the profile is visible",
]

# ---------------------------------------------------------------- helpers

def load_refs():
    if not REF_DIR.is_dir():
        sys.exit(f"No {REF_DIR}/ directory. Put 3-4 reference images of one character there.")
    files = sorted(p for p in REF_DIR.iterdir()
                   if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    if not files:
        sys.exit(f"{REF_DIR}/ is empty.")
    if len(files) > 4:
        print(f"  ! {len(files)} refs found; using first 4 (model handles ~4 character refs)")
        files = files[:4]
    return files


def image_part(path: Path):
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return {
        "type": "image",
        "data": base64.b64encode(path.read_bytes()).decode(),
        "mime_type": mime,
        # NOTE: per-image resolution is omitted on purpose. gemini-3.1-flash-image
        # rejects a "resolution" field server-side with HTTP 400, so refs are sent
        # at the model's default detail.
    }


# Per-image subject notes for arm A. The reference paintings are not all simple
# single-subject portraits: images 2 and 3 contain distractor people, so the
# intended subject must be named per image instead of a generic "Image 1-3".
REF_NOTES = [
    "Image 1: the older Victorian man seated by the fireplace - long full beard dark at the sides with a strong grey/white centre, receding dark hair combed back, narrow serious face, deep-set eyes, prominent nose.",
    "Image 2: the CENTRAL seated bearded man wearing a flat cap and handling a long gun. Other people and dogs appear in this painting - ignore them.",
    "Image 3: the FOREGROUND bearded man looking toward the viewer. A partial man appears at the right edge - ignore him.",
]


def ref_declaration(n: int) -> str:
    notes = []
    for i in range(n):
        if i < len(REF_NOTES):
            notes.append(REF_NOTES[i])
        else:
            notes.append(f"Image {i+1}: the same bearded Victorian man; ignore any other people in the painting.")
    return "\n".join(notes)


def build_input(scene: str, refs, use_refs: bool):
    """Arm A attaches references and names them. Arm B is text only."""
    if use_refs:
        text = (
            "The attached images are reference paintings, not photographs, and are "
            f"intended to depict the same character: {CHARACTER}. Match that same "
            "man's face, hairline, beard pattern, and build exactly.\n\n"
            f"{ref_declaration(len(refs))}\n\n"
            f"{VISUAL_CONTRACT}\n\n"
            f"Scene: {CHARACTER} {scene}.\n"
            f"Style: {STYLE}.\n"
            f"Exactly one person (single figure). No text, no captions, no speech bubbles, no watermark."
        )
        return [{"type": "text", "text": text}] + [image_part(p) for p in refs]

    text = (
        f"{VISUAL_CONTRACT}\n\n"
        f"Scene: {CHARACTER} {scene}.\n"
        f"Style: {STYLE}.\n"
        f"Exactly one person (single figure). No text, no captions, no speech bubbles, no watermark."
    )
    return [{"type": "text", "text": text}]


def generate(client, contents, seed=None):
    body = {
        "model": MODEL,
        "input": contents,
        "response_format": {
            "type": "image",
            "aspect_ratio": ASPECT,
            "image_size": IMAGE_SIZE,
        },
        "store": False,
    }
    if seed is not None:
        body["generation_config"] = {"seed": seed}

    interaction = client.interactions.create(**body)

    img = getattr(interaction, "output_image", None)
    if img is None or not getattr(img, "data", None):
        print("\n!! Unexpected response shape. Dumping so you can adjust:")
        print(repr(interaction)[:2000])
        raise SystemExit(1)
    return base64.b64decode(img.data)


def contact_sheet(records, out_path):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    rows = {}
    for r in records:
        rows.setdefault(r["scene_idx"], {}).setdefault(r["arm"], []).append(r["path"])
    if not rows:
        return None
    thumb_w, pad, header = 420, 8, 26
    cols = max(len(v.get("A", [])) + len(v.get("B", [])) for v in rows.values())
    sample = Image.open(records[0]["path"])
    thumb_h = int(thumb_w * sample.height / sample.width)
    W = cols * (thumb_w + pad) + pad
    H = len(rows) * (thumb_h + pad + header) + pad
    sheet = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(sheet)
    for ri, (si, arms) in enumerate(sorted(rows.items())):
        y = pad + ri * (thumb_h + pad + header)
        x = pad
        for arm in ("A", "B"):
            for p in arms.get(arm, []):
                im = Image.open(p).convert("RGB").resize((thumb_w, thumb_h))
                draw.text((x, y), f"scene {si}  arm {arm}  {'WITH refs' if arm=='A' else 'text only'}",
                          fill="black")
                sheet.paste(im, (x, y + header))
                x += thumb_w + pad
    sheet.save(out_path)
    return out_path

# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually send requests")
    args = ap.parse_args()

    # Project-local .env (see .env.example). load_dotenv() does NOT override an
    # already-exported GEMINI_API_KEY, so the shell environment still wins.
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is not set. Export it or fill it in .env (see .env.example).")

    refs = load_refs()
    n_ab = len(SCENES) * 2 * RUNS_PER_ARM
    n_seed = 2
    total = n_ab + n_seed
    unit = COST_PER_IMAGE[IMAGE_SIZE]

    print(f"model        {MODEL} @ {IMAGE_SIZE} {ASPECT}")
    print(f"references   {len(refs)}: {', '.join(p.name for p in refs)}")
    print(f"plan         {len(SCENES)} scenes x 2 arms x {RUNS_PER_ARM} runs = {n_ab}")
    print(f"             + {n_seed} for the seed-determinism check")
    print(f"total        {total} images  ~${total*unit:.2f}")

    if total > MAX_IMAGES:
        sys.exit(f"Refusing: {total} exceeds MAX_IMAGES={MAX_IMAGES}.")
    if not args.go:
        print("\nDry run. Re-run with --go to spend money.")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = OUT_ROOT / stamp
    out.mkdir(parents=True, exist_ok=True)
    client = genai.Client()
    records, spent = [], 0.0

    for si, scene in enumerate(SCENES, 1):
        for arm, use_refs in (("A", True), ("B", False)):
            for run in range(1, RUNS_PER_ARM + 1):
                contents = build_input(scene, refs, use_refs)
                name = f"s{si}_{arm}_r{run}.png"
                print(f"  -> {name} ", end="", flush=True)
                t0 = time.time()
                data = generate(client, contents)
                path = out / name
                path.write_bytes(data)
                spent += unit
                print(f"{time.time()-t0:.1f}s  ${spent:.2f}")
                text_only = [c for c in contents if c["type"] == "text"]
                records.append({
                    "scene_idx": si, "scene": scene, "arm": arm, "run": run,
                    "path": str(path),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "used_refs": use_refs,
                    "refs": [p.name for p in refs] if use_refs else [],
                    "prompt": text_only[0]["text"],
                })

    # ---- does seed actually pin the output?
    print("\nseed determinism check (same seed, same prompt, twice):")
    seed_hashes = []
    for i in (1, 2):
        contents = build_input(SCENES[0], refs, True)
        data = generate(client, contents, seed=12345)
        p = out / f"seedcheck_{i}.png"
        p.write_bytes(data)
        h = hashlib.sha256(data).hexdigest()
        seed_hashes.append(h)
        spent += unit
        print(f"  seedcheck_{i}.png  {h[:16]}")
    deterministic = seed_hashes[0] == seed_hashes[1]
    print(f"  -> seed is {'DETERMINISTIC' if deterministic else 'NOT deterministic'}")

    sheet = contact_sheet(records, out / "_compare.png")

    (out / "manifest.json").write_text(json.dumps({
        "model": MODEL, "image_size": IMAGE_SIZE, "aspect_ratio": ASPECT,
        "character": CHARACTER, "visual_contract": VISUAL_CONTRACT, "style": STYLE,
        "seed_deterministic": deterministic,
        "estimated_cost_usd": round(spent, 3),
        "records": records,
    }, indent=2))

    print(f"\nwrote {out}  (~${spent:.2f})")
    if sheet:
        print(f"open {sheet} - arm A is with references, arm B is text only")
    print("\nLook for: is arm A recognisably the SAME person across all three scenes,")
    print("and is arm B a different person each time? That is the whole question.")


if __name__ == "__main__":
    main()
