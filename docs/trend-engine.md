# Trend Discovery Engine Guide

This document details the architecture, processing flows, scoring rules, and instructions on how to extend the Trend Discovery Engine of the AI Personal Branding platform.

---

## 1. System Architecture & Components

The Trend Discovery Engine comprises pluggable source connectors, a mathematical scoring module, a metadata-aware deduplicator, and a concurrent orchestrator.

```
                  ┌────────────────────────────────────────────────┐
                  │                TrendAggregator                 │
                  │   - concurrency limit (asyncio.Semaphore)      │
                  │   - concurrent retrieval (asyncio.gather)      │
                  └──────┬──────────────────────────────────┬──────┘
                         │                                  │
                         ▼                                  ▼
             ┌──────────────────────┐            ┌──────────────────────┐
             │ GitHub Trending API  │   ... 4    │  Google Trends RSS   │
             │   (GitHubTrendSource)│   more     │ (GoogleTrendsSource) │
             └───────────┬──────────┘            └──────────┬───────────┘
                         │                                  │
                         └────────────────┬─────────────────┘
                                          │
                                          ▼  [List of TrendPayload]
                         ┌──────────────────────────────────┐
                         │         TrendDeduplicator        │
                         │ - Simplified Title Normalization │
                         │ - Groups duplicate urls/titles   │
                         │ - Merges metadata & source list  │
                         └────────────────┬─────────────────┘
                                          │
                                          ▼  [List of unique TrendPayload]
                         ┌──────────────────────────────────┐
                         │           TrendScorer            │
                         │ - Base score (scaled upvotes)    │
                         │ - Positive modifiers (relevance) │
                         │ - Strict negative filters (0.0)  │
                         └────────────────┬─────────────────┘
                                          │
                                          ▼  [List of Scored Trends]
                         ┌──────────────────────────────────┐
                         │         Database Layer           │
                         │ - Find/Insert TrendSource        │
                         │ - Upsert Trend (canonical_url)   │
                         │ - Write TrendScore history log   │
                         └──────────────────────────────────┘
```

* **`BaseTrendSource`**: Base abstract connector featuring automatic retry and backoff hooks (`tenacity`) and timeout-bound async operations.
* **`TrendDeduplicator`**: Consolidates content sharing similar titles or matching URLs, summing upvotes/engagement and logging secondary URLs.
* **`TrendScorer`**: Assesses values based on technical target relevance.
* **`TrendAggregator`**: The central supervisor executing all connectors concurrently.

---

## 2. Event Flow & Data Stream

1. **Trigger**: An API call (`POST /api/v1/trends/refresh`) or Celery Beat cron activates the refresh background process.
2. **Parallel Fetch**: The Aggregator fires all active connectors using `asyncio.gather`, restricted by a semaphore pool to prevent rate limits.
3. **Graceful Connector Failure**: If a connector throws a network timeout or API exception, it logs the stack trace and returns an empty list, allowing the remaining active sources to proceed.
4. **Deduplication**: Payload objects are grouped by title similarity.
5. **Scoring**: Every unique payload is calculated and stored.
6. **Database Persistence**: Safe upserting of Trend tables is performed.

---

## 3. Scoring Mathematics & Rules

The final score is evaluated between `0.0` and `100.0`.

### 3.1 Base Score calculation
The base score is derived from normalized engagement metrics (upvotes, stars, points):
$$\text{Base} = \min\left(\max\left(\frac{\text{Engagement Metric}}{10}, 0.0\right), 30.0\right)$$
*Example: A post with 120 points translates to a base score of 12.0.*

### 3.2 Modifiers
* **Positive keyword matches**: Scanning text for relevant items adds `+15` points per word (or `+10` for secondary words):
  * **Primary keywords (+15.0)**: `AI`, `Artificial Intelligence`, `Agentic`, `Automation`, `Startup`, `Startups`, `Career Growth`, `Open Source`, `Software Engineering`, `Business Technology`, `RAG`.
  * **Secondary keywords (+10.0)**: `Python`, `FastAPI`, `Cloud`.
* **Negative keyword matches (Strict zeroing)**: If any polarizing or low-information keywords are found, the final score drops to **0.0**:
  * **Negative keywords**: `Politics`, `Political`, `Election`, `Democrat`, `Republican`, `Congress`, `Senate`, `Celebrity`, `Gossip`, `Religion`, `Religious`, `God`, `Church`, `Bible`, `Spirituality`, `Spam`, `Clickbait`, `Low Quality`, `Divisive`.

---

## 4. Extension Guide: Adding a Custom Source (e.g. Substack)

Adding a new trend discovery channel is modular and straightforward. Follow these steps:

### Step 1: Create the Source Class
Create a new file in `backend/app/services/trends/connectors/substack.py` inheriting from `BaseTrendSource`.

```python
from datetime import datetime, timezone
from typing import Any, List
import httpx
from app.schemas.trends import TrendPayload
from app.services.trends.base import BaseTrendSource

class SubstackTrendSource(BaseTrendSource):
    def __init__(self, timeout: float = 10.0):
        super().__init__(name="substack", timeout=timeout)

    async def fetch_raw_data(self) -> Any:
        url = "https://substack.com/api/v1/discover/trending"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    async def normalize(self, raw_data: Any) -> List[TrendPayload]:
        payloads = []
        posts = raw_data.get("posts", [])
        for post in posts:
            payloads.append(
                TrendPayload(
                    canonical_url=post.get("canonical_url"),
                    title=post.get("title"),
                    summary=post.get("subtitle") or "",
                    topic="Technology Trends",
                    published_at=datetime.now(timezone.utc),
                    metadata_json={
                        "source_name": self.name,
                        "source_url": "https://substack.com",
                        "connector_type": "api",
                        "upvotes": post.get("likes_count", 0)
                    }
                )
            )
        return payloads
```

### Step 2: Register the Connector
Add the export definition inside `backend/app/services/trends/connectors/__init__.py`:
```python
from app.services.trends.connectors.substack import SubstackTrendSource
# Add to __all__ list
```

### Step 3: Wire into API Router
Include the new class in `app.api.endpoints.trends.run_refresh_background()` list of active connectors:
```python
connectors = [
    GitHubTrendSource(),
    HackerNewsSource(),
    # ...
    SubstackTrendSource()
]
```
No other application edits are required; the deduplicator, scorer, and database mapping handle the rest automatically!
