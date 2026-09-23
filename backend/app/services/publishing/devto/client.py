import logging
import os
from typing import Optional

import httpx

from app.services.publishing.base import SocialPublisher, AuthenticationError

logger = logging.getLogger("branding_engine.publishing.devto.client")


class DevToClient(SocialPublisher):
    """Dev.to publisher using their REST API with API keys."""

    @property
    def name(self) -> str:
        return "dev_to"

    def __init__(self):
        self.api_key = os.getenv("DEVTO_API_KEY")

    def is_connected(self) -> bool:
        return bool(self.api_key)

    async def validate_auth(self, **kwargs):
        if not self.is_connected():
            raise AuthenticationError("Dev.to API key not configured.")
        try:
            headers = {
                "api-key": self.api_key,
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get("https://dev.to/api/users/me", headers=headers)
                resp.raise_for_status()
        except Exception as e:
            raise AuthenticationError(f"Dev.to authentication failed: {e}")

    async def upload_media(self, image_url: Optional[str] = None, **kwargs) -> Optional[str]:
        """Dev.to does not support standalone media upload. Images are inline in Markdown."""
        return None

    async def publish(self, draft_text: str, media_id: Optional[str] = None, **kwargs) -> str:
        """Publish a live article to Dev.to.

        Expects kwargs:
            title (str): Article title.
            tags (list[str]): Up to 4 tags.
        """
        title = kwargs.get("title", "")
        tags = kwargs.get("tags", [])

        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "article": {
                "title": title,
                "body_markdown": draft_text,
                "published": True,
                "tags": [t.replace("-", "").replace(" ", "") for t in tags[:4]],
            }
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://dev.to/api/articles",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            url = resp.json()["url"]
            logger.info(f"[DEV.TO] Published article: {url}")
            return url
