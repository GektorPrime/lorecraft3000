"""Gemini Interactions API adapter. SDK details do not escape this module."""

from __future__ import annotations

import base64
import re
import time

from app.providers.base import ProviderRequest, ProviderResult

# gemini-3-pro-image periodically returns a 5xx "high demand ... try again
# later" response. Confirmed (docs + live probing) to be transient Google-side
# capacity, not a client/request defect: the identical request succeeds on
# retry. These are not charged, so a bounded retry with backoff recovers the
# generation instead of aborting on a momentary spike.
CAPACITY_MAX_ATTEMPTS = 4
CAPACITY_BACKOFF_SECONDS = (1.0, 3.0, 7.0)


class GeminiProviderError(Exception):
    def __init__(self, message: str, *, charge_expected: bool = True) -> None:
        super().__init__(message)
        self.charge_expected = charge_expected


class GeminiProvider:
    def __init__(self, client=None, *, sleep=time.sleep) -> None:
        self.client = client
        self._sleep = sleep

    def _client(self):
        if self.client is None:
            from google import genai

            self.client = genai.Client()
        return self.client

    def build_api_request(self, request: ProviderRequest) -> dict:
        inputs: list[dict] = [{"type": "text", "text": request.prompt}]
        for reference in request.references:
            image = {
                "type": "image",
                "data": base64.b64encode(reference.data).decode("ascii"),
                "mime_type": reference.mime_type,
            }
            inputs.append(image)
        return {
            "model": request.model,
            "input": inputs,
            "response_format": {
                "type": "image",
                "aspect_ratio": request.aspect_ratio,
                "image_size": request.image_size,
            },
            "store": False,
        }

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
            "store": False,
        }

    @staticmethod
    def _is_capacity_failure(exc: Exception) -> bool:
        """True for the transient 5xx 'high demand ... try again later' response.

        This is Google-side capacity for gemini-3-pro-image, confirmed to
        succeed on retry with an identical request. Kept separate from generic
        5xx so only this specific, retry-safe condition is retried.
        """
        error_text = str(exc)
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        if status is None:
            match = re.search(r"(?:Error code|code)[:=]\s*(\d{3})", error_text)
            status = int(match.group(1)) if match else None
        return (
            isinstance(status, int)
            and status >= 500
            and "high demand" in error_text.lower()
            and "try again later" in error_text.lower()
        )

    def _generate_once(self, request: ProviderRequest) -> ProviderResult:
        interaction = self._client().interactions.create(
            **self.build_api_request(request)
        )
        image = getattr(interaction, "output_image", None)
        if image is None or not getattr(image, "data", None):
            raise GeminiProviderError("Gemini returned no output image")
        interaction_id = getattr(interaction, "id", None)
        return ProviderResult(
            image_bytes=base64.b64decode(image.data),
            interaction_id=interaction_id,
            response_metadata={"interaction_id": interaction_id},
        )

    def generate(self, request: ProviderRequest) -> ProviderResult:
        last_exc: Exception | None = None
        for attempt in range(CAPACITY_MAX_ATTEMPTS):
            try:
                return self._generate_once(request)
            except GeminiProviderError:
                raise
            except Exception as exc:  # noqa: BLE001 — classified below
                last_exc = exc
                is_capacity = self._is_capacity_failure(exc)
                has_retries_left = attempt < CAPACITY_MAX_ATTEMPTS - 1
                if is_capacity and has_retries_left:
                    self._sleep(CAPACITY_BACKOFF_SECONDS[attempt])
                    continue
                status = getattr(exc, "status_code", None) or getattr(
                    exc, "code", None
                )
                if status is None:
                    match = re.search(
                        r"(?:Error code|code)[:=]\s*(\d{3})", str(exc)
                    )
                    status = int(match.group(1)) if match else None
                charge_expected = not (
                    (isinstance(status, int) and 400 <= status < 500) or is_capacity
                )
                raise GeminiProviderError(
                    f"Gemini generation failed: {exc}",
                    charge_expected=charge_expected,
                ) from exc
        # Unreachable in practice (loop either returns or raises), but keeps the
        # type checker satisfied and guards against a zero-attempt config.
        raise GeminiProviderError(
            f"Gemini generation failed: {last_exc}", charge_expected=False
        )
