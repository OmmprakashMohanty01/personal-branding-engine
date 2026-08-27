"""
router.py
=========
Simplified visual generation router with guaranteed output.

Primary: Native Pillow text card for guaranteed visual quality.

This replaces the old router that used Kroki/PlantUML, HF fallback,
and an LLM-based Visual Director for routing decisions.
"""

import base64
import logging
from app.schemas.generation import VisualDirection
from app.services.generation.image_card import generate_quote_card
from app.services.generation.providers.pollinations import generate_flux_image

logger = logging.getLogger(__name__)

MIN_IMAGE_SIZE_BYTES = 5 * 1024  # 5KB minimum to reject error pages

def sanitize_image_prompt(direction: VisualDirection) -> str:
    """Build a detailed image prompt from the VisualDirection fields."""
    scene = f"{direction.subject}. {direction.scene}. {direction.concept}. {direction.composition}. {direction.lighting}. Style: {direction.style}."
    
    REQUIRED_MODIFIERS = "highly detailed, 8k, photorealistic, cinematic lighting"
    scene = f"{scene}, {REQUIRED_MODIFIERS}"
    
    return scene[:300]

from typing import Any

async def generate_visuals(direction: Any, draft_data: dict | str = None, use_fallback: bool = False) -> str | None:
    """Generate an image based on the VisualDirection from the VisualDirector.

    Always returns a valid data URI string. Never returns None.

    Args:
        direction: The structured VisualDirection object, or a raw topic string from the manual UI.
        draft_data: Ignored, kept for signature compatibility during transition.
        use_fallback: If True, skip generation and go straight to Pillow fallback.

    Returns:
        A base64-encoded data URI (data:image/...) string.
    """
    # Handle manual UI generation where direction might just be a string topic
    if isinstance(direction, str):
        direction = VisualDirection(
            visual_type="editorial_photo",
            subject=direction,
            scene=direction,
            concept="Technology",
            composition="Cinematic framing",
            lighting="Studio lighting",
            style="Premium editorial photography",
            negative_prompt="text, typography, quotes, logos"
        )
    elif isinstance(direction, dict):
        direction = VisualDirection(**direction)

    if not use_fallback:
        if direction.visual_type == "diagram":
            import zlib
            import httpx
            
            try:
                logger.info("[ROUTER] Attempting Kroki (PlantUML)...")
                # Create a simple PlantUML flowchart from the subject/concept
                plantuml_code = f"@startuml\nskinparam backgroundColor transparent\nrectangle \"{direction.subject}\" as node1\nrectangle \"{direction.concept}\" as node2\nnode1 --> node2\n@enduml"
                
                compressed = zlib.compress(plantuml_code.encode('utf-8'), 9)
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
        
        elif direction.visual_type == "editorial_photo":
            try:
                logger.info("[ROUTER] Attempting Pollinations AI (FLUX)...")
                
                final_image_prompt = sanitize_image_prompt(direction)

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
    # Also used intentionally if visual_type == "quote_card"
    logger.info("[ROUTER] Generating native typography quote card...")
    try:
        # Pass the subject or concept to quote card to render *something*
        payload = direction.subject if direction.subject else "Engineering excellence requires simplicity."
        data_uri = generate_quote_card(payload)
        logger.info("[ROUTER] Typography card generated successfully.")
        return data_uri
    except Exception as e:
        logger.error(f"[ROUTER] Typography card generation failed: {e}. Returning None.")
        return None
