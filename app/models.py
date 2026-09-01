"""Model capability and pricing registry.

Single source of truth for which generation models exist, which image sizes they
support, the default model/image size, and the supported aspect ratios.

Prices live in app/config.py (``Settings.model_prices_cents``,
``PRICE_TABLE_VERSION``); this registry derives capability from that same table
so pricing and capabilities cannot drift apart. Generation capability (how many
character references a model can take) comes from the prompt assembler's
capability table (app/assembler/core.py::MODEL_CAPABILITIES).
"""

from __future__ import annotations

from app.assembler.core import MODEL_CAPABILITIES
from app.config import Settings

# Aspect ratios supported by the image provider for every model. This is the
# canonical list shared by the JSON API options endpoint and the services.
ASPECT_RATIOS: tuple[str, ...] = ("3:2", "16:9", "4:3", "1:1", "3:4", "9:16")

# Image sizes selectable from the UI, in display order. A model is usable only
# if it has a price for at least one of these; sizes like "512" stay internal
# to the price table and are never offered to the user.
SELECTABLE_IMAGE_SIZES: tuple[str, ...] = ("1K", "2K", "4K")


class ModelRegistry:
    """Resolve the selectable model/image-size surface from Settings."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def image_sizes_for(self, model: str) -> tuple[str, ...]:
        """Selectable image sizes for one model, in display order."""
        prices = self.settings.model_prices_cents.get(model, {})
        return tuple(size for size in SELECTABLE_IMAGE_SIZES if size in prices)

    @property
    def models(self) -> tuple[str, ...]:
        """Generation-capable models (per the assembler) with a selectable price."""
        return tuple(
            capability.model
            for capability in MODEL_CAPABILITIES.values()
            if self.image_sizes_for(capability.model)
        )

    @property
    def image_sizes(self) -> tuple[str, ...]:
        """Union of selectable sizes across usable models, in stable order."""
        seen: set[str] = set()
        ordered: list[str] = []
        for model in self.models:
            for size in self.image_sizes_for(model):
                if size not in seen:
                    seen.add(size)
                    ordered.append(size)
        return tuple(ordered)

    @property
    def aspect_ratios(self) -> tuple[str, ...]:
        return ASPECT_RATIOS

    @property
    def default_model(self) -> str:
        return self.settings.default_model

    @property
    def default_image_size(self) -> str:
        return self.settings.default_image_size