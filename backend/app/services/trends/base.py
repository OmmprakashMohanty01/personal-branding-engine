import logging
from abc import ABC, abstractmethod
from typing import List, Any
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.schemas.trends import TrendPayload

logger = logging.getLogger("branding_engine.trends.base")

class BaseTrendSource(ABC):
    """Abstract base connector for external trend sources."""
    
    def __init__(self, name: str, timeout: float = 10.0):
        self.name = name
        self.timeout = timeout

    @abstractmethod
    async def fetch_raw_data(self) -> Any:
        """Fetch raw payload from external API."""
        pass

    @abstractmethod
    async def normalize(self, raw_data: Any) -> List[TrendPayload]:
        """Convert raw payload to a list of TrendPayload objects."""
        pass

    # Retry HTTP errors or timeout errors using tenacity
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True
    )
    async def _fetch_with_retry(self) -> Any:
        """Helper to invoke fetch_raw_data with automatic retries."""
        logger.info(f"[{self.name}] Fetching raw trend data...")
        return await self.fetch_raw_data()

    async def fetch_trends(self) -> List[TrendPayload]:
        """Pipes fetching and normalization, catching any exceptions gracefully."""
        try:
            raw_data = await self._fetch_with_retry()
            normalized = await self.normalize(raw_data)
            logger.info(f"[{self.name}] Successfully fetched and normalized {len(normalized)} items.")
            return normalized
        except Exception as e:
            logger.error(f"[{self.name}] Connector failed: {e}", exc_info=True)
            import asyncio
            from app.services.monitoring.alerts import AlertManager
            asyncio.create_task(
                AlertManager().send_alert(
                    f"Trend Source '{self.name}' failed or rate-limited: {e}",
                    "WARNING"
                )
            )
            # Fail gracefully returning empty list
            return []
