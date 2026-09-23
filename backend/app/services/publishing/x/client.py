import io
import logging
import os
from typing import Optional

import tweepy

from app.services.publishing.base import SocialPublisher, AuthenticationError

logger = logging.getLogger("branding_engine.publishing.x.client")


class XClient(SocialPublisher):
    """X (Twitter) publisher using Tweepy API v2 for tweets and v1.1 for media."""

    @property
    def name(self) -> str:
        return "x"

    def __init__(self):
        self.api_key = os.getenv("TWITTER_API_KEY")
        self.api_secret = os.getenv("TWITTER_API_SECRET")
        self.access_token = os.getenv("TWITTER_ACCESS_TOKEN")
        self.access_secret = os.getenv("TWITTER_ACCESS_SECRET")

    def is_connected(self) -> bool:
        return bool(self.api_key and self.api_secret and self.access_token and self.access_secret)

    def _sync_validate(self):
        client = tweepy.Client(
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_secret,
        )
        client.get_me()

    async def validate_auth(self, **kwargs):
        if not self.is_connected():
            raise AuthenticationError("X (Twitter) credentials not configured.")
        import asyncio
        try:
            await asyncio.to_thread(self._sync_validate)
        except Exception as e:
            raise AuthenticationError(f"X (Twitter) authentication failed: {e}")

    def _sync_upload_media(self, image_bytes: bytes) -> str:
        auth = tweepy.OAuth1UserHandler(
            self.api_key, self.api_secret,
            self.access_token, self.access_secret,
        )
        api_v1 = tweepy.API(auth)
        upload_res = api_v1.media_upload(
            filename="visual.png",
            file=io.BytesIO(image_bytes),
        )
        logger.info(f"[X] Media uploaded successfully: media_id={upload_res.media_id}")
        return str(upload_res.media_id)

    async def upload_media(self, image_url: Optional[str] = None, **kwargs) -> Optional[str]:
        """Upload media to X using API v1.1 media upload endpoint."""
        if not image_url:
            return None

        try:
            import base64
            if isinstance(image_url, str):
                if "," in image_url:
                    base64_data = image_url.split(",")[1]
                else:
                    base64_data = image_url
                image_bytes = base64.b64decode(base64_data)
            else:
                image_bytes = image_url

            import asyncio
            return await asyncio.to_thread(self._sync_upload_media, image_bytes)
        except Exception as e:
            logger.warning(f"[X] Media upload failed: {e}. Publishing text-only.")
            return None

    def _sync_publish(self, text: str, media_ids: Optional[list] = None) -> str:
        client = tweepy.Client(
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_secret,
        )
        response = client.create_tweet(text=text, media_ids=media_ids)
        tweet_id = response.data["id"]
        url = f"https://x.com/i/status/{tweet_id}"
        logger.info(f"[X] Published tweet: {url}")
        return url

    async def publish(self, draft_text: str, media_id: Optional[str] = None, **kwargs) -> str:
        """Publish a tweet using API v2. Text is truncated to 280 chars."""
        media_ids = [int(media_id)] if media_id else None
        text = draft_text[:280]

        import asyncio
        return await asyncio.to_thread(self._sync_publish, text, media_ids)
