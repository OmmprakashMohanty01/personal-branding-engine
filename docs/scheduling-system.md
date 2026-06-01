# Scheduling & Auto-Dispatch System Guide

This document details the architecture, database schema, timezone handling logic, webhook endpoint security, and serverless cron setup for the **Scheduling Engine**.

---

## 1. System Architecture

The Scheduling Engine is a database-backed, stateless coordinator designed to assign optimal publishing times to approved content and dispatch mature posts automatically using an external cron heartbeat.

```
       ┌──────────────────────────────┐
       │   External Serverless Cron   │
       │     (e.g., cron-job.org)     │
       └──────────────┬───────────────┘
                      │
                      │ POST /scheduling/dispatch
                      │ with X-Cron-Secret header
                      ▼
        ┌────────────────────────────┐
        │    FastAPI Webhook API     │
        └─────────────┬──────────────┘
                      │
                      │ Hand off to
                      ▼
         ┌──────────────────────────┐
         │     BackgroundTasks      │
         └────────────┬─────────────┘
                      │
                      │ Triggers
                      ▼
        ┌────────────────────────────┐
        │      DispatchService       │
        └─────────────┬──────────────┘
                      │
                      │ 1. Reset scheduled_for = None (Lock)
                      │ 2. Call publish_draft()
                      ▼
       ┌──────────────────────────────┐
       │    PublishingOrchestrator    │
       └──────────────────────────────┘
```

### 1.1 Stateless Design
The scheduler stores config state inside SQLite/PostgreSQL, making the runtime stateless. Any node behind a load balancer can handle schedule calculations or execute dispatches.

### 1.2 QueueManager
Coordinates assignment of optimal post times for APPROVED drafts:
* Finds drafts where `scheduled_for` is empty.
* Reads the persona's `ScheduleConfig` (falling back to UTC standard slots if none are active).
* Calculates the next available future slot that avoids overlapping posts on the same platform (collision prevention).

### 1.3 DispatchService & Concurrency Safeguard (Locking)
When the external cron hits `/dispatch`, the `DispatchService`:
1. Queries APPROVED drafts where `scheduled_for <= NOW()`.
2. **Immediate Lock**: Instantly clears `scheduled_for = None` and commits it to the database *before* making the publishing API calls. This prevents concurrent cron requests from fetching the same draft, avoiding double-publishing.
3. Dispatches drafts to the `PublishingOrchestrator` for distribution.

---

## 2. Database Schema

### `schedule_configs` Table
Defines optimal posting slots and timezones for a specific persona and platform:
* `id`: String(36), Primary Key
* `persona_id`: String(36), ForeignKey (`personas.id` on delete CASCADE), Index, Non-Nullable
* `platform`: String(50), Non-Nullable (e.g. `'linkedin'`, `'x'`, `'threads'`, `'substack'`)
* `posting_times_json`: JSON List of strings, Non-Nullable (e.g. `["08:00", "12:30", "17:00"]`)
* `timezone`: String(100), Default `"UTC"`, Non-Nullable (e.g. `"America/New_York"`, `"Europe/London"`)
* `is_active`: Boolean, Default `True`, Non-Nullable

### `content_drafts` (Added Column)
* `scheduled_for`: DateTime(timezone=True), Nullable, Indexed

---

## 3. Timezone Math Strategy

All calculations are standardized in UTC natively to prevent server location offsets from skewing post times:
1. `datetime.now(timezone.utc)` gets the current reference time.
2. The current datetime is converted to the user's local timezone using `zoneinfo.ZoneInfo(config.timezone)`.
3. Actionable post slots are constructed locally for today or tomorrow.
4. Local slots are converted back to UTC before saving to `scheduled_for` in the database.

---

## 4. API Endpoints

### 4.1 Assign Schedules
* **Endpoint**: `POST /api/v1/scheduling/assign`
* **Response**: `ScheduleAssignResponse`
* **Response Example**:
```json
{
  "status": "scheduled",
  "scheduled_count": 4
}
```

### 4.2 Secure Webhook Dispatch
* **Endpoint**: `POST /api/v1/scheduling/dispatch`
* **Headers**: `X-Cron-Secret: your_super_secret_string_here`
* **Status**: `202 Accepted`
* **Response**: `ScheduleDispatchResponse`

---

## 5. Serverless External Cron Configuration

To automate dispatch execution without running a persistent system thread, configure a free external cron service like **cron-job.org**:

### Step-by-Step Setup
1. Log into your [cron-job.org](https://cron-job.org/) account.
2. Click **Create Cronjob**.
3. Configure the job settings:
   * **Title**: `AI Brand Engine - Auto Dispatch`
   * **URL**: `https://your-api-domain.com/api/v1/scheduling/dispatch`
   * **Request Method**: `POST`
   * **Schedule**: Set execution frequency to every **5 minutes** or **15 minutes** (e.g., `*/15 * * * *`).
4. Click **Advanced Settings** -> **Headers**:
   * Add a custom header:
     * **Key**: `X-Cron-Secret`
     * **Value**: Set this to match the `API_CRON_SECRET` variable in your `.env` file (e.g. `your_super_secret_string_here`).
5. Click **Create** to save the job.

The external cron will now regularly trigger the dispatch webhook safely, keeping your queue active and secure.
