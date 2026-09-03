"""OpenAI GPT image adapter. SDK details do not escape this module.

Serves every OpenAI GPT image model the app offers (gpt-image-1, gpt-image-1.5,
gpt-image-2); they share the same generate/edit request surface, so one adapter
covers all three. The public shape mirrors GeminiProvider: ``generate`` and
``edit`` both accept the provider-neutral request dataclasses and return a
``ProviderResult``. The panel's aspect ratio is mapped onto the model's concrete
request sizes here so the model respects the requested framing, and generation
uses the best quality tier. These models always return base64 in
``data[0].b64_json`` (never a URL), so there is no URL code path.
"""

from __future__ import annotations

import base64
import time

from app.providers.base import (
    ProviderEditRequest,
    ProviderReference,
    ProviderRequest,
    ProviderResult,
)

# The GPT image models support exactly three standard request sizes: a square, a
# landscape, and a portrait (per the OpenAI Images API `size` parameter). The
# panel's aspect ratio picks which one, so a wide/tall panel is generated in that
# orientation instead of being forced into a square (which both loses detail and
# distorts composition). The UI's 1K/2K/4K selector only reflects cost tiers for
# Gemini; the GPT models have no larger tier, so size is driven by aspect ratio
# alone here.
_SQUARE = "1024x1024"
_LANDSCAPE = "1536x1024"
_PORTRAIT = "1024x1536"

# Every aspect ratio the app offers (see app/models.py::ASPECT_RATIOS), mapped
# to the nearest orientation for the 1K tier. gpt-image-1/1.5 only support
# this trio; gpt-image-2 supports arbitrary resolutions and uses 2K/4K tiers.
_ASPECT_SIZE = {
    "1:1": _SQUARE,
    "3:2": _LANDSCAPE,
    "16:9": _LANDSCAPE,
    "4:3": _LANDSCAPE,
    "2:3": _PORTRAIT,
    "3:4": _PORTRAIT,
    "9:16": _PORTRAIT,
}
_DEFAULT_SIZE = _SQUARE

# gpt-image-2 2K/4K sizes from the platform (screenshot + docs):
# 2K 2560x1440 (landscape) / 1440x2560 (portrait), 4K 3840x2160 / 2160x3840.
# Squares use 2048x2048 / 2816x2816 (16-divisible, under the 3840x2160 ~8.3MP
# ceiling for the 2K tier and experimental above it). 1K tier reuses the trio.
_GPT2_SIZE = {
    "1K": {"square": "1024x1024", "landscape": "1536x1024", "portrait": "1024x1536"},
    "2K": {"square": "2048x2048", "landscape": "2560x1440", "portrait": "1440x2560"},
    "4K": {"square": "2816x2816", "landscape": "3840x2160", "portrait": "2160x3840"},
}

# Transient conditions worth a bounded retry: 429 rate limiting and 5xx server
# overload. Mirrors the Gemini capacity policy so both providers recover from a
# momentary spike instead of aborting a billable-looking attempt.
CAPACITY_MAX_ATTEMPTS = 4
CAPACITY_BACKOFF_SECONDS = (1.0, 3.0, 7.0)


class OpenAIProviderError(Exception):
    def __init__(self, message: str, *, charge_expected: bool = True) -> None:
        super().__init__(message)
        self.charge_expected = charge_expected


