# ARCHITECTURE SPECIFICATION

> **IMPORTANT**: Before modifying or adding any files, the AI agent MUST read this file. Any proposed change that alters directory paths, removes existing API endpoints, modifies database schemas without migrations, or breaks core invariants is STRICTLY FORBIDDEN unless explicitly requested by the user.

## Repository Layout Tree

- `backend/` : Root of the Python FastAPI backend application.
  - `backend/app/api/` : Contains FastAPI routing, endpoints, and external API interfaces.
  - `backend/app/services/` : Core business logic, generation pipelines, and integrations.
  - `backend/app/models/` : SQLAlchemy database models and schemas.
  - `backend/tests/` : Pytest test suites.
- `branding-engine-ui/` : Frontend React/Next.js UI application.
- `.github/workflows/` : GitHub Actions CI/CD and automation scheduled workflows.
- `docs/` : Project documentation and guidelines.
- `static/` : Static assets.

## Core System Invariants (DO NOT MODIFY)

1. **Trigger & Scheduler**
   - `.github/workflows/daily-draft.yml` handles the multi-cron schedule, Render wake-up loops, and HMAC headers. This file is critical for automated posting.
2. **API Contract**
   - `POST /api/v1/automation/daily` must enforce the Idempotency key (`daily-automation-YYYY-MM-DD`) and perform constant-time secret checking.
3. **Publishing Pipeline**
   - `PublishingOrchestrator.publish_draft()` is the single source of truth for dispatching posts. It must correctly adhere to the LinkedIn REST API payload schema (`/rest/posts`).
4. **Fail-Safe Non-Blocking Rule**
   - Visual/Image generation failures MUST be caught gracefully. Any failure in image generation or image upload must not crash the transaction. Drafts must always publish as text-only if media upload fails.
