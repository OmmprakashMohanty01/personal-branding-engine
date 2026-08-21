import httpx
import logging
import re

logger = logging.getLogger("branding_engine.generation.diagram_service")

KROKI_URL = "https://kroki.io/mermaid/png"

async def render_mermaid_to_png(mermaid_code: str) -> bytes | None:
    # 1. Clean the LLM output (remove ```mermaid and ```)
    cleaned_code = re.sub(r"^```(?:mermaid)?|```$", "", mermaid_code.strip(), flags=re.MULTILINE).strip()
    
    # 2. Add dark mode theme
    theme_header = "%%{init: {'theme': 'dark', 'themeVariables': {'darkMode': true, 'background': '#0B0F17', 'primaryColor': '#1E293B', 'primaryBorderColor': '#38BDF8', 'primaryTextColor': '#F8FAFC', 'lineColor': '#64748B'}}}%%\\n"
    full_code = theme_header + cleaned_code
    
    try:
        # Increase timeout to 20 seconds for free public API
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(
                KROKI_URL,
                content=full_code.encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"}
            )
            if res.status_code == 200:
                return res.content
            logger.error(f"[DIAGRAM] Kroki API error: {res.status_code} - {res.text}")
            return None
    except Exception as e:
        # Print the exact error type for easier debugging
        logger.error(f"[DIAGRAM] Diagram rendering exception: {type(e).__name__}: {e}")
        return None
