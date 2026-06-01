import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, List
import httpx

from app.schemas.trends import TrendPayload
from app.services.trends.base import BaseTrendSource

class GoogleTrendsSource(BaseTrendSource):
    """Fetches daily search trends from Google Trends geo=US RSS feed."""
    
    def __init__(self, timeout: float = 10.0):
        super().__init__(name="google_trends", timeout=timeout)

    async def fetch_raw_data(self) -> Any:
        url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.text

    async def normalize(self, raw_data: Any) -> List[TrendPayload]:
        payloads = []
        if not raw_data:
            return payloads
            
        try:
            root = ET.fromstring(raw_data)
            channel = root.find("channel")
            if channel is None:
                return payloads
                
            items = channel.findall("item")
            for item in items:
                title_el = item.find("title")
                desc_el = item.find("description")
                link_el = item.find("link")
                pub_date_el = item.find("pubDate")
                
                # Custom google trends elements with namespaces
                traffic_el = item.find("{https://trends.google.com/trends/trendingsearches/daily}approx_traffic")
                
                title = title_el.text if title_el is not None else "Unknown Google Trend"
                summary = desc_el.text if desc_el is not None else ""
                link = link_el.text if link_el is not None else "https://trends.google.com"
                
                traffic_str = traffic_el.text if traffic_el is not None else "0"
                # Strip "+" and commas to parse upvotes points approximation
                traffic_clean = traffic_str.replace("+", "").replace(",", "").strip()
                try:
                    upvotes = int(traffic_clean)
                except ValueError:
                    upvotes = 0
                
                # Parse pubDate e.g. "Mon, 01 Jun 2026 12:00:00 +0000" or similar
                pub_date = datetime.now(timezone.utc)
                if pub_date_el is not None and pub_date_el.text:
                    try:
                        # Attempt to parse standard RFC 822 format
                        pub_date = datetime.strptime(pub_date_el.text.strip()[:25], "%a, %d %b %Y %H:%M:%S").replace(tzinfo=timezone.utc)
                    except Exception:
                        pass
                
                payloads.append(
                    TrendPayload(
                        canonical_url=link,
                        title=title,
                        summary=summary,
                        topic="Technology Trends",
                        published_at=pub_date,
                        metadata_json={
                            "source_name": self.name,
                            "source_url": "https://trends.google.com",
                            "connector_type": "rss",
                            "traffic": traffic_str,
                            "upvotes": upvotes
                        }
                    )
                )
        except Exception as e:
            # Catch XML parsing errors and log
            import logging
            logging.getLogger("branding_engine").error(f"Google Trends XML parsing failed: {e}")
            
        return payloads
