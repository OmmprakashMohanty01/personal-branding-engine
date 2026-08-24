from huggingface_hub import InferenceClient
import os
import logging
import asyncio

logger = logging.getLogger(__name__)

async def generate_hf_fallback(prompt: str) -> bytes | None:
    api_key = os.environ.get("HUGGINGFACE_API_KEY")
    if not api_key:
        logger.warning("[HF FALLBACK] No HUGGINGFACE_API_KEY found. Skipping HF fallback.")
        return None
    try:
        # Wrap sync call in asyncio.to_thread
        client = InferenceClient(api_key=api_key)
        def _generate():
            # Using a fast, free-tier friendly model
            image = client.text_to_image(prompt, model="black-forest-labs/FLUX.1-schnell")
            # The object returned is a PIL image, we need bytes.
            import io
            buf = io.BytesIO()
            image.save(buf, format='PNG')
            return buf.getvalue()
        
        png_bytes = await asyncio.to_thread(_generate)
        return png_bytes
    except Exception as e:
        logger.error(f"[HF FALLBACK] Failed: {e}")
        return None
