# LinkedIn Publishing Integration Guide

This document details the OAuth2 credentials connection, encrypted lifecycle token management, payload formatting, and failure recovery protocols for the LinkedIn publishing channel.

---

## 1. OAuth2 Connection Flow

To authenticate the client on behalf of a user, the engine follows the standard authorization code grant flow:

```
[Frontend Client]                  [FastAPI API Gateway]                 [LinkedIn API Server]
        │                                    │                                     │
        │ ── 1. Connect Redirect ──────────> │                                     │
        │    (User grants permissions)       │                                     │
        │                                    │ ── 2. Request Tokens (OAuth) ─────> │
        │                                    │    (Exchange auth code)             │
        │                                    │                                     │
        │                                    │ <── 3. Access/Refresh Tokens ────── │
        │                                    │                                     │
        │                                    │ ── 4. Fetch User Profile URN ─────> │
        │                                    │                                     │
        │                                    │ <── 5. User URN (urn:li:person:*) ─ │
        │                                    │                                     │
        │ <── 6. Connection Connected ────── │                                     │
        │    (Encrypted credentials saved)   │                                     │
```

1. **Authorization Request**: The frontend redirects the user to LinkedIn's OAuth authorize link with required scopes: `w_member_social` (to post content) and `openid profile` (to discover URN).
2. **Callback Endpoint**: LinkedIn redirects the user back to the backend endpoint `/api/v1/publishing/linkedin/connect?code=...`.
3. **Token Exchange**: The API gateway invokes `LinkedInClient.exchange_code_for_tokens(code)` to exchange the code for access and refresh tokens.
4. **URN Fetching**: The API retrieves the user's personal principal URN from `/v2/userinfo`.
5. **Database Registration**: Creates or updates a `LinkedInAccount` record, encrypting credentials before saving.

---

## 2. Encrypted Token Lifecycle

Integration credentials represent high-severity access vectors and are protected at the database level:

### 2.1 Encryption & Decryption (AES-256-GCM)
* **Fernet Recipe**: Tokens are encrypted using the Fernet symmetric envelope recipe.
* **Environment Sourcing**: Sourced from the `ENCRYPTION_KEY` environment variable.
* **Storage format**: Encrypted strings stored in `linkedin_accounts` table. Decrypted on-demand only inside memory during request lifecycles.

### 2.2 Expiration & Automatic Refresh
Before dispatching any publication payload, the `LinkedInClient` evaluates access token validity:
* **Expiry Evaluation**: If `account.expires_at <= datetime.now() + 5 minutes`, a refresh is triggered.
* **Exchange Call**: Dispatches a `refresh_token` grant request to `/oauth/v2/accessToken`.
* **Database Update**: The returned new access and refresh token values are encrypted, `expires_at` is updated, and changes are committed.

---

## 3. LinkedIn Posts API Payload Structure

Post bodies are compiled to target LinkedIn's modern `/v2/posts` endpoint:

```json
{
  "author": "urn:li:person:abc123XYZ",
  "commentary": "Draft post text goes here...",
  "visibility": "PUBLIC",
  "distribution": {
    "feedDistribution": "MAIN_FEED",
    "targetEntities": []
  },
  "lifecycleState": "PUBLISHED"
}
```

---

## 4. Failure Recovery Patterns

The `PublishingOrchestrator` implements strict recovery boundaries:

* **State updates on Success (HTTP 201)**: The draft transitions `status = 'PUBLISHED'`. The created post URN is logged inside `draft.llm_metadata["linkedin_post_id"]` along with a clickable `published_url` helper.
* **State updates on Failure**: If the client encounters a 401 (expired/revoked authorization), 429 (rate limits), or 400 (formatting payload exception):
  * The transition transitions `status = 'FAILED_PUBLISHING'`.
  * The raw error string response is logged inside the `feedback_notes` column to notify the user.
