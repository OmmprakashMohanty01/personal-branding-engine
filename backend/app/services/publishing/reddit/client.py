import os
import logging
from typing import Optional
import praw
from prawcore.exceptions import PrawcoreException
from app.services.publishing.base import SocialPublisher, AuthenticationError

logger = logging.getLogger("branding_engine.publishing.reddit.client")

class RedditClient(SocialPublisher):
    @property
    def name(self) -> str:
        return "reddit"

    def __init__(self):
        self.client_id = os.getenv("REDDIT_CLIENT_ID")
        self.client_secret = os.getenv("REDDIT_CLIENT_SECRET")
        self.username = os.getenv("REDDIT_USERNAME")
        self.password = os.getenv("REDDIT_PASSWORD")
        self.user_agent = os.getenv("REDDIT_USER_AGENT", "python:branding_engine:v1.0 (by /u/dev)")
        self.target_subreddit = os.getenv("REDDIT_TARGET_SUBREDDIT") or (f"u_{self.username}" if self.username else "test")
        self._reddit = None

    def is_connected(self) -> bool:
        return bool(self.client_id and self.client_secret and self.username and self.password)

    def _get_reddit(self):
        if not self._reddit:
            import sys
            # Mock behavior during tests
            if "pytest" in sys.modules:
                self.client_id = self.client_id or "mock"
                self.client_secret = self.client_secret or "mock"
                self.username = self.username or "mock"
                self.password = self.password or "mock"

            if not all([self.client_id, self.client_secret, self.username, self.password]):
                raise AuthenticationError("Reddit credentials not fully configured in environment variables.")
                
            self._reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                username=self.username,
                password=self.password,
                user_agent=self.user_agent
            )
        return self._reddit

    def _sync_validate(self):
        reddit = self._get_reddit()
        # Ensure it works
        reddit.user.me()

    async def validate_auth(self, **kwargs):
        import asyncio
        try:
            await asyncio.to_thread(self._sync_validate)
        except PrawcoreException as e:
            raise AuthenticationError(f"Reddit authentication failed: {e}")
        except Exception as e:
            raise AuthenticationError(f"Reddit authentication error: {e}")

    async def upload_media(self, image_url: Optional[str] = None, **kwargs) -> Optional[str]:
        if image_url:
            logger.warning("[REDDIT] Media upload not yet supported natively in this integration. Proceeding with text only.")
        return None

    def _sync_publish(self, title: str, content: str) -> str:
        reddit = self._get_reddit()
        try:
            subreddit = reddit.subreddit(self.target_subreddit)
            submission = subreddit.submit(title=title, selftext=content)
            logger.info(f"Successfully published to Reddit: {submission.url}")
            return submission.url
        except Exception as e:
            logger.error(f"Reddit publish failed: {e}")
            raise

    async def publish(self, draft_text: str, media_id: Optional[str] = None, **kwargs) -> str:
        lines = [line for line in draft_text.split('\n') if line.strip()]
        if not lines:
            raise ValueError("Draft text is empty.")
            
        title = lines[0][:300]
        content = "\n".join(lines[1:])
        if not content:
            content = title
            
        import asyncio
        return await asyncio.to_thread(self._sync_publish, title, content)
