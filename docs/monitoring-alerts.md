# Monitoring & Alerting Guide

This document details the architecture, health check endpoints, alert providers (Discord & Slack), severity formatting, and configuration rules for the **Monitoring & Alerts Engine**.

---

## 1. System Overview

To achieve production-grade stability, the personal branding engine monitors critical failures—such as publishing credential expiration, LLM rate limit quotas, and connector API timeouts—and fires non-blocking real-time webhook notifications.

```
                  ┌──────────────────────┐
                  │    System Trigger    │
                  │ (LLM/Publish Error)  │
                  └──────────┬───────────┘
                             │
                             ▼
               ┌───────────────────────────┐
               │    AlertManager Service   │
               └─────────────┬─────────────┘
                             │
                             │ asyncio.create_task() (Non-blocking)
                             ▼
               ┌───────────────────────────┐
               │  Structured Payload Post  │
               └─────┬───────────────┬─────┘
                     │               │
            If Slack │               │ If Discord
                     ▼               ▼
               ┌───────────┐   ┌───────────┐
               │   Slack   │   │  Discord  │
               │  Channel  │   │  Channel  │
               └───────────┘   └───────────┘
```

### 1.1 Non-Blocking "Fire-and-Forget" Dispatches
All alerts are dispatched asynchronously inside a background event loop task using `asyncio.create_task()`. Webhook connection delays or remote server timeouts are caught locally within `AlertManager` and logged, ensuring they **never block** or crash core publishing, generation, or scheduling operations.

### 1.2 Graceful No-Op Safeguard
If `ALERT_WEBHOOK_URL` is omitted from the environment settings, the alerting service will immediately no-op and return `True` gracefully.

---

## 2. API Health Checks

The engine exposes two monitoring endpoints under the `/api/v1/health` prefix:

### 2.1 Shallow Uptime Health Check
* **Endpoint**: `GET /api/v1/health`
* **Response**: `HealthResponse`
* **Use Case**: Used by load balancers, Kubernetes liveness probes, or third-party checkers (e.g. UptimeRobot) to verify the web server is responsive.
* **Example**:
```json
{
  "status": "healthy",
  "timestamp": "2026-06-01T17:00:00.000Z"
}
```

### 2.2 Deep Health Check
* **Endpoint**: `GET /api/v1/health/deep`
* **Response**: `DeepHealthResponse` (200 OK or 503 Service Unavailable)
* **Use Case**: Performs a lightweight, raw database query (`SELECT 1`) to confirm that connection pools are active.
* **Example (Success - 200 OK)**:
```json
{
  "status": "healthy",
  "database": "connected",
  "timestamp": "2026-06-01T17:00:00.000Z"
}
```

---

## 3. Webhook Alert Providers & Setup

Alerts support both **Discord** and **Slack** payload formats.

### 3.1 Discord Webhook Configuration (Recommended)
1. Open your Discord server and navigate to the target text channel.
2. Click the **Channel Settings** gear icon -> **Integrations**.
3. Click **Webhooks** -> **New Webhook**.
4. Give the webhook a professional name (e.g., `Brand Engine Monitor`) and click **Copy Webhook URL**.
5. Add these parameters to your `.env` file:
```bash
ALERT_PROVIDER=discord
ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN
```

### 3.2 Slack Webhook Configuration
1. Go to your Slack workspace's App Directory and search for **Incoming Webhooks**.
2. Click **Add to Slack** and choose the channel where notifications should post.
3. Click **Add Incoming Webhooks Integration**.
4. Copy the generated **Webhook URL**.
5. Add these parameters to your `.env` file:
```bash
ALERT_PROVIDER=slack
ALERT_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/HASH
```

---

## 4. Alert Severities & Formatting

Alerts are formatted with intuitive visual emojis to keep them highly scannable on mobile notification centers:

| Severity Level | Emoji & Label Prefix | Trigger Cases |
| :--- | :--- | :--- |
| `INFO` | 📢 `[INFO]` | Informational status notifications. |
| `WARNING` | ⚠️ `[WARNING]` | LLM timeouts, API quota warnings, or non-blocking rate limits. |
| `CRITICAL` | 🚨 `[CRITICAL]` | Complete publishing failures (expired accounts, bad credentials, SMTP disconnections). |
