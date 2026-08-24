import logging
import httpx
import base64
import zlib
import asyncio

logger = logging.getLogger(__name__)

async def generate_kroki_diagram(diagram_code: str, diagram_type: str = "plantuml") -> bytes | None:
    # Clean markdown fences
    clean_code = diagram_code.replace("```plantuml", "").replace("```", "").strip()
    
    # Ensure standard PlantUML tags exist
    if not clean_code.startswith("@startuml"):
        clean_code = f"@startuml\n{clean_code}\n@enduml"

    url = "https://kroki.io"
    
    # Kroki prefers encoded URIs for GET, but we will use the POST API for stability
    payload = {
        "diagram_source": clean_code,
        "diagram_type": "plantuml", # Hardcode to PlantUML
        "output_format": "png"      # CRITICAL: Force PNG format
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
