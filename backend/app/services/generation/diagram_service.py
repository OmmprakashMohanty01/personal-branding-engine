import httpx
import logging

logger = logging.getLogger("branding_engine.generation.diagram_service")

KROKI_URL = "https://kroki.io"

async def render_mermaid_to_png(mermaid_code: str) -> bytes | None:
    """
    Renders Mermaid syntax to a high-resolution PNG using Kroki.
    """
    # Prepend dark mode styling config if not already present
    init_directive = "%%{init: {'theme': 'dark', 'themeVariables': { 'darkMode': true, 'background': '#0F172A', 'primaryColor': '#1E293B', 'primaryBorderColor': '#38BDF8', 'primaryTextColor': '#F8FAFC', 'lineColor': '#94A3B8'}}}%%\n"
    
    full_mermaid = init_directive + mermaid_code.strip()
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "diagram_source": full_mermaid,
                "diagram_type": "mermaid",
                "output_format": "png"
            }
            response = await client.post(
                KROKI_URL,
                json=payload
            )
            if response.status_code == 200:
                return response.content
            logger.error(f"[DIAGRAM] Kroki render failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"[DIAGRAM] Error rendering flowchart: {e}")
        return None
