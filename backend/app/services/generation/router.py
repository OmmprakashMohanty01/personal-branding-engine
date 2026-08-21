import logging
import json
import base64

from app.services.llm_provider import GeminiProvider
from app.services.generation.image_director import get_visual_director_prompt
from app.services.generation.providers.pollinations import generate_flux_image
from app.services.generation.providers.hf_fallback import generate_hf_fallback
from app.services.generation.providers.kroki import generate_kroki_diagram
from app.services.generation.quality_gate import validate_image_bytes

logger = logging.getLogger(__name__)

async def generate_visuals(post_content: str, use_fallback: bool = False) -> str | None:
    """
    Analyzes the post and routes to the appropriate visual generator (Pollinations/HF for photo, Kroki for diagram).
    Returns a data URI string (data:image/...) or None if no image should be generated / generation failed.
    """
    logger.info("[ROUTER] Calling Visual Director to determine visual medium...")
    
    # 1. Call Visual Director
    director_prompt = get_visual_director_prompt(post_content)
    llm = GeminiProvider()
    director_response = await llm.generate(
        prompt=post_content,
        system_instruction=director_prompt,
        temperature=0.2 # Lower temp for more deterministic JSON
    )
    
    # Parse JSON
    try:
        # Try to extract JSON block if it's wrapped in markdown
        cleaned_response = director_response.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        
        routing_payload = json.loads(cleaned_response.strip())
        visual_type = routing_payload.get("visual_type", "none").lower()
        concept = routing_payload.get("concept", "")
        prompt_or_code = routing_payload.get("prompt_or_code", "")
    except Exception as e:
        logger.error(f"[ROUTER] Failed to parse Visual Director JSON: {e}. Degrading to none.")
        return None
        
    logger.info(f"[ROUTER] Decision: {visual_type.upper()} | Concept: {concept[:50]}...")
    
    if visual_type == "none" or not prompt_or_code:
        return None
        
    raw_bytes = None
    mime_type = "image/png"
    
    # 2. Route based on decision
    if visual_type == "diagram":
        logger.info("[ROUTER] Routing to Kroki (Mermaid.js)...")
        raw_bytes = await generate_kroki_diagram(prompt_or_code)
        mime_type = "image/svg+xml"
    elif visual_type == "photo":
        logger.info("[ROUTER] Routing to Pollinations (FLUX)...")
        png_bytes = await generate_flux_image(prompt_or_code)
        if validate_image_bytes(png_bytes):
            raw_bytes = png_bytes
            mime_type = "image/jpeg" # Pollinations usually returns JPEG
        else:
            logger.warning("[ROUTER] Pollinations failed or rejected by Quality Gate.")
            logger.info("[ROUTER] Routing to HF Fallback...")
            png_bytes = await generate_hf_fallback(prompt_or_code)
            if validate_image_bytes(png_bytes):
                raw_bytes = png_bytes
                mime_type = "image/png"
            else:
                logger.error("[ROUTER] HF Fallback failed or rejected by Quality Gate.")
    else:
        logger.warning(f"[ROUTER] Unknown visual_type: {visual_type}. Defaulting to none.")
        
    # 3. Process final output
    if raw_bytes:
        b64_str = base64.b64encode(raw_bytes).decode('utf-8')
        return f"data:{mime_type};base64,{b64_str}"
        
    return None
