import logging
import httpx
import urllib.parse
import random

logger = logging.getLogger(__name__)

async def generate_flux_image(prompt: str, max_retries: int = 2) -> bytes | None:
    encoded_prompt = urllib.parse.quote(prompt)
    seed = random.randint(1, 999999)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?model=flux&width=1080&height=1080&nologo=true&seed={seed}"
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(url)
                if res.status_code == 200 and "image" in res.headers.get("content-type", ""):
                    return res.content
                logger.warning(f"[POLLINATIONS] Attempt {attempt + 1} returned status {res.status_code}")
        except Exception as e:
            logger.warning(f"[POLLINATIONS] Attempt {attempt + 1} failed: {e}")
    return None
