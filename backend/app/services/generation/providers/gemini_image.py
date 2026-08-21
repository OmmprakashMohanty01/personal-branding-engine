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
        
        # Using the recommended general-purpose image model
        result = client.models.generate_images(
            model='gemini-3.1-flash-image',
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                output_mime_type="image/jpeg",
                aspect_ratio="1:1" # or "16:9" if LinkedIn layout prefers
            )
        )
        
        if result.generated_images:
            return result.generated_images[0].image.image_bytes
            
        return None
    except Exception as e:
        logger.error(f"[GEMINI IMAGE] Generation failed: {e}")
        return None
