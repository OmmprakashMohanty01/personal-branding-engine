from datetime import datetime, timezone
from typing import Any, List
import httpx

from app.schemas.trends import TrendPayload
from app.services.trends.base import BaseTrendSource

class GitHubTrendSource(BaseTrendSource):
    """Fetches trending/popular repositories from GitHub Search API."""
    
    def __init__(self, timeout: float = 10.0):
        super().__init__(name="github", timeout=timeout)

    async def fetch_raw_data(self) -> Any:
        url = "https://api.github.com/search/repositories"
        params = {
            "q": "stars:>100 created:>2026-05-01",
            "sort": "stars",
            "order": "desc",
            "per_page": 10
        }
        headers = {"User-Agent": "ai-personal-branding:v1.0"}
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()

    async def normalize(self, raw_data: Any) -> List[TrendPayload]:
        payloads = []
        items = raw_data.get("items", [])
        
        for item in items:
            # Parse created_at or updated_at
            pub_date_str = item.get("created_at")
            if pub_date_str:
                pub_date = datetime.strptime(pub_date_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            else:
                pub_date = datetime.now(timezone.utc)
                
            payloads.append(
                TrendPayload(
                    canonical_url=item.get("html_url"),
                    title=item.get("name"),
                    summary=item.get("description") or "",
                    topic="Open Source",
                    published_at=pub_date,
                    metadata_json={
                        "source_name": self.name,
                        "source_url": "https://github.com",
                        "connector_type": "api",
                        "upvotes": item.get("stargazers_count", 0),
                        "forks": item.get("forks_count", 0),
                        "language": item.get("language") or "Unknown"
                    }
                )
            )
            
        return payloads
