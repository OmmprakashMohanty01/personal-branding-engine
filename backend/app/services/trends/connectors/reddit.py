from datetime import datetime, timezone
from typing import Any, List
import httpx

from app.schemas.trends import TrendPayload
from app.services.trends.base import BaseTrendSource

class RedditTrendSource(BaseTrendSource):
    """Fetches popular posts from Reddit subreddits without requiring OAuth."""
    
    def __init__(self, timeout: float = 10.0):
        super().__init__(name="reddit", timeout=timeout)

    async def fetch_raw_data(self) -> Any:
        url = "https://www.reddit.com/r/MachineLearning+startup+Python/hot.json"
        params = {"limit": 10}
        headers = {"User-Agent": "ai-personal-branding:v1.0 (by /u/custom_user)"}
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()

    async def normalize(self, raw_data: Any) -> List[TrendPayload]:
        payloads = []
        children = raw_data.get("data", {}).get("children", [])
        
        for child in children:
            data = child.get("data", {})
            if not data or data.get("is_self") is False and not data.get("url"):
                continue
                
            time_epoch = data.get("created_utc", int(datetime.now(timezone.utc).timestamp()))
            pub_date = datetime.fromtimestamp(time_epoch, timezone.utc)
            
            subreddit = data.get("subreddit", "Unknown")
            topic = "AI" if subreddit.lower() == "machinelearning" else "Startups" if subreddit.lower() == "startup" else "Technology Trends"
            
            # Map reddit link post or self post
            canonical_url = data.get("url")
            if data.get("is_self"):
                canonical_url = f"https://reddit.com{data.get('permalink')}"
                
            payloads.append(
                TrendPayload(
                    canonical_url=canonical_url,
                    title=data.get("title"),
                    summary=data.get("selftext")[:400] if data.get("selftext") else "",
                    topic=topic,
                    published_at=pub_date,
                    metadata_json={
                        "source_name": self.name,
                        "source_url": f"https://reddit.com/r/{subreddit}",
                        "connector_type": "api",
                        "upvotes": data.get("score", 0),
                        "subreddit": subreddit,
                        "comments_count": data.get("num_comments", 0)
                    }
                )
            )
            
        return payloads
