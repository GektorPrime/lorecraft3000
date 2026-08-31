"""Gemini Interactions API adapter. SDK details do not escape this module."""

from __future__ import annotations

import base64
import re

from app.providers.base import ProviderRequest, ProviderResult


class GeminiProviderError(Exception):
    def __init__(self, message: str, *, charge_expected: bool = True) -> None:
        super().__init__(message)
        self.charge_expected = charge_expected


class GeminiProvider:
    def __init__(self, client=None) -> None:
        self.client = client

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

    def generate(self, request: ProviderRequest) -> ProviderResult:
        try:
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
        except GeminiProviderError:
            raise
        except Exception as exc:
            error_text = str(exc)
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            if status is None:
                match = re.search(r"(?:Error code|code)[:=]\s*(\d{3})", error_text)
                status = int(match.group(1)) if match else None
            known_capacity_failure = (
                isinstance(status, int)
                and status >= 500
                and "high demand" in error_text.lower()
                and "try again later" in error_text.lower()
            )
            charge_expected = not (
                (isinstance(status, int) and 400 <= status < 500)
                or known_capacity_failure
            )
            raise GeminiProviderError(
                f"Gemini generation failed: {exc}",
                charge_expected=charge_expected,
            ) from exc
