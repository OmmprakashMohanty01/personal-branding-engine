# Threads Publishing Integration Guide

This document details the OAuth2 long-lived token connections, encrypted lifecycle token management (60-day refresh roll-overs), Two-Step publishing container flow, and failure recovery protocols for the Threads publishing channel.

---

## 1. OAuth2 Connection & Long-Lived Token Exchange

Meta's Threads Graph API requires a server-to-server exchange to acquire long-lived tokens that remain valid for 60 days.

```
[Frontend Client]                  [FastAPI API Gateway]                     [Threads API Server]
        │                                    │                                        │
        │ ── 1. Connect Redirect ──────────> │                                        │
        │    (User grants permissions)       │                                        │
        │                                    │ ── 2. Exchange Code for Short Token ─> │
        │                                    │    (POST /oauth/access_token)          │
        │                                    │                                        │
        │                                    │ <── 3. Short Access Token (2-hour) ─── │
        │                                    │                                        │
        │                                    │ ── 4. Exchange for Long-Lived Token ─> │
        │                                    │    (GET /access_token)                 │
        │                                    │                                        │
        │                                    │ <── 5. 60-Day Long-Lived Token ──────── │
        │                                    │                                        │
        │                                    │ ── 6. Fetch Profile (GET /v1.0/me) ───> │
        │                                    │                                        │
        │                                    │ <── 7. Profile details (ID, Username) ─ │
        │                                    │                                        │
        │ <── 8. Connection Connected ────── │                                        │
        │    (Encrypted credentials saved)   │                                        │
```

1. **Authorization Request**: The frontend redirects the user to the Threads authorization flow requesting scopes: `threads_basic` and `threads_content_publish`.
2. **Callback Endpoint**: Threads redirects back to the backend endpoint `/api/v1/publishing/threads/connect?code=...`.
3. **Step 1: Short-lived Token exchange**: The gateway invokes `exchange_code_for_short_token` exchanging the code for a short-lived (2-hour) access token.
4. **Step 2: Long-lived Token exchange**: Calls the server-to-server endpoint `GET /access_token?grant_type=th_exchange_token` to upgrade to a 60-day token.
5. **Profile Query**: The API queries `GET /v1.0/me?fields=id,username` using the long-lived token.
6. **Registration**: Persists a `ThreadsAccount` record with encrypted tokens.

---

## 2. Encrypted Token Lifecycle & Rolling Refresh

Long-lived credentials are encrypted symmetrically (AES-256-GCM envelope Fernet) under the shared key `ENCRYPTION_KEY`.

### 2.1 Refresh Protocol (60-day cycle)
Access tokens are valid for 60 days. The engine implements a rolling refresh check:
* **Expiry Evaluation**: If `account.expires_at <= datetime.now() + 7 days`, a refresh is triggered.
* **Exchange Call**: Dispatches a `GET /refresh_access_token?grant_type=th_refresh_token` request.
* **Database Roll**: The returned new long-lived token is encrypted, expiry is reset to another 60 days, and changes are committed.

---

## 3. Two-Step "Container" Publishing Architecture

Threads requires text content to go through a two-step creation and publishing lifecycle.

### 3.1 Step 1: Containerization (POST /v1.0/{threads_user_id}/threads)
POST the text content to create a container.
```json
{
  "media_type": "TEXT",
  "text": "This is a Threads post."
}
```
*Response*: Returns `{ "id": "creation_id_123" }`.

### 3.2 Step 2: Publishing (POST /v1.0/{threads_user_id}/threads_publish)
Confirm and publish the container to make it live.
```json
{
  "creation_id": "creation_id_123"
}
```
*Response*: Returns `{ "id": "live_post_id_999" }`.

---

## 4. Threads Thread Chaining

For draft payloads containing the delimiter `---thread-split---`, posts are posted sequentially. Each subsequent container creation payload must reference the parent post via the `reply_to_id` parameter:

**First Item (Post 1)**:
* POST `/threads` with `{"text": "Part 1"}` -> returns `c1`.
* POST `/threads_publish` with `{"creation_id": "c1"}` -> returns live post ID `post1`.

**Second Item (Post 2)**:
* POST `/threads` with `{"text": "Part 2", "reply_to_id": "post1"}` -> returns `c2`.
* POST `/threads_publish` with `{"creation_id": "c2"}` -> returns live post ID `post2`.

---

## 5. Failure Recovery & Orphan Containers

Due to the two-step dance, specific failure modes must be handled:

* **Orphan Container Scenario**: If Step 1 (Containerization) succeeds but Step 2 (Publishing) fails (due to connection timeouts, rate limits, or Meta outages), the container remains as an **orphan container** on Meta's servers.
* **Orchestrator Protocol**:
  * The orchestrator catches the `ThreadsPublishingError`.
  * Successfully published post IDs are logged in `draft.llm_metadata["threads_post_ids"]` along with `published_url` of the thread starter.
  * The draft transitions to `status = 'FAILED_PUBLISHING'`.
  * The orphan container `creation_id` is logged explicitly in the `feedback_notes` column (e.g. `"Publishing failed: ... Orphan container creation_id: c_orphan_abc"`) to notify the user.
