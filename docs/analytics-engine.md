# Analytics Engine Integration Guide

This document details the architecture, data models, rate limiting strategies, background tasks, and API specifications for the **Analytics Engine**. The engine computes internal pipeline efficiency metrics and synchronizes external engagement metrics (likes, shares, comments, views) for published content.

---

## 1. Architecture & Components

The Analytics Engine acts as a read-only observer and metrics collector of existing content drafts and publishing networks. It consists of the following components:

```
                  ┌──────────────────────┐
                  │   Client / Frontend  │
                  └──────────┬───────────┘
                             │
                             │ HTTP Requests
                             ▼
               ┌───────────────────────────┐
               │    FastAPI API Router     │
               └────┬──────────────────┬───┘
                    │                  │
                    │                  │ Uses
                    ▼                  ▼
       ┌────────────────────────┐  ┌────────────────────────┐
       │ PipelineMetricsService │  │    EngagementSyncer    │
       └────────────┬───────────┘  └───────────┬────────────┘
                    │                          │
                    │ Query DB                 │ Updates DB
                    ▼                          ▼
               ┌───────────────────────────────────┐
               │           SQLite Database         │
               │ (trends, content_drafts,          │
               │  post_analytics tables)           │
               └───────────────────────────────────┘
```

### 1.1 PipelineMetricsService
Calculates high-level content aggregation KPIs for the system dashboard:
* **SQL Aggregation Pathway**: Uses SQLAlchemy to compute totals, ratios, and grouping distributions directly in SQLite/PostgreSQL.
* **In-Memory Python Fallback**: If SQLite date math or complex aggregates fail due to dialect discrepancies, the service automatically falls back to in-memory Python calculations, guaranteeing zero pipeline-blocking errors.

### 1.2 EngagementSyncer
Coordinates periodic retrieval of external engagement metrics:
* **Sync Window Restriction**: Only checks posts published in the **last 7 days**.
* **Sync Interval Threshold**: Enforces a **6-hour rolling threshold** per post to prevent rapid-fire requests.
* **X Client Batch Fetch**: Batch fetches metrics for multiple X tweet IDs using `GET /2/tweets?ids=...` (rather than iterating sequentially) to conserve API rate limits.
* **Stubbed Non-X Platforms**: Stubs engagement to `0` for LinkedIn, Threads, and Substack, updating the last-synced timestamp to prevent infinite sync loops.

---

## 2. Database Schema

The Analytics Engine introduces the `post_analytics` table, linked to `content_drafts` via a one-to-one relationship.

### `post_analytics` Table
| Column Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | String(36) | Primary Key | Unique UUID |
| `draft_id` | String(36) | Foreign Key (`content_drafts.id`, `ondelete="CASCADE"`), Unique, Index | Links to parent published content draft |
| `likes` | Integer | Default 0, Non-Nullable | Total likes/favorites count |
| `shares` | Integer | Default 0, Non-Nullable | Total shares/retweets/reposts count |
| `comments` | Integer | Default 0, Non-Nullable | Total comments/replies count |
| `views` | Integer | Default 0, Non-Nullable | Total views/impressions count |
| `last_synced_at` | DateTime | Non-Nullable, onupdate=now | Last synchronization timestamp |

---

## 3. Rate-Limiting & Mitigation Safeguards

To prevent developer API quota exhaustion, the engine implements four defensive limits:
1. **Time-based Exclusion**: Filter query strictly excludes posts published $> 7$ days ago.
2. **Frequency Gate**: Filters out any post synced within the last 6 hours, even if it's within the 7-day window.
3. **URL/ID Batching**: Chains all tweet IDs for a thread and multiple posts into one comma-separated GET request to the X endpoint.
4. **Eager Loading**: The FastAPI router uses SQLAlchemy `selectinload` to eager-load `PostAnalytics` relationships. This prevents `MissingGreenlet` exceptions during serialization in asynchronous contexts.

---

## 4. API Endpoints

All endpoints are registered under the `/api/v1/analytics` prefix.

### 4.1 Get Dashboard Analytics
* **Endpoint**: `GET /api/v1/analytics/dashboard`
* **Response Model**: `DashboardMetricsResponse`
* **Response Example**:
```json
{
  "total_drafts_generated": 142,
  "approval_rate": 0.6725,
  "platform_distribution": {
    "linkedin": 45,
    "x": 38,
    "threads": 12,
    "substack": 5
  },
  "top_performing_trends": [
    {
      "trend_id": "trend-uuid-111",
      "title": "Agentic AI workflows in production",
      "topic": "AI",
      "canonical_url": "https://github.com/google/jax",
      "score": 85.0,
      "post_count": 4
    }
  ]
}
```

### 4.2 Trigger Engagement Sync
* **Endpoint**: `POST /api/v1/analytics/sync`
* **Status Code**: `202 Accepted`
* **Response Model**: `SyncResponse`
* **Response Example**:
```json
{
  "status": "sync_scheduled",
  "message": "Engagement synchronization has been scheduled in the background."
}
```

### 4.3 List Posts with Analytics
* **Endpoint**: `GET /api/v1/analytics/posts`
* **Query Parameters**:
  * `skip` (int, default: 0): Offset.
  * `limit` (int, default: 20): Count.
  * `sort_by` (string, optional): Column to sort by (`likes`, `shares`, `comments`, `views`, `generated_at`).
  * `order` (string, default: `desc`): Sort order (`asc` or `desc`).
* **Response Model**: `List[PostWithAnalyticsResponse]`
* **Response Example**:
```json
[
  {
    "id": "draft-uuid-abc",
    "trend_id": "trend-uuid-111",
    "persona_id": "persona-uuid-999",
    "platform": "x",
    "content_text": "This is the generated text content.",
    "status": "PUBLISHED",
    "generated_at": "2026-06-01T12:00:00Z",
    "approved_at": "2026-06-01T12:30:00Z",
    "final_content": "This is the final edited text content.",
    "analytics": {
      "likes": 120,
      "shares": 15,
      "comments": 6,
      "views": 2400,
      "last_synced_at": "2026-06-01T17:00:00Z"
    }
  }
]
```
