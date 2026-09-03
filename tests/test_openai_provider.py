from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from app.providers.base import (
    ProviderEditRequest,
    ProviderReference,
    ProviderRequest,
)
from app.providers.openai import OpenAIProvider, OpenAIProviderError


def _response(payload: bytes = b"output", request_id: str = "req-1"):
    obj = SimpleNamespace(
        data=[SimpleNamespace(b64_json=base64.b64encode(payload).decode())]
    )
    obj._request_id = request_id
    return obj


class _Images:
    def __init__(self):
        self.generate_kwargs = None
        self.edit_kwargs = None

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        return _response()

    def edit(self, **kwargs):
        self.edit_kwargs = kwargs
        return _response(b"edited")


def _client(images):
    return SimpleNamespace(images=images)


def _request(model="gpt-image-1"):
    return ProviderRequest(
        model=model,
        prompt="prompt",
        references=(ProviderReference(1, "a" * 64, "image/png", b"ref-bytes"),),
        aspect_ratio="3:2",
        image_size="1K",
        labels={"scene": "1"},
    )


def _edit_request(model="gpt-image-1"):
    return ProviderEditRequest(
        model=model,
        prompt="prompt",
        instruction="move the lamp to the left",
        source_image=b"source-bytes",
        source_mime_type="image/png",
        references=(ProviderReference(1, "a" * 64, "image/png", b"ref-bytes"),),
        aspect_ratio="3:2",
        image_size="1K",
        labels={"scene": "1"},
    )


def test_generate_with_references_uses_edits_endpoint_and_low_fidelity():
    images = _Images()
    provider = OpenAIProvider(_client(images))
    result = provider.generate(_request())
    # With canonical refs, generation must go through edits (images.edit)
    # so the characters are anchored; fresh generates use low fidelity so
    # textual VISUAL CONTRACTS (distinct outfits) win over the face crops'
    # clothing (e.g. watch chain) and get variation between runs.
    assert result.image_bytes == b"edited"
    assert images.edit_kwargs is not None
    assert images.generate_kwargs is None
    assert images.edit_kwargs["model"] == "gpt-image-1"
    assert images.edit_kwargs["quality"] == "high"
    assert images.edit_kwargs["input_fidelity"] == "low"
    assert len(images.edit_kwargs["image"]) == 1
    assert images.edit_kwargs["image"][0][1] == b"ref-bytes"


def test_generate_without_references_uses_generations_endpoint():
    images = _Images()
    provider = OpenAIProvider(_client(images))
    req = ProviderRequest(
        model="gpt-image-1",
        prompt="prompt",
        references=(),
        aspect_ratio="1:1",
        image_size="1K",
        labels={},
    )
    result = provider.generate(req)
    assert result.image_bytes == b"output"
    assert images.generate_kwargs is not None
    assert images.edit_kwargs is None
    assert images.generate_kwargs["size"] == "1024x1024"


def test_generate_extracts_image_and_request_id():
    images = _Images()
    provider = OpenAIProvider(_client(images))
    result = provider.generate(_request())
    assert result.image_bytes == b"edited"
    assert result.interaction_id == "req-1"
    # _request has a reference -> routed to edits, size still follows aspect
    assert images.edit_kwargs["size"] == "1536x1024"


@pytest.mark.parametrize(
    "model", ("gpt-image-1", "gpt-image-1.5", "gpt-image-2")
)
def test_all_gpt_models_generate_at_best_quality(model):
    images = _Images()
    provider = OpenAIProvider(_client(images))
    provider.generate(_request(model))
    # _request has refs -> routed to edits; fresh generates use low fidelity
    # so outfit text wins over face-crop clothing, edits stay high.
    assert images.edit_kwargs["model"] == model
    assert images.edit_kwargs["quality"] == "high"
    if model in ("gpt-image-1", "gpt-image-1.5"):
        assert images.edit_kwargs["input_fidelity"] == "low"
    else:
        assert "input_fidelity" not in images.edit_kwargs


@pytest.mark.parametrize(
    "model", ("gpt-image-1", "gpt-image-1.5", "gpt-image-2")
)
def test_all_gpt_models_edit_with_high_fidelity(model):
    images = _Images()
    provider = OpenAIProvider(_client(images))
    provider.edit(_edit_request(model))
    assert images.edit_kwargs["model"] == model
    assert images.edit_kwargs["quality"] == "high"
    if model in ("gpt-image-1", "gpt-image-1.5"):
        assert images.edit_kwargs["input_fidelity"] == "high"
    else:
        assert "input_fidelity" not in images.edit_kwargs


