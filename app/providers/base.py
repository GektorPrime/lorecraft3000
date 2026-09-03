"""Provider boundary for image generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderReference:
    image_number: int
    sha256: str
    mime_type: str
    data: bytes


@dataclass(frozen=True)
class ProviderRequest:
    model: str
    prompt: str
    references: tuple[ProviderReference, ...]
    aspect_ratio: str
    image_size: str
    labels: dict[str, str]


@dataclass(frozen=True)
class ProviderEditRequest:
    """A follow-up edit of an already generated image.

    ``source_image`` is the bytes of the image being edited. ``instruction`` is
    the natural-language change to apply. ``prompt`` carries the original
    assembled prompt for context, and ``references`` the same canonical
    character references, so identity stays anchored across the edit.
    ``source_interaction_id`` lets a provider that supports server-side
    multi-turn state (Gemini) continue the conversation instead of re-uploading
    the image; providers that edit statelessly (OpenAI) ignore it and use
    ``source_image``.
    """

    model: str
    prompt: str
    instruction: str
    source_image: bytes
    source_mime_type: str
    references: tuple[ProviderReference, ...]
    aspect_ratio: str
    image_size: str
    labels: dict[str, str]
    source_interaction_id: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    image_bytes: bytes
    interaction_id: str | None
    response_metadata: dict
    billed_cost_cents: int | None = None


class ImageProvider(Protocol):
    def generate(self, request: ProviderRequest) -> ProviderResult: ...

    def edit(self, request: ProviderEditRequest) -> ProviderResult: ...
