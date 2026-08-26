"""
router.py
=========
Simplified visual generation router with guaranteed output.

Primary: Pollinations AI (FLUX model) for illustrative images.
Fallback: Pure Python Pillow text card — zero external API calls, always succeeds.

This replaces the old router that used Kroki/PlantUML, HF fallback,
and an LLM-based Visual Director for routing decisions.
"""

import base64
import logging
import re
import urllib.parse

from app.services.generation.providers.pollinations import generate_flux_image
from app.services.generation.image_card import generate_quote_card

logger = logging.getLogger(__name__)

MIN_IMAGE_SIZE_BYTES = 5 * 1024  # 5KB minimum to reject error pages

BANNED_TERMS = [
    "database", "api", "cloud", "telemetry", "ingestion", "pipeline",
    "endpoint", "cache", "microservice", "algorithm", "software",
    "query", "schema", "deployment", "cluster", "backend", "frontend",
]
FALLBACK_SCENE = "a minimalist desk with a glowing monitor in a dim room, close-up, shallow depth of field"
REQUIRED_MODIFIERS = "highly detailed, 8k, photorealistic, cinematic lighting, shallow depth of field"


def sanitize_image_prompt(raw_prompt: str) -> str:
    lowered = raw_prompt.lower()
    if any(re.search(rf"\b{term}\b", lowered) for term in BANNED_TERMS):
        scene = FALLBACK_SCENE
    else:
        scene = raw_prompt.strip()

    if REQUIRED_MODIFIERS not in scene:
        scene = f"{scene}, {REQUIRED_MODIFIERS}"
    return scene[:300]



async def generate_visuals(post_content: str, use_fallback: bool = False, image_prompt: str | None = None) -> str | None:
    """Generate an image for the post.

    Strategy:
    1. Try Pollinations AI (FLUX) for a real illustrative image.
    2. If Pollinations fails or returns a tiny payload (< 5KB), fall back to
       a locally-generated Pillow text card using the post hook.

    Always returns a valid data URI string. Never returns None.

    Args:
        post_content: The full text of the LinkedIn post.
        use_fallback: If True, skip Pollinations and go straight to Pillow fallback.
        image_prompt: Optional dedicated prompt for the image generation model.

    Returns:
        A base64-encoded data URI (data:image/...) string.
    """
    if not use_fallback:
        try:
            logger.info("[ROUTER] Attempting Pollinations AI (FLUX)...")
            
            if image_prompt:
                final_image_prompt = sanitize_image_prompt(image_prompt)
            else:
                # Build a concise image prompt from the post content
                # Take the first 200 chars as a seed for the image concept
                image_seed = post_content[:200].replace("\n", " ").strip()
                final_image_prompt = sanitize_image_prompt(f"Abstract minimalist tech illustration: {image_seed}")

            png_bytes = await generate_flux_image(final_image_prompt)

            if png_bytes and len(png_bytes) >= MIN_IMAGE_SIZE_BYTES:
                logger.info(f"[ROUTER] Pollinations succeeded. Image size: {len(png_bytes)} bytes")
                b64_str = base64.b64encode(png_bytes).decode("utf-8")

                # Detect MIME type from magic bytes
                if png_bytes.startswith(b"\xff\xd8\xff"):
                    mime_type = "image/jpeg"
                else:
                    mime_type = "image/png"

                return f"data:{mime_type};base64,{b64_str}"
            else:
                size = len(png_bytes) if png_bytes else 0
                logger.warning(f"[ROUTER] Pollinations returned insufficient data ({size} bytes < {MIN_IMAGE_SIZE_BYTES}). Falling back to Pillow.")

        except Exception as e:
            logger.warning(f"[ROUTER] Pollinations failed: {e}. Falling back to Pillow text card.")

    # ── GUARANTEED FALLBACK: Pillow Text Card ──
    # This never fails — it uses only local Python libraries.
    logger.info("[ROUTER] Generating Pillow text card fallback...")
    try:
        data_uri = generate_quote_card(post_content)
        logger.info("[ROUTER] Pillow text card generated successfully.")
        return data_uri
    except Exception as e:
        # This should effectively never happen, but handle gracefully
        logger.error(f"[ROUTER] Even Pillow fallback failed: {e}. Returning None.")
        return None
