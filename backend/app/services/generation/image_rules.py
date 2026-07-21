"""
image_rules.py
==============
ImageRulesEngine — strict cinematic image prompt constraints
for Pollinations AI image generation.

The image should reinforce the emotional idea of the post,
not illustrate it literally.
"""

import logging

logger = logging.getLogger("branding_engine.generation.image_rules")


class ImageRulesEngine:
    """Provides strict image prompt constraints for the generation pipeline."""

    PREFERRED_STYLES = [
        "cinematic photography",
        "visual metaphors",
        "environmental storytelling",
        "dramatic lighting",
        "macro photography",
        "shallow depth of field",
        "minimalist composition",
        "one clear subject",
    ]

    FORBIDDEN_ELEMENTS = [
        "UI screenshots or code screenshots",
        "dashboards or data visualizations",
        "laptops, monitors, or device screens",
        "floating robots or glowing blue brains",
        "holograms or holographic displays",
        "text, words, or typography of any kind",
        "logos, brand marks, or watermarks",
        "generic glowing orbs or data streams",
        "multiple competing subjects",
        "company or product logos",
    ]

    def get_rules(self) -> str:
        """Return the complete image rules string for template injection.

        Returns:
            Formatted image rules as a plain string.
        """
        preferred = "\n".join(f"- {style}" for style in self.PREFERRED_STYLES)
        forbidden = "\n".join(f"- {elem}" for elem in self.FORBIDDEN_ELEMENTS)

        return (
            "Image Prompt Rules (if requires_image is true):\n"
            "The image should reinforce the emotional idea of the post.\n\n"
            "Preferred:\n"
            f"{preferred}\n\n"
            "Never create:\n"
            f"{forbidden}"
        )
