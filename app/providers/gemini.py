"""Gemini Interactions API adapter. SDK details do not escape this module."""

from __future__ import annotations

import base64
import re
import time

from app.providers.base import (
    ProviderEditRequest,
    ProviderRequest,
    ProviderResult,
)

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
    def __init__(
        self, client=None, *, timeout_seconds: int = 120, sleep=time.sleep
    ) -> None:
        self.client = client
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep

    def _client(self):
        if self.client is None:
            from google import genai
            from google.genai import types

            self.client = genai.Client(
                http_options=types.HttpOptions(timeout=self.timeout_seconds * 1000)
            )
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

    def build_edit_request(self, request: ProviderEditRequest) -> dict:
        """Build a multi-turn edit turn.

        The source image is re-supplied as an input alongside the canonical
        character references and a text instruction. When the originating
        interaction id is known it is also passed via ``previous_interaction_id``
        so Gemini can continue from its own server-side state; the re-supplied
        bytes keep the edit reliable even when that state is unavailable
        (our generation turns use store=False).
        """
        inputs: list[dict] = [
            {
                "type": "text",
                "text": (
                    f"{request.prompt}\n\nEDIT INSTRUCTION\n"
                    f"Modify the provided image as follows, changing only what is "
                    f"described and preserving everything else, including each "
                    f"character's identity: {request.instruction.strip()}"
                ),
            },
            {
                "type": "image",
                "data": base64.b64encode(request.source_image).decode("ascii"),
                "mime_type": request.source_mime_type,
            },
        ]
        for reference in request.references:
            inputs.append(
                {
                    "type": "image",
                    "data": base64.b64encode(reference.data).decode("ascii"),
                    "mime_type": reference.mime_type,
                }
            )
        payload: dict = {
            "model": request.model,
            "input": inputs,
            "response_format": {
                "type": "image",
                "aspect_ratio": request.aspect_ratio,
                "image_size": request.image_size,
            },
            "store": False,
        }
        if request.source_interaction_id:
            payload["previous_interaction_id"] = request.source_interaction_id
        return payload

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
    def _is_auth_failure(exc: Exception) -> bool:
        """True for missing/invalid API key or permission failures.

        These are client configuration errors that never reach billable
        inference (401/403, or a local check that raises before any HTTP
        call). They must never count toward the daily spend cap.
        """
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        if isinstance(status, int) and status in (401, 403):
            return True
        text = str(exc).lower()
        return (
            "api key" in text
            or "api_key" in text
            or "gemini_api_key" in text
            or "not wired" in text
            or "unauthenticated" in text
            or "permission denied" in text
            or "requires an api key" in text
        )

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

    def _interpret(self, interaction) -> ProviderResult:
        image = getattr(interaction, "output_image", None)
        if image is None or not getattr(image, "data", None):
            raise GeminiProviderError("Gemini returned no output image")
        interaction_id = getattr(interaction, "id", None)
        return ProviderResult(
            image_bytes=base64.b64decode(image.data),
            interaction_id=interaction_id,
            response_metadata={"interaction_id": interaction_id},
        )

    def _run_with_retries(self, payload: dict, *, action: str) -> ProviderResult:
        """Call the Interactions API with the shared capacity retry policy.

        ``action`` is only used for the error message ("generation"/"edit"); the
        capacity, backoff, and billing classification are identical for both.
        """
        last_exc: Exception | None = None
        for attempt in range(CAPACITY_MAX_ATTEMPTS):
            try:
                interaction = self._client().interactions.create(**payload)
                return self._interpret(interaction)
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
                is_auth = self._is_auth_failure(exc)
                charge_expected = not (
                    (isinstance(status, int) and 400 <= status < 500)
                    or is_capacity
                    or is_auth
                )
                raise GeminiProviderError(
                    f"Gemini {action} failed: {exc}",
                    charge_expected=charge_expected,
                ) from exc
        # Unreachable in practice (loop either returns or raises), but keeps the
        # type checker satisfied and guards against a zero-attempt config.
        raise GeminiProviderError(
            f"Gemini {action} failed: {last_exc}", charge_expected=False
        )

    def generate(self, request: ProviderRequest) -> ProviderResult:
        return self._run_with_retries(
            self.build_api_request(request), action="generation"
        )

    def edit(self, request: ProviderEditRequest) -> ProviderResult:
        return self._run_with_retries(
            self.build_edit_request(request), action="edit"
        )
