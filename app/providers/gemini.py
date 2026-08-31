"""Gemini Interactions API adapter. SDK details do not escape this module."""

from __future__ import annotations

import base64

from app.assembler.core import capabilities_for
from app.providers.base import ProviderRequest, ProviderResult


class GeminiProviderError(Exception):
    pass


class GeminiProvider:
    def __init__(self, client=None) -> None:
        if client is None:
            from google import genai

            client = genai.Client()
        self.client = client

    def build_api_request(self, request: ProviderRequest) -> dict:
        capabilities = capabilities_for(request.model)
        inputs: list[dict] = [{"type": "text", "text": request.prompt}]
        for reference in request.references:
            image = {
                "type": "image",
                "data": base64.b64encode(reference.data).decode("ascii"),
                "mime_type": reference.mime_type,
            }
            if capabilities.supports_media_resolution:
                image["resolution"] = "high"
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
            "labels": request.labels,
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
            "labels": request.labels,
            "store": False,
        }

    def generate(self, request: ProviderRequest) -> ProviderResult:
        try:
            interaction = self.client.interactions.create(
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
            raise GeminiProviderError(f"Gemini generation failed: {exc}") from exc
