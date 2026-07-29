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
        "Corporate editorial photography",
        "Technology magazine cover",
        "Minimal composition",
        "Realistic office",
        "Professional photography",
        "Natural lighting",
        "Glass office",
        "Developer workspace",
        "Server racks",
        "Clean UI",
        "Modern architecture",
        "Soft blue palette",
        "Business magazine quality",
    ]

    FORBIDDEN_ELEMENTS = [
        "people",
        "faces",
        "glowing screens",
        "neon",
        "cyberpunk",
        "text",
        "messy",
        "3d render",
        "cartoon",
        "desk",
        "computer monitor",
        "keyboard",
    ]

    # Deterministic topic-to-visual mapping for image prompt generation.
    # Each key is matched as a substring against the topic (case-insensitive).
    TOPIC_VISUAL_MAP = {
        "architecture": "Minimalist brutalist architecture, intersecting concrete lines",
        "system": "Minimalist brutalist architecture, intersecting concrete lines",
        "data": "Abstract geometric glass shapes refracting light",
        "ai": "Abstract geometric glass shapes refracting light",
        "machine learning": "Symmetrical patterns in polished black marble",
        "leadership": "A solitary modern chess piece on a clean marble table",
        "management": "A solitary modern chess piece on a clean marble table",
        "python": "Clean interlocking geometric steel structures",
        "cloud": "Vast empty modern concrete gallery with natural skylight",
        "devops": "Precise mechanical clockwork gears in monochrome",
        "security": "Heavy steel vault door mechanism, macro photography",
        "startup": "A single healthy bonsai tree on a minimal white pedestal",
        "automation": "Perfectly aligned dominoes in a white studio space",
        "testing": "Symmetrical reflection on a perfectly still pool of water",
    }

    DEFAULT_VISUAL = "Abstract geometric shapes casting sharp shadows in natural light"

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

    def build_deterministic_prompt(self, topic: str, post_type: str = "insight") -> str:
        """Build a fully deterministic image prompt from topic keywords.

        No LLM is involved. The prompt is composed from a controlled
        topic-visual mapping plus a randomly selected preferred style.

        Args:
            topic: The post topic string.
            post_type: The type of post (insight, tutorial, etc.).

        Returns:
            A complete image generation prompt string.
        """
        import random

        topic_lower = topic.lower()

        # Find the best matching visual from the topic map
        matched_visual = self.DEFAULT_VISUAL
        for keyword, visual in self.TOPIC_VISUAL_MAP.items():
            if keyword in topic_lower:
                matched_visual = visual
                break

        # Select a random preferred style for variety
        style = random.choice(self.PREFERRED_STYLES)

        prompt = (
            f"Professional editorial photography, {matched_visual}, {style}, "
            f"natural sunlight, depth of field, 8k resolution, minimalist, photorealistic. "
            f"negative prompt: people, faces, glowing screens, neon, cyberpunk, text, "
            f"messy, 3d render, cartoon, desk, computer monitor, keyboard"
        )

        logger.info(
            f"[IMAGE RULES] Deterministic prompt built",
            extra={"topic": topic, "matched_keyword": next((k for k in self.TOPIC_VISUAL_MAP if k in topic_lower), "default"), "prompt_length": len(prompt)},
        )

        return prompt