def test_edit_sends_source_first_then_references():
    images = _Images()
    provider = OpenAIProvider(_client(images))
    result = provider.edit(_edit_request())
    assert result.image_bytes == b"edited"
    sent = images.edit_kwargs["image"]
    # Source image is the base being edited and must come first.
    assert sent[0][1] == b"source-bytes"
    assert sent[1][1] == b"ref-bytes"
    assert "move the lamp to the left" in images.edit_kwargs["prompt"]


def test_aspect_ratio_selects_orientation():
    images = _Images()
    provider = OpenAIProvider(_client(images))
    cases = {
        "1:1": "1024x1024",
        "3:2": "1536x1024",
        "16:9": "1536x1024",
        "4:3": "1536x1024",
        "3:4": "1024x1536",
        "9:16": "1024x1536",
    }
    for aspect_ratio, expected in cases.items():
        req = ProviderRequest(
            model="gpt-image-1",
            prompt="p",
            references=(),
            aspect_ratio=aspect_ratio,
            image_size="1K",
            labels={},
        )
        provider.generate(req)
        assert images.generate_kwargs["size"] == expected, aspect_ratio


def test_gpt2_tiered_sizes_use_platform_resolutions():
    images = _Images()
    provider = OpenAIProvider(_client(images))
    # 1K tier reuses trio, 2K/4K use platform's larger sizes per screenshot/docs
    cases = [
        ("1K", "16:9", "1536x1024"),
        ("1K", "9:16", "1024x1536"),
        ("1K", "1:1", "1024x1024"),
        ("2K", "16:9", "2560x1440"),
        ("2K", "9:16", "1440x2560"),
        ("2K", "1:1", "2048x2048"),
        ("4K", "16:9", "3840x2160"),
        ("4K", "9:16", "2160x3840"),
        ("4K", "1:1", "2816x2816"),
    ]
    for image_size, aspect, expected in cases:
        req = ProviderRequest(
            model="gpt-image-2",
            prompt="p",
            references=(),
            aspect_ratio=aspect,
            image_size=image_size,
            labels={},
        )
        provider.generate(req)
        assert images.generate_kwargs["size"] == expected, f"{image_size} {aspect}"


def test_sanitized_request_omits_bytes_and_key():
    capture = OpenAIProvider.sanitized_request(_request())
    rendered = str(capture)
    assert "a" * 64 in rendered
    assert "ref-bytes" not in rendered
    assert "OPENAI_API_KEY" not in rendered


def test_missing_image_is_an_error():
    class Empty:
        def generate(self, **kwargs):
            return SimpleNamespace(data=[])

        def edit(self, **kwargs):
            return SimpleNamespace(data=[])

    provider = OpenAIProvider(_client(Empty()))
    with pytest.raises(OpenAIProviderError):
        provider.generate(_request())


def test_400_is_non_billable_and_not_retried():
    class Rejecting:
        def __init__(self):
            self.calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            exc = RuntimeError("bad request")
            exc.status_code = 400
            raise exc

        def edit(self, **kwargs):
            self.calls += 1
            exc = RuntimeError("bad request")
            exc.status_code = 400
            raise exc

    images = Rejecting()
    sleeps: list[float] = []
    provider = OpenAIProvider(_client(images), sleep=sleeps.append)
    with pytest.raises(OpenAIProviderError) as excinfo:
        provider.generate(_request())
    assert excinfo.value.charge_expected is False
    assert images.calls == 1
    assert sleeps == []


def test_429_retries_then_surfaces_non_billable():
    class Busy:
        def __init__(self):
            self.calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            exc = RuntimeError("rate limited")
            exc.status_code = 429
            raise exc

        def edit(self, **kwargs):
            self.calls += 1
            exc = RuntimeError("rate limited")
            exc.status_code = 429
            raise exc

    images = Busy()
    sleeps: list[float] = []
    provider = OpenAIProvider(_client(images), sleep=sleeps.append)
    with pytest.raises(OpenAIProviderError) as excinfo:
        provider.generate(_request())
    assert excinfo.value.charge_expected is False
    assert images.calls == 4
    assert sleeps == [1.0, 3.0, 7.0]


def test_500_retries_then_succeeds():
    class Flaky:
        def __init__(self):
            self.calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            if self.calls < 3:
                exc = RuntimeError("server overloaded")
                exc.status_code = 503
                raise exc
            return _response(b"recovered")

        def edit(self, **kwargs):
            self.calls += 1
            if self.calls < 3:
                exc = RuntimeError("server overloaded")
                exc.status_code = 503
                raise exc
            return _response(b"recovered")

    images = Flaky()
    sleeps: list[float] = []
    provider = OpenAIProvider(_client(images), sleep=sleeps.append)
    result = provider.generate(_request())
    assert result.image_bytes == b"recovered"
    assert images.calls == 3
    assert sleeps == [1.0, 3.0]
