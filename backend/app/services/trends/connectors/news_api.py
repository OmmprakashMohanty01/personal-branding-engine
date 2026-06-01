from datetime import datetime, timezone
from typing import Any, List
import os
import httpx

from app.schemas.trends import TrendPayload
from app.services.trends.base import BaseTrendSource

class NewsAPITrendSource(BaseTrendSource):
    """Fetches recent tech news headlines from NewsAPI."""
    
    def __init__(self, api_key: str = None, timeout: float = 10.0):
        super().__init__(name="news_api", timeout=timeout)
        self.api_key = api_key or os.getenv("NEWS_API_KEY")

    async def fetch_raw_data(self) -> Any:
        if not self.api_key:
            return {}
            
        url = "https://newsapi.org/v2/top-headlines"
        params = {
            "category": "technology",
            "language": "en",
            "pageSize": 10,
            "apiKey": self.api_key
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def normalize(self, raw_data: Any) -> List[TrendPayload]:
        payloads = []
        if not raw_data:
            return payloads
            
        articles = raw_data.get("articles", [])
        for article in articles:
            # Check for required properties to avoid invalid mapping
            if not article.get("title") or not article.get("url"):
                continue
                
            pub_str = article.get("publishedAt")
            if pub_str:
                # NewsAPI returns ISO 8601 strings
                try:
                    pub_date = datetime.strptime(pub_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                except ValueError:
                    pub_date = datetime.now(timezone.utc)
            else:
                pub_date = datetime.now(timezone.utc)
                
            payloads.append(
                TrendPayload(
                    canonical_url=article.get("url"),
                    title=article.get("title"),
                    summary=article.get("description") or "",
                    topic="Technology Trends",
                    published_at=pub_date,
                    metadata_json={
                        "source_name": self.name,
                        "source_url": "https://newsapi.org",
                        "connector_type": "api",
                        "author": article.get("author") or "Unknown",
                        "source_label": article.get("source", {}).get("name", "Unknown News")
                    }
                )
            )
            
        return payloads
