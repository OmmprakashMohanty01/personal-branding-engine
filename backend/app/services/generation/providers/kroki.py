import logging
import httpx
import base64
import zlib
import asyncio

logger = logging.getLogger(__name__)

async def generate_kroki_diagram(mermaid_code: str, max_retries: int = 3) -> bytes | None:
    # Kroki expects the payload to be deflated and base64 encoded, then made URL safe
    try:
        compressed = zlib.compress(mermaid_code.encode("utf-8"), 9)
        b64 = base64.urlsafe_b64encode(compressed).decode("ascii")
        url = f"https://kroki.io/mermaid/svg/{b64}"
    except Exception as e:
        logger.error(f"[KROKI] Failed to encode mermaid payload: {e}")
        return None

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    return res.content
                logger.warning(f"[KROKI] Attempt {attempt + 1} returned status {res.status_code}")
        except Exception as e:
            logger.warning(f"[KROKI] Attempt {attempt + 1} failed: {e}")
        
        # Exponential backoff
        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt)
            
    return None
