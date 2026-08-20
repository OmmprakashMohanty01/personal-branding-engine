import os
import base64
import logging
import asyncio
from typing import Optional

from google import genai
from google.genai import types

from app.services.generation.providers import BaseImageProvider
from app.services.generation.circuit_breaker import CircuitBreaker, execute_with_retry

logger = logging.getLogger("branding_engine.generation.providers.imagen")


class ImagenProvider(BaseImageProvider):
    """Google Imagen 3 image generation provider."""

    def __init__(self, failure_threshold: int = 3, recovery_time_seconds: float = 60.0):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            logger.warning("GEMINI_API_KEY is not set. Imagen provider will fail.")
            self.client = None
        else:
            self.client = genai.Client(api_key=self.api_key)
            
        self.circuit_breaker = CircuitBreaker(
            provider_name="imagen_3",
            failure_threshold=failure_threshold,
            recovery_time_seconds=recovery_time_seconds,
        )

    async def generate_image(self, prompt: str) -> Optional[str]:
        if not self.client:
            return None
            
        async def _generate():
            def _sync_gen():
                # Use standard conservative filters as required.
                result = self.client.models.generate_images(
                    model='imagen-3.0-generate-002',
                    prompt=prompt,
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio="1:1"
                    )
                )
                if result and result.generated_images:
                    return result.generated_images[0].image.image_bytes
                return None
                
            # Execute with a 15-second timeout as specified in the plan
            image_bytes = await asyncio.wait_for(asyncio.to_thread(_sync_gen), timeout=15.0)
            if image_bytes:
                b64_str = base64.b64encode(image_bytes).decode("utf-8")
                return f"data:image/jpeg;base64,{b64_str}"
            return None

        try:
            return await execute_with_retry(
                _generate,
                circuit_breaker=self.circuit_breaker,
                max_retries=1,  # Short retry if it fails
                initial_backoff=1.0,
            )
        except asyncio.TimeoutError:
            logger.warning("[IMAGEN PROVIDER FALLBACK] Imagen generation timed out after 15s.")
            return None
        except Exception as err:
            logger.warning(f"[IMAGEN PROVIDER FALLBACK] Image generation failed: {err}")
            return None
