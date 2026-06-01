import asyncio
from datetime import datetime, timezone
from typing import Any, List
import httpx

from app.schemas.trends import TrendPayload
from app.services.trends.base import BaseTrendSource

class HackerNewsSource(BaseTrendSource):
    """Fetches top tech stories from the official Hacker News API."""
    
    def __init__(self, timeout: float = 10.0, limit: int = 10):
        super().__init__(name="hacker_news", timeout=timeout)
        self.limit = limit

    async def fetch_raw_data(self) -> Any:
        url = "https://hacker-news.firebaseio.com/v0/topstories.json"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            story_ids = resp.json()[:self.limit]
            
            # Fetch individual story details in parallel
            tasks = [self._fetch_story_detail(client, sid) for sid in story_ids]
            stories = await asyncio.gather(*tasks)
            return [s for s in stories if s is not None]

    async def _fetch_story_detail(self, client: httpx.AsyncClient, story_id: int) -> Any:
        url = f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    async def normalize(self, raw_data: Any) -> List[TrendPayload]:
        payloads = []
        
        for item in raw_data:
            if not item or "url" not in item:
                continue
                
            time_epoch = item.get("time", int(datetime.now(timezone.utc).timestamp()))
            pub_date = datetime.fromtimestamp(time_epoch, timezone.utc)
            
            payloads.append(
                TrendPayload(
                    canonical_url=item.get("url"),
                    title=item.get("title"),
                    summary=f"Hacker News story by {item.get('by')} with {item.get('descendants', 0)} comments.",
                    topic="Technology Trends",
                    published_at=pub_date,
                    metadata_json={
                        "source_name": self.name,
                        "source_url": "https://news.ycombinator.com",
                        "connector_type": "api",
                        "upvotes": item.get("score", 0),
                        "by": item.get("by"),
                        "comments_count": item.get("descendants", 0)
                    }
                )
            )
            
        return payloads
