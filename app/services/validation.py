"""Shared validation helpers for the library services.

Deterministic, dependency-free rules (no tokenizer):
  - visual_contract is hard-capped at 60 words (locked parameter).
  - ref_image roles come from the fixed allowed set in the schema.
"""

from __future__ import annotations

# Locked parameter (documentation/phase-1-plan.md): visual-contract ceiling.
VISUAL_CONTRACT_MAX_WORDS = 60

# Allowed ref_image roles, ordered with the preferred default image first.
ALLOWED_ROLES: tuple[str, ...] = (
    "turnaround",
    "face_front",
    "face_3q",
    "face_profile",
    "full_body",
    "outfit",
    "head_back",
    "expression",
)


def word_count(text: str) -> int:
    """Deterministic word count: split on whitespace, no tokenizer."""
    return len(text.split())


def slugify(name: str) -> str:
    """Derive a URL-safe slug from a name.

    Lowercases, replaces runs of non-alphanumeric characters with a single
    hyphen, and strips leading/trailing hyphens. Empty input yields ''.
    """
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in name)
    parts = [p for p in cleaned.split("-") if p]
    return "-".join(parts)
