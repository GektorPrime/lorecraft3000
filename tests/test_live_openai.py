"""Paid OpenAI smoke test. Never runs in the default suite."""

from __future__ import annotations

import os

import pytest

from app.providers.base import ProviderReference, ProviderRequest
from app.providers.openai import OpenAIProvider


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("LORECRAFT_RUN_LIVE_TESTS") != "1",
    reason="set LORECRAFT_RUN_LIVE_TESTS=1 to authorize this paid call",
)
def test_live_openai_image_adapter(png_bytes):
    request = ProviderRequest(
        model="gpt-image-2",
        prompt=(
            "Use Image 1 as the canonical character reference. Render the same "
            "single figure as a Victorian oil-painting portrait. No text or lettering."
        ),
        references=(ProviderReference(1, "live-smoke", "image/png", png_bytes),),
        aspect_ratio="1:1",
        image_size="1K",
        labels={"test": "live-smoke"},
    )
    result = OpenAIProvider().generate(request)
    assert result.image_bytes
