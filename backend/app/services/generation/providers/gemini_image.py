import logging
import os
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

def generate_gemini_image(director_json: dict) -> bytes | None:
    try:
        # Construct the final strict prompt
        prompt = f"Editorial photography, {director_json.get('concept', 'modern server infrastructure')}, {director_json.get('style', 'premium corporate')}. Do not include: {director_json.get('avoid', 'text, people')}"
        
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        
        # Use generate_content for gemini-3.1-flash-image with IMAGE modality
        response = client.models.generate_content(
            model='gemini-3.1-flash-image',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            )
        )
        
        # Extract the image bytes from the response parts
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                return part.inline_data.data
                
        logger.error("[GEMINI IMAGE] No image data found in the response parts.")
        return None
        
    except Exception as e:
        logger.error(f"[GEMINI IMAGE] Generation failed: {type(e).__name__}: {e}")
        return None
