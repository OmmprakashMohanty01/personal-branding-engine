from abc import ABC, abstractmethod
from typing import Optional

class AuthenticationError(Exception):
    pass

class SocialPublisher(ABC):
    """Abstract base class for all social media publishers."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """The identifier for the platform (e.g. 'linkedin', 'reddit')."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Returns True if all required API keys/tokens are present."""
        pass

    @abstractmethod
    async def validate_auth(self, **kwargs):
        """Validate credentials and refresh if necessary. Raises AuthenticationError on failure."""
        pass

    @abstractmethod
    async def upload_media(self, image_url: Optional[str] = None, **kwargs) -> Optional[str]:
        """Upload media to the platform and return the media ID/URN."""
        pass

    @abstractmethod
    async def publish(self, draft_text: str, media_id: Optional[str] = None, **kwargs) -> str:
        """Publish the content and return the post URL or ID."""
        pass
