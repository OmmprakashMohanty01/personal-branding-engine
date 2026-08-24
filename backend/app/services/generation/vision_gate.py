import os
import base64
import json
import logging
import httpx
from typing import Dict, Any, Optional
from google import genai
from google.genai import types

logger = logging.getLogger("branding_engine.generation.vision_gate")

async def _fetch_bytes_from_url(url: str) -> bytes:
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        return response.content

def _extract_bytes_from_data_uri(data_uri: str) -> tuple[bytes, str]:
    # data:image/png;base64,iVBORw0KGgo...
    header, encoded = data_uri.split(",", 1)
    mime_type = header.split(";")[0].replace("data:", "")
    return base64.b64decode(encoded), mime_type

async def evaluate_image_alignment(text_draft: str, image_url_or_base64: str) -> Dict[str, Any]:
    """
    Evaluates whether an image aligns with the provided text draft using Gemini Vision.
    
    Returns a dictionary matching the required schema:
    {
        "score": int, (1-10)
        "passed": bool, (score >= 7)
        "reason": str
    }
    """
    logger.info("Initializing Semantic Quality Gate evaluation.")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not found. Skipping semantic visual validation (auto-passing).")
        return {"score": 10, "passed": True, "reason": "No API key found, validation skipped."}
        
    try:
        if image_url_or_base64.startswith("data:"):
            image_bytes, mime_type = _extract_bytes_from_data_uri(image_url_or_base64)
        else:
            image_bytes = await _fetch_bytes_from_url(image_url_or_base64)
            # Default to jpeg for generic URLs unless we do more complex parsing
            mime_type = "image/jpeg" 
    except Exception as e:
        logger.error(f"Failed to extract image bytes for validation: {e}")
        return {"score": 0, "passed": False, "reason": f"Failed to load image: {str(e)}"}
        
    client = genai.Client(api_key=api_key)
    
    # Force JSON response format
    # The new google-genai SDK uses response_schema inside GenerateContentConfig
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema={
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER", "description": "Score from 1 to 10"},
                "passed": {"type": "BOOLEAN", "description": "True if score >= 7, False otherwise"},
                "reason": {"type": "STRING", "description": "Brief explanation of the score and whether it passes or fails"}
            },
            "required": ["score", "passed", "reason"]
        },
        temperature=0.2
    )

    prompt = f"""
    You are an elite, highly critical design director for a tech brand. Evaluate this generated image against the post text.
    
    --- TEXT DRAFT START ---
    {text_draft}
    --- TEXT DRAFT END ---
    
    CRITICAL AESTHETIC LAWS (Immediate Failure if violated):
    1. OVERLAPPING TEXT: If this is a diagram and ANY text overlaps with lines, borders, or other text, you MUST FAIL IT (Score < 5).
    2. CROPPING: If lines or shapes are cut off at the edges of the image, FAIL IT.
    3. CLUTTER: If the diagram looks messy, cramped, or unreadable, FAIL IT.
    4. HALLUCINATIONS: If this is a photorealistic image and it contains mangled text or mutant objects, FAIL IT.

    You must score this image from 1-10. You must return `passed: false` if the score is below 7.
    
    Output JSON ONLY.
    """
    
    import asyncio
    
    def _sync_call():
        return client.models.generate_content(
            model='gemini-3.5-flash',
            contents=[
                prompt,
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            ],
            config=config
        )
        
    try:
        response = await asyncio.to_thread(_sync_call)
        result = json.loads(response.text)
        logger.info(f"Vision Gate Result: Passed={result.get('passed')}, Score={result.get('score')}")
        return result
    except Exception as e:
        logger.error(f"Gemini Vision API failed: {e}")
        # In case of API failure, fail closed or fail open? 
        # Usually it's better to fail the image and downgrade to text-only if we can't validate it.
        return {"score": 0, "passed": False, "reason": f"API error during validation: {str(e)}"}
