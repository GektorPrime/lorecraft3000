"""Paid Gemini smoke test. Never runs in the default suite."""

from __future__ import annotations

import os

import pytest

from app.providers.base import ProviderReference, ProviderRequest
from app.providers.gemini import GeminiProvider


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("LORECRAFT_RUN_LIVE_TESTS") != "1",
    reason="set LORECRAFT_RUN_LIVE_TESTS=1 to authorize this paid call",
)
def test_live_gemini_interactions_adapter(png_bytes):
    request = ProviderRequest(
        model="gemini-3.1-flash-image",
        prompt=(
            "Image 1 is a canonical character reference. Render the same single "
            "figure as a Victorian oil-painting portrait. No text or lettering."
        ),
        references=(ProviderReference(1, "live-smoke", "image/png", png_bytes),),
        aspect_ratio="1:1",
        image_size="1K",
        labels={"test": "live-smoke"},
    )
    result = GeminiProvider().generate(request)
    assert result.image_bytes
