import httpx
import logging

logger = logging.getLogger("branding_engine.generation.diagram_service")

KROKI_URL = "https://kroki.io/mermaid/png"

async def render_mermaid_to_png(mermaid_code: str) -> bytes | None:
    theme_header = "%%{init: {'theme': 'dark', 'themeVariables': {'darkMode': true, 'background': '#0B0F17', 'primaryColor': '#1E293B', 'primaryBorderColor': '#38BDF8', 'primaryTextColor': '#F8FAFC', 'lineColor': '#64748B', 'secondaryColor': '#0F172A', 'tertiaryColor': '#1E293B'}}}%%\\n"
    full_code = theme_header + mermaid_code.strip()
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                KROKI_URL,
                content=full_code.encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"}
            )
            if res.status_code == 200:
                return res.content
            logger.error(f"Kroki error: {res.status_code} - {res.text}")
            return None
    except Exception as e:
        logger.error(f"Diagram rendering exception: {e}")
        return None
