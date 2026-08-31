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
class ProviderResult:
    image_bytes: bytes
    interaction_id: str | None
    response_metadata: dict
    billed_cost_cents: int | None = None


class ImageProvider(Protocol):
    def generate(self, request: ProviderRequest) -> ProviderResult: ...
