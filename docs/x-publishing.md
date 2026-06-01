# X (Twitter) Publishing Integration Guide

This document details the OAuth2 credentials connection using PKCE (Proof Key for Code Exchange), encrypted lifecycle token management, thread splitting logic, API constraints, and failure recovery protocols for the X (Twitter) publishing channel.

---

## 1. OAuth2 Connection Flow with PKCE

To authenticate the client on behalf of a user, the engine follows the standard OAuth 2.0 Authorization Code Flow with PKCE:

```
[Frontend Client]                  [FastAPI API Gateway]                     [X API Server]
        │                                    │                                     │
        │ ── 1. Connect Redirect ──────────> │                                     │
        │    (User grants permissions)       │                                     │
        │                                    │ ── 2. Exchange Code & PKCE ───────> │
        │                                    │    (Exchanges code + verifier)      │
        │                                    │                                     │
        │                                    │ <── 3. Access/Refresh Tokens ────── │
        │                                    │                                     │
        │                                    │ ── 4. Fetch User Profile ─────────> │
        │                                    │    (/2/users/me)                    │
        │                                    │                                     │
        │                                    │ <── 5. User Details ─────────────── │
        │                                    │                                     │
        │ <── 6. Connection Connected ────── │                                     │
        │    (Encrypted credentials saved)   │                                     │
```

1. **Authorization Request**: The frontend redirects the user to X's OAuth 2.0 authorize link with the required scopes: `tweet.read`, `tweet.write`, `users.read`, and `offline.access` (to obtain a refresh token). It generates and caches a `code_verifier` and a `code_challenge`.
2. **Callback Endpoint**: X redirects the user back to the backend endpoint `/api/v1/publishing/x/connect?code=...&state=...`.
3. **Token Exchange**: The API gateway invokes `XClient.exchange_code_for_tokens(code, redirect_uri, code_verifier)` to exchange the code and PKCE verifier for access and refresh tokens.
4. **Profile Fetching**: The API retrieves the user's Twitter ID and username from `GET /2/users/me`.
5. **Database Registration**: Creates or updates an `XAccount` record, encrypting credentials using a symmetric key before database persistence.

---

## 2. Encrypted Token Lifecycle

Integration credentials represent high-severity access vectors and are protected at the database level:

### 2.1 Encryption & Decryption
* **Fernet Envelope**: Tokens are encrypted using the symmetric Fernet recipe.
* **Environment Sourcing**: The encryption key is sourced from the `ENCRYPTION_KEY` environment variable.
* **Storage format**: Encrypted strings are stored in the `x_accounts` table. Decrypted on-demand only inside memory during request lifecycles.

### 2.2 Expiration & Automatic Refresh
Before dispatching any publication payload, the `XClient` evaluates access token validity:
* **Expiry Evaluation**: If `account.expires_at <= datetime.now() + 5 minutes`, a refresh is triggered.
* **Exchange Call**: Dispatches a `refresh_token` grant request to `/2/oauth2/token` containing the encrypted refresh token.
* **Database Update**: The returned new access and refresh token values are encrypted, `expires_at` is updated, and changes are committed.

---

## 3. X API v2 Payload & Threading Architecture

X limits free tier publications to text-only tweets under 280 characters. For drafts exceeding this length, the system splits content using the standard thread split marker `---thread-split---`.

### 3.1 Single Tweet Payload
For single-part tweets, the post body is sent directly to `POST /2/tweets`:
```json
{
  "text": "This is a single tweet."
}
```

### 3.2 Thread Chain Chaining
For threads, the first tweet is posted to generate a base tweet ID. Subsequent tweets are chained using the `reply.in_reply_to_tweet_id` property:

**1. First Tweet Request (POST /2/tweets)**:
```json
{
  "text": "Thread part 1..."
}
```
*Response*: Returns `{ "data": { "id": "11223344" } }`.

**2. Second Tweet Request (POST /2/tweets)**:
```json
{
  "text": "Thread part 2...",
  "reply": {
    "in_reply_to_tweet_id": "11223344"
  }
}
```
*Response*: Returns `{ "data": { "id": "55667788" } }`.

This sequence repeats until all thread segments are successfully posted.

---

## 4. Constraints & Free Tier Restrictions

The X Free tier has strict limits that this integration enforces:
* **Rate Limits**: Strictly capped at **50 posts per day** per user.
* **Media Limits**: The Free tier does not support media uploads (images/videos) via the v2 API. The integration is restricted to text-only posts.

---

## 5. Failure Recovery & Partial Thread Protocol

The `PublishingOrchestrator` implements strict recovery boundaries:

* **State updates on Success (HTTP 201)**: The draft status transitions to `PUBLISHED`. The list of created tweet IDs is saved inside `draft.llm_metadata["x_tweet_ids"]` along with a clickable `published_url` helper linking to the thread starter.
* **State updates on Partial Thread Failure**: If a thread publishing loop fails midway (e.g., tweet 1 succeeds, but tweet 2 fails due to rate limits):
  * The orchestrator catches the `XPublishingError` exception.
  * Successfully posted tweet IDs are preserved in `draft.llm_metadata["x_tweet_ids"]` (and `published_url` is updated with the first successfully posted tweet link).
  * The draft status transitions to `FAILED_PUBLISHING`.
  * The error notes are logged inside `feedback_notes` indicating exactly where the thread posting failed to allow manual verification and recovery.