class OpenAIProvider:
    def __init__(
        self, client=None, *, timeout_seconds: int = 120, sleep=time.sleep
    ) -> None:
        self.client = client
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep

    def _client(self):
        if self.client is None:
            from openai import OpenAI

            self.client = OpenAI(timeout=self.timeout_seconds)
        return self.client

    @staticmethod
    def _size_for(aspect_ratio: str, model: str = "gpt-image-1", image_size: str = "1K") -> str:
        """Pick the GPT image request size from panel aspect + tier.

        gpt-image-1/1.5 only support the 1K trio, so image_size is ignored
        and orientation decides. gpt-image-2 supports 1K/2K/4K tiers and
        arbitrary WIDTHxHEIGHT, so both aspect and tier matter.
        """
        if model == "gpt-image-2":
            tier = _GPT2_SIZE.get(image_size, _GPT2_SIZE["1K"])
            if aspect_ratio in ("3:4", "9:16", "2:3"):
                return tier["portrait"]
            if aspect_ratio == "1:1":
                return tier["square"]
            # 3:2, 16:9, 4:3, and any unknown default to landscape
            return tier["landscape"]
        return _ASPECT_SIZE.get(aspect_ratio, _DEFAULT_SIZE)

    @staticmethod
    def _reference_file(reference: ProviderReference) -> tuple[str, bytes, str]:
        """A multipart tuple (name, bytes, mime) for an edit input image."""
        suffix = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
        }.get(reference.mime_type, "png")
        return (
            f"reference-{reference.image_number}.{suffix}",
            reference.data,
            reference.mime_type,
        )

    # gpt-image-2 does not support input_fidelity (400 invalid_input_fidelity_model).
    _FIDELITY_MODELS = {"gpt-image-1", "gpt-image-1.5", "gpt-image-1-mini", "chatgpt-image-latest"}

    def build_generate_kwargs(self, request: ProviderRequest) -> dict:
        # When canonical character references are present, LoreCraft must send
        # them. The OpenAI *generations* endpoint is text-only; the reference
        # images have to go through the *edits* endpoint (images[]. Prompt
        # carries the assembled REFERENCE DECLARATION + visual contracts, the
        # images[] are the canonical refs). This is the correct OpenAI path for
        # identity-anchored generation (see /v1/images/edits – GPT image models
        # accept up to 16 input images). Without refs we fall back to pure
        # text-to-image via generations.
        # For panel 7: refs are face_front only (no outfit). A high fidelity
        # generate copies clothing from those face crops (e.g. watch chain)
        # to every character and makes distinct textual outfit descriptions
        # collapse into one uniform + deterministic output. Use low fidelity
        # for fresh generates so text (VISUAL CONTRACTS) wins over ref
        # clothing; keep high for edits where the source image must stay.
        if request.references:
            kwargs: dict = {
                "model": request.model,
                "prompt": request.prompt,
                "image": [self._reference_file(ref) for ref in request.references],
                "size": self._size_for(request.aspect_ratio, request.model, request.image_size),
                "quality": "high",
            }
            if request.model in self._FIDELITY_MODELS:
                kwargs["input_fidelity"] = "low"
            return kwargs
        return {
            "model": request.model,
            "prompt": request.prompt,
            "size": self._size_for(request.aspect_ratio, request.model, request.image_size),
            "quality": "high",
        }

    def build_edit_kwargs(self, request: ProviderEditRequest) -> dict:
        # The source image comes first so it is the base being edited; the
        # canonical character references follow so identity stays anchored.
        images: list[tuple[str, bytes, str]] = [
            ("source.png", request.source_image, request.source_mime_type)
        ]
        images.extend(self._reference_file(ref) for ref in request.references)
        prompt = (
            f"{request.prompt}\n\nEDIT INSTRUCTION\n"
            f"Modify the first image as follows, changing only what is described "
            f"and preserving everything else, including each character's "
            f"identity: {request.instruction.strip()}"
        )
        kwargs: dict = {
            "model": request.model,
            "image": images,
            "prompt": prompt,
            "size": self._size_for(request.aspect_ratio, request.model, request.image_size),
            "quality": "high",
        }
        # Keep the edit faithful to the source: change only what the
        # instruction asks and preserve the rest (per the /images/edits
        # `input_fidelity` parameter). Best for our refine-in-place loop.
        # gpt-image-2 does not support this field.
        if request.model in self._FIDELITY_MODELS:
            kwargs["input_fidelity"] = "high"
        return kwargs

    @staticmethod
    def sanitized_request(request: ProviderRequest) -> dict:
        return {
            "model": request.model,
            "prompt": request.prompt,
            "references": [
                {
                    "image_number": ref.image_number,
                    "sha256": ref.sha256,
                    "mime_type": ref.mime_type,
                }
                for ref in request.references
            ],
            "aspect_ratio": request.aspect_ratio,
            "image_size": request.image_size,
        }

    @staticmethod
    def _status_of(exc: Exception) -> int | None:
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        return status if isinstance(status, int) else None

    @staticmethod
    def _is_auth_failure(exc: Exception) -> bool:
        """Missing/invalid API key or permission — never billable."""
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if isinstance(status, int) and status in (401, 403):
            return True
        text = str(exc).lower()
        return (
            "api key" in text
            or "api_key" in text
            or "openai_api_key" in text
            or "not wired" in text
            or "unauthenticated" in text
            or "permission denied" in text
            or "requires an api key" in text
            or "you must provide an api key" in text
            or "incorrect api key" in text
        )

    @classmethod
    def _is_capacity_failure(cls, exc: Exception) -> bool:
        status = cls._status_of(exc)
        return status == 429 or (isinstance(status, int) and status >= 500)

    def _interpret(self, response) -> ProviderResult:
        data = getattr(response, "data", None)
        if not data:
            raise OpenAIProviderError("OpenAI returned no image")
        b64 = getattr(data[0], "b64_json", None)
        if not b64:
            raise OpenAIProviderError("OpenAI returned no image")
        request_id = getattr(response, "_request_id", None)
        return ProviderResult(
            image_bytes=base64.b64decode(b64),
            interaction_id=request_id,
            response_metadata={"request_id": request_id},
        )

    def _run_with_retries(self, call, *, action: str) -> ProviderResult:
        """Invoke ``call`` (a zero-arg callable) with the shared retry policy."""
        last_exc: Exception | None = None
        for attempt in range(CAPACITY_MAX_ATTEMPTS):
            try:
                return self._interpret(call())
            except OpenAIProviderError:
                raise
            except Exception as exc:  # noqa: BLE001 — classified below
                last_exc = exc
                is_capacity = self._is_capacity_failure(exc)
                has_retries_left = attempt < CAPACITY_MAX_ATTEMPTS - 1
                if is_capacity and has_retries_left:
                    self._sleep(CAPACITY_BACKOFF_SECONDS[attempt])
                    continue
                status = self._status_of(exc)
                is_auth = self._is_auth_failure(exc)
                # A request defect (4xx), an auth/missing-key failure, or a
                # capacity failure (429/5xx) that produced no image after
                # exhausting retries is not billed. Only an unclassifiable
                # error stays billable.
                charge_expected = not (
                    (isinstance(status, int) and 400 <= status < 500)
                    or is_capacity
                    or is_auth
                )
                raise OpenAIProviderError(
                    f"OpenAI {action} failed: {exc}",
                    charge_expected=charge_expected,
                ) from exc
        raise OpenAIProviderError(
            f"OpenAI {action} failed: {last_exc}", charge_expected=False
        )

    def generate(self, request: ProviderRequest) -> ProviderResult:
        kwargs = self.build_generate_kwargs(request)
        has_refs = "image" in kwargs
        call = (
            (lambda: self._client().images.edit(**kwargs))
            if has_refs
            else (lambda: self._client().images.generate(**kwargs))
        )
        return self._run_with_retries(call, action="generation")

    def edit(self, request: ProviderEditRequest) -> ProviderResult:
        kwargs = self.build_edit_kwargs(request)
        return self._run_with_retries(
            lambda: self._client().images.edit(**kwargs), action="edit"
        )
