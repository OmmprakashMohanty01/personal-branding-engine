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
        "editorial photography",
        "professional technology branding",
        "engineering diagrams",
        "SaaS product visuals",
        "developer workstations",
        "cloud infrastructure",
        "abstract architectural photography",
        "clean data visualization",
        "modern UI",
        "technical illustrations",
    ]

    FORBIDDEN_ELEMENTS = [
        "fantasy",
        "animals",
        "robots",
        "steampunk",
        "cyberpunk",
        "glowing magic",
        "cinematic movie posters",
        "Instagram aesthetics",
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
