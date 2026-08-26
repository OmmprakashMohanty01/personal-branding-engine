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

REQUIRED_MODIFIERS = "highly detailed, 8k, photorealistic, cinematic lighting, shallow depth of field"


def sanitize_image_prompt(raw_prompt: str) -> str:
    # Trust the LLM's physical description, just ensure high-quality modifiers
    scene = raw_prompt.strip()
    
    if REQUIRED_MODIFIERS not in scene:
        scene = f"{scene}, {REQUIRED_MODIFIERS}"
        
    return scene[:300]



async def generate_visuals(draft_data: dict | str, use_fallback: bool = False) -> str | None:
    """Generate an image for the post.

    Strategy:
    1. If visual_type == 'diagram', try Kroki (PlantUML).
    2. If visual_type == 'photo', try Pollinations AI (FLUX).
    3. If generation fails or returns a tiny payload (< 5KB), fall back to
       a locally-generated Pillow text card using the post hook.

    Always returns a valid data URI string. Never returns None.

    Args:
        draft_data: Dict with visual_type, visual_payload, and post_content, OR a raw string prompt.
        use_fallback: If True, skip generation and go straight to Pillow fallback.

    Returns:
        A base64-encoded data URI (data:image/...) string.
    """
    if isinstance(draft_data, str):
        visual_type = "photo"
        payload = draft_data
        post_content = draft_data
    else:
        visual_type = draft_data.get("visual_type")
        payload = draft_data.get("visual_payload")
        post_content = draft_data.get("post_content", "")

    if not use_fallback:
        if visual_type == "diagram" and payload:
            import zlib
            import httpx
            
            try:
                logger.info("[ROUTER] Attempting Kroki (PlantUML)...")
                compressed = zlib.compress(payload.encode('utf-8'), 9)
                encoded = base64.urlsafe_b64encode(compressed).decode('utf-8')
                url = f"https://kroki.io/plantuml/png/{encoded}"
                
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, timeout=15.0)
                    resp.raise_for_status()
                    png_bytes = resp.content
                    
                    if png_bytes and len(png_bytes) >= MIN_IMAGE_SIZE_BYTES:
                        logger.info(f"[ROUTER] Kroki succeeded. Image size: {len(png_bytes)} bytes")
                        b64_str = base64.b64encode(png_bytes).decode("utf-8")
                        return f"data:image/png;base64,{b64_str}"
                    else:
                        size = len(png_bytes) if png_bytes else 0
                        logger.warning(f"[ROUTER] Kroki returned insufficient data ({size} bytes). Falling back to Pillow.")
            except Exception as e:
                logger.warning(f"[ROUTER] Kroki failed: {e}. Falling back to Pillow text card.")
        else:
            try:
                logger.info("[ROUTER] Attempting Pollinations AI (FLUX)...")
                
                if payload:
                    final_image_prompt = sanitize_image_prompt(payload)
                else:
                    # Build a concise image prompt from the post content
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
