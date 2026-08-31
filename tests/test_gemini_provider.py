from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from app.providers.base import ProviderReference, ProviderRequest
from app.providers.gemini import GeminiProvider, GeminiProviderError


class _Interactions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="interaction-1",
            output_image=SimpleNamespace(data=base64.b64encode(b"output").decode()),
        )


def _request(model):
    return ProviderRequest(
        model=model,
        prompt="prompt",
        references=(ProviderReference(1, "a" * 64, "image/png", b"secret-bytes"),),
        aspect_ratio="3:2",
        image_size="1K",
        labels={"scene": "1"},
    )


@pytest.mark.parametrize(
    "model", ("gemini-3.1-flash-image", "gemini-3-pro-image")
)
def test_image_models_omit_unsupported_media_resolution(model):
    interactions = _Interactions()
    provider = GeminiProvider(SimpleNamespace(interactions=interactions))
    provider.generate(_request(model))
    assert "resolution" not in interactions.kwargs["input"][1]
    assert "labels" not in interactions.kwargs


def test_sanitized_request_has_hash_but_no_bytes_or_key():
    capture = GeminiProvider.sanitized_request(_request("gemini-3.1-flash-image"))
    rendered = str(capture)
    assert "a" * 64 in rendered
    assert "secret-bytes" not in rendered
    assert "GEMINI_API_KEY" not in rendered
    assert "labels" not in capture


def test_adapter_extracts_image_and_interaction_id():
    provider = GeminiProvider(SimpleNamespace(interactions=_Interactions()))
    result = provider.generate(_request("gemini-3.1-flash-image"))
    assert result.image_bytes == b"output"
    assert result.interaction_id == "interaction-1"


def test_consumer_api_400_is_marked_non_billable():
    class RejectedInteractions:
        def create(self, **kwargs):
            raise RuntimeError("Error code: 400 - invalid_request")

    provider = GeminiProvider(SimpleNamespace(interactions=RejectedInteractions()))
    with pytest.raises(GeminiProviderError) as excinfo:
        provider.generate(_request("gemini-3.1-flash-image"))
    assert excinfo.value.charge_expected is False


def test_high_demand_500_is_marked_non_billable():
    class BusyInteractions:
        def create(self, **kwargs):
            raise RuntimeError(
                "Error code: 500 - gemini-3-pro-image is currently experiencing "
                "high demand. Please try again later."
            )

    provider = GeminiProvider(SimpleNamespace(interactions=BusyInteractions()))
    with pytest.raises(GeminiProviderError) as excinfo:
        provider.generate(_request("gemini-3-pro-image"))
    assert excinfo.value.charge_expected is False
