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


_HIGH_DEMAND = (
    "Error code: 500 - gemini-3-pro-image is currently experiencing "
    "high demand. Please try again later."
)


def test_high_demand_500_exhausts_retries_and_is_non_billable():
    class BusyInteractions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            raise RuntimeError(_HIGH_DEMAND)

    interactions = BusyInteractions()
    sleeps: list[float] = []
    provider = GeminiProvider(
        SimpleNamespace(interactions=interactions), sleep=sleeps.append
    )
    with pytest.raises(GeminiProviderError) as excinfo:
        provider.generate(_request("gemini-3-pro-image"))
    assert excinfo.value.charge_expected is False
    # Retried up to the cap, then surfaced the failure.
    assert interactions.calls == 4
    # Backoff slept between attempts but not after the final failure.
    assert sleeps == [1.0, 3.0, 7.0]


def test_high_demand_500_retries_then_succeeds():
    class FlakyInteractions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError(_HIGH_DEMAND)
            return SimpleNamespace(
                id="interaction-1",
                output_image=SimpleNamespace(
                    data=base64.b64encode(b"output").decode()
                ),
            )

    interactions = FlakyInteractions()
    sleeps: list[float] = []
    provider = GeminiProvider(
        SimpleNamespace(interactions=interactions), sleep=sleeps.append
    )
    result = provider.generate(_request("gemini-3-pro-image"))
    assert result.image_bytes == b"output"
    assert interactions.calls == 3
    assert sleeps == [1.0, 3.0]


def test_consumer_api_400_is_not_retried():
    class RejectedInteractions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            raise RuntimeError("Error code: 400 - invalid_request")

    interactions = RejectedInteractions()
    sleeps: list[float] = []
    provider = GeminiProvider(
        SimpleNamespace(interactions=interactions), sleep=sleeps.append
    )
    with pytest.raises(GeminiProviderError):
        provider.generate(_request("gemini-3-pro-image"))
    # 4xx fails fast: no retries, no backoff sleeps.
    assert interactions.calls == 1
    assert sleeps == []
