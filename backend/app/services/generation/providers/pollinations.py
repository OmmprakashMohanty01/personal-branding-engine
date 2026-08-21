import logging
import httpx
import urllib.parse
import random

logger = logging.getLogger(__name__)

async def generate_pollinations_image(director_json: dict) -> bytes | None:
    try:
        # Build the strict, photorealistic prompt from the Director JSON
        concept = director_json.get('concept', 'modern corporate technology infrastructure')
        style = director_json.get('style', 'premium technology editorial photography')
        avoid = director_json.get('avoid', 'cyberpunk, glowing neon, robots, text, floating cubes, fantasy')
        
        raw_prompt = f"{style}, {concept}, photorealistic 8k, shot on 35mm lens. DO NOT INCLUDE: {avoid}"
        encoded_prompt = urllib.parse.quote(raw_prompt)
        
        # Force the FLUX model via URL params with a random seed
        seed = random.randint(1, 999999)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?model=flux&width=1080&height=1080&nologo=true&seed={seed}"
        
        # Fetch image with async retry loop for reliability
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=25.0) as client:
                    res = await client.get(url)
                    if res.status_code == 200 and 'image' in res.headers.get('content-type', ''):
                        return res.content
                    logger.warning(f"[POLLINATIONS] Attempt {attempt+1} failed: {res.status_code}")
            except httpx.ReadTimeout:
                logger.warning(f"[POLLINATIONS] Timeout on attempt {attempt+1}")
                
        logger.error("[POLLINATIONS] All image generation attempts failed.")
        return None

    except Exception as e:
        logger.error(f"[POLLINATIONS] Unexpected error: {type(e).__name__}: {e}")
        return None
