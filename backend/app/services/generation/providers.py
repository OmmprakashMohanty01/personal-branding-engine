"""
providers.py
============
Abstract provider interfaces and Pollinations Image Provider implementation
with circuit breaker resilience and selective retries.
"""

import abc
import base64
import logging
import urllib.parse
from typing import Optional

import httpx

from app.services.generation.circuit_breaker import CircuitBreaker, execute_with_retry

logger = logging.getLogger("branding_engine.generation.providers")


class BaseLLMProvider(abc.ABC):
    """Abstract Base Class for LLM Text Providers."""

    @abc.abstractmethod
    async def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Generate text output from the provider."""
        pass


class BaseImageProvider(abc.ABC):
    """Abstract Base Class for Image Generation Providers."""

    @abc.abstractmethod
    async def generate_image(self, prompt: str) -> Optional[str]:
        """Generate an image from prompt and return data URI or URL (or None on failure)."""
        pass


class PollinationsImageProvider(BaseImageProvider):
    """Pollinations AI image generation provider with Circuit Breaker and text-only fallback."""

    def __init__(self, failure_threshold: int = 3, recovery_time_seconds: float = 60.0):
        self.circuit_breaker = CircuitBreaker(
            provider_name="pollinations",
            failure_threshold=failure_threshold,
            recovery_time_seconds=recovery_time_seconds,
        )

    async def generate_image(self, prompt: str) -> Optional[str]:
        """Fetch image from Pollinations AI and return base64 data URI.

        Returns None on failure to enable graceful text-only post degradation.
        """
        encoded_prompt = urllib.parse.quote(prompt.strip())
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"

        async def _fetch() -> str:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(image_url)
                if resp.status_code != 200:
                    raise httpx.HTTPStatusError(
                        f"Pollinations returned status {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                b64_str = base64.b64encode(resp.content).decode("utf-8")
                return f"data:image/jpeg;base64,{b64_str}"

        try:
            return await execute_with_retry(
                _fetch,
                circuit_breaker=self.circuit_breaker,
                max_retries=2,
                initial_backoff=1.0,
            )
        except Exception as err:
            logger.warning(
                f"[POLLINATIONS PROVIDER FALLBACK] Image generation failed: {err}. "
                f"Degrading gracefully to text-only mode."
            )
            return None
