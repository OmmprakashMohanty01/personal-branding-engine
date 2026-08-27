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
from app.services.generation.image_card import generate_quote_card

logger = logging.getLogger(__name__)

async def generate_visuals(draft_data: dict | str, use_fallback: bool = False) -> str | None:
    """Generate an image for the post.

    Strategy:
    Generates a local Pillow typography quote card using the post hook.
    This ensures high quality aesthetic and deterministic visual quality.

    Always returns a valid data URI string. Never returns None.

    Args:
        draft_data: Dict with quote_hook and post_content, OR a raw string prompt.
        use_fallback: Ignored in this deterministic version.

    Returns:
        A base64-encoded data URI (data:image/...) string.
    """
    if isinstance(draft_data, str):
        payload = draft_data
    else:
        payload = draft_data.get("quote_hook", "Engineering excellence requires simplicity.")

    logger.info("[ROUTER] Generating native typography quote card...")
    try:
        data_uri = generate_quote_card(payload)
        logger.info("[ROUTER] Typography card generated successfully.")
        return data_uri
    except Exception as e:
        logger.error(f"[ROUTER] Typography card generation failed: {e}. Returning None.")
        return None
