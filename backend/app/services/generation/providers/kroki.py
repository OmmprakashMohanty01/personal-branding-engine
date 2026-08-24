import logging
import httpx
import base64
import zlib
import asyncio

logger = logging.getLogger(__name__)

async def generate_kroki_diagram(diagram_code: str, diagram_type: str = "mermaid") -> bytes | None:
    # Clean the code of markdown backticks
    clean_code = diagram_code.replace("```mermaid", "").replace("```", "").strip()
    
    # Inject a theme directive to force a white background and clean styling
    if diagram_type == "mermaid":
        clean_code = "%%{init: {'theme': 'default', 'themeVariables': {'background': '#ffffff'}}}%%\n" + clean_code

    url = "https://kroki.io"
    payload = {
        "diagram_source": clean_code,
        "diagram_type": diagram_type,
        "output_format": "png"  # CRITICAL: Force PNG, never SVG
    }
    
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(url, json=payload)
            if res.status_code == 200:
                return res.content
            logger.error(f"[KROKI] Failed to generate diagram: {res.text}")
            return None
    except Exception as e:
        logger.error(f"[KROKI] Exception: {e}")
        return None
