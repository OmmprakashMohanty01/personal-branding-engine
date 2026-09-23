import logging
import os
from typing import Optional

import httpx

from app.services.publishing.base import SocialPublisher, AuthenticationError

logger = logging.getLogger("branding_engine.publishing.medium.client")


class MediumClient(SocialPublisher):
    """Medium publisher using their REST API with integration tokens."""

    @property
    def name(self) -> str:
        return "medium"

    def __init__(self):
        self.token = os.getenv("MEDIUM_INTEGRATION_TOKEN")
        self._author_id: Optional[str] = None

    def is_connected(self) -> bool:
        return bool(self.token)

    async def validate_auth(self, **kwargs):
        if not self.is_connected():
            raise AuthenticationError("Medium integration token not configured.")
        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get("https://api.medium.com/v1/me", headers=headers)
                resp.raise_for_status()
                self._author_id = resp.json()["data"]["id"]
        except Exception as e:
            raise AuthenticationError(f"Medium authentication failed: {e}")

    async def upload_media(self, image_url: Optional[str] = None, **kwargs) -> Optional[str]:
        """Medium does not support standalone media upload. Images are inline in Markdown."""
        return None

    async def publish(self, draft_text: str, media_id: Optional[str] = None, **kwargs) -> str:
        """Publish a live article to Medium.

        Expects kwargs:
            title (str): Article title.
            tags (list[str]): Up to 5 tags.
        """
        title = kwargs.get("title", "")
        tags = kwargs.get("tags", [])

        if not self._author_id:
            await self.validate_auth()

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "title": title,
            "contentFormat": "markdown",
            "content": f"# {title}\n\n{draft_text}" if title else draft_text,
            "tags": tags[:5],
            "publishStatus": "public",
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"https://api.medium.com/v1/users/{self._author_id}/posts",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            url = resp.json()["data"]["url"]
            logger.info(f"[MEDIUM] Published article: {url}")
            return url
