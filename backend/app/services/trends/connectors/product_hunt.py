from datetime import datetime, timezone
from typing import Any, List
import os
import httpx

from app.schemas.trends import TrendPayload
from app.services.trends.base import BaseTrendSource

class ProductHuntSource(BaseTrendSource):
    """Fetches trending launches from Product Hunt GraphQL API."""
    
    def __init__(self, token: str = None, timeout: float = 10.0):
        super().__init__(name="product_hunt", timeout=timeout)
        self.token = token or os.getenv("PRODUCT_HUNT_DEVELOPER_TOKEN")

    async def fetch_raw_data(self) -> Any:
        if not self.token:
            # Silent skip if no token configured
            return {}
            
        url = "https://api.producthunt.com/v2/api/graphql"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        query = """
        {
          posts(first: 10, order: VOTES) {
            edges {
              node {
                name
                tagline
                url
                votesCount
                createdAt
              }
            }
          }
        }
        """
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json={"query": query}, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def normalize(self, raw_data: Any) -> List[TrendPayload]:
        payloads = []
        if not raw_data:
            return payloads
            
        edges = raw_data.get("data", {}).get("posts", {}).get("edges", [])
        for edge in edges:
            node = edge.get("node", {})
            
            created_str = node.get("createdAt")
            if created_str:
                pub_date = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            else:
                pub_date = datetime.now(timezone.utc)
                
            payloads.append(
                TrendPayload(
                    canonical_url=node.get("url"),
                    title=node.get("name"),
                    summary=node.get("tagline") or "",
                    topic="Startups",
                    published_at=pub_date,
                    metadata_json={
                        "source_name": self.name,
                        "source_url": "https://producthunt.com",
                        "connector_type": "api",
                        "upvotes": node.get("votesCount", 0)
                    }
                )
            )
            
        return payloads
