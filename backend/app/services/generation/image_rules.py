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
        "fantasy",
        "illustrations",
        "animals",
        "robots",
        "glowing effects",
        "cyberpunk",
        "steampunk",
        "dramatic cinematic scenes",
    ]

    # Deterministic topic-to-visual mapping for image prompt generation.
    # Each key is matched as a substring against the topic (case-insensitive).
    TOPIC_VISUAL_MAP = {
        "ai": "Modern glass office with AI data visualizations on large curved monitors",
        "machine learning": "Clean research lab with whiteboards showing diagrams and dual monitors",
        "python": "Minimal developer workspace with dual monitors displaying clean code",
        "fastapi": "Modern API dashboard on a large screen in a bright office",
        "devops": "Professional server rack room with organized cabling and blue LED indicators",
        "docker": "Clean terminal interface on a professional workstation",
        "kubernetes": "Infrastructure monitoring dashboard in a modern operations center",
        "cloud": "Panoramic view of a modern data center with organized server rows",
        "career": "Professional meeting room with city skyline visible through floor-to-ceiling windows",
        "productivity": "Organized minimal desk setup with natural lighting and a single monitor",
        "open source": "Collaborative workspace with multiple contributors at standing desks",
        "database": "Modern data center corridor with symmetric server racks",
        "security": "Clean cybersecurity operations center with multiple monitoring screens",
        "startup": "Modern co-working space with standing desks and natural light",
        "automation": "Robotic process dashboard on a wide professional monitor",
        "api": "Clean API architecture diagram displayed on a presentation screen",
        "testing": "Quality assurance dashboard showing green test results on a monitor",
        "linux": "Professional terminal session on a minimal developer workstation",
    }

    DEFAULT_VISUAL = "Minimal modern tech workspace with natural lighting and clean desk organization"

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
            f"{matched_visual}, {style}, "
            f"professional photography, 8k resolution, sharp focus, "
            f"realistic, no text, no watermarks"
        )

        logger.info(
            f"[IMAGE RULES] Deterministic prompt built",
            extra={"topic": topic, "matched_keyword": next((k for k in self.TOPIC_VISUAL_MAP if k in topic_lower), "default"), "prompt_length": len(prompt)},
        )

        return prompt
