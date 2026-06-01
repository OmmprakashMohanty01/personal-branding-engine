# Content Curation & Approval State Machine Guide

This document details the state transition rules, API integrations, and feedback iteration mechanisms for the content review lifecycle.

---

## 1. State Machine Transitions

Every generated piece of content (stored inside the `ContentDraft` table) is subjected to a strict state transition manager.

```
       ┌───────────┐           ┌────────────────────┐
       │   DRAFT   │ ────────> │  PENDING_APPROVAL  │
       └─────┬─────┘           └─────────┬──────────┘
             │                           │
             ├───────────────────────────┼───────────────────────────┐
             │                           │                           │
             ▼                           ▼                           ▼
       ┌───────────┐               ┌───────────┐               ┌───────────┐
       │ APPROVED  │               │ REJECTED  │               │ PUBLISHED │
       └───────────┘               └─────┬─────┘               └───────────┘
                                         │
                                         ▼ (via /revise)
                                ┌───────────────────┐
                                │ PENDING_APPROVAL  │
                                └───────────────────┘
```

* **DRAFT**: Newly seeded drafts or manually queued content pieces. Allowed transitions: `PENDING_APPROVAL`, `APPROVED`, `REJECTED`.
* **PENDING_APPROVAL**: Draft is locked and ready for editor curation review. Allowed transitions: `APPROVED`, `REJECTED`.
* **APPROVED**: Terminal state in the curation lifecycle. Re-routing or state modifications are disallowed.
* **REJECTED**: Draft is archived. May be moved back to `PENDING_APPROVAL` ONLY by requesting a revision.

---

## 2. API Contracts & Endpoints

The API router handles operations inside `/api/v1/approvals/`:

* **`GET /approvals/pending`**: List drafts with status `DRAFT` or `PENDING_APPROVAL`.
  * *Query parameters*: `platform` (optional, e.g. `linkedin`).
  * *Response*: List of `DraftResponse` JSON objects.
* **`POST /approvals/{draft_id}/approve`**: Transition draft status to `APPROVED`.
  * *Request Body*:
    ```json
    {
      "edited_content": "Optional modified content string override."
    }
    ```
  * *Actions*: Updates `final_content` column (falls back to `content_text` if payload value is empty), transitions `status = 'APPROVED'`, and timestamps `approved_at`.
* **`POST /approvals/{draft_id}/reject`**: Transition draft status to `REJECTED`.
  * *Request Body*:
    ```json
    {
      "reason": "Rejection notes details."
    }
    ```
  * *Actions*: Transitions `status = 'REJECTED'` and logs the reason inside `feedback_notes`.
* **`POST /approvals/{draft_id}/revise`**: Trigger an LLM rewrite loop.
  * *Request Body*:
    ```json
    {
      "feedback_notes": "Tweak parameters, e.g., make it shorter."
    }
    ```
  * *Actions*: Instantiates `GenerationOrchestrator`, compiles a user adjustment prompt containing the feedback, requests regeneration, overwrites `content_text`, resets `status = 'PENDING_APPROVAL'`, and updates `generated_at`.

---

## 3. Feedback Loop Integration

Feedback notes supplied during revision are integrated directly into the LLM prompt. The `PromptFactory` merges this feedback under the `USER_TEMPLATE` prompt block:

```jinja2
{% if feedback %}
User feedback adjustment request:
"{{ feedback }}"
Modify the generation to address this feedback request.
{% endif %}
```
This forces the LLM provider to review the previous layout, incorporate the tweak requested by the user, and deliver a more aligned draft post.
