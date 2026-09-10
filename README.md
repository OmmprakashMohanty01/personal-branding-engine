# 🚀 Personal Branding Engine

> An autonomous, AI-powered content generation and LinkedIn publishing platform — built with FastAPI, React/Next.js, SQLite, and GitHub Actions CI/CD.

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-Next.js-black?logo=next.js)](https://nextjs.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![CI](https://github.com/OmmprakashMohanty01/personal-branding-engine/actions/workflows/daily-draft.yml/badge.svg)](https://github.com/OmmprakashMohanty01/personal-branding-engine/actions)

---

## 📌 Overview

**Personal Branding Engine** automates the creation and publishing of professional LinkedIn posts. It uses a multi-stage AI pipeline — research → content drafting → semantic visual direction → human review → one-click publish — with a fully interactive UI and scheduled GitHub Actions automation.

**Key capabilities:**
- 🧠 **AI Content Drafting** — Gemini-powered drafts tailored to personal tone and technical niche
- 🎨 **Visual Director** — Semantic image generation with structured prompt engineering (avoids generic imagery)
- ✅ **Human-in-the-Loop** — Approval-gated publishing via a web dashboard
- 📅 **Scheduled Automation** — Daily GitHub Actions cron (04:00 UTC → 9:30 AM IST) with HMAC-secured webhook calls
- 📊 **Publish History** — SQLite-backed log of all published posts with status tracking

---

## 🏗️ System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        GitHub Actions (CI/CD)                     │
│  daily-draft.yml  →  Render wake-up loop  →  HMAC-secured POST   │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                    ┌───────────▼──────────────┐
                    │    FastAPI Backend         │
                    │  (backend/app/)            │
                    │                           │
                    │  ┌─────────────────────┐  │
                    │  │  PublishingOrchest. │  │  ← single source of truth
                    │  │  (services/)        │  │     for LinkedIn dispatch
                    │  └─────────┬───────────┘  │
                    │            │               │
                    │  ┌─────────▼───────────┐  │
                    │  │  VisualDirector     │  │  ← semantic image prompting
                    │  │  (services/)        │  │     + graceful failure
                    │  └─────────┬───────────┘  │
                    │            │               │
                    │  ┌─────────▼───────────┐  │
                    │  │  SQLite (SQLAlchemy) │  │  ← drafts + publish log
                    │  │  (models/)          │  │
                    │  └─────────────────────┘  │
                    └───────────┬──────────────┘
                                │  REST API
                    ┌───────────▼──────────────┐
                    │  React / Next.js Frontend │
                    │  (branding-engine-ui/)    │
                    │                           │
                    │  Dashboard → Draft Review │
                    │  → Approve → Publish      │
                    └──────────────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11, FastAPI, SQLAlchemy, Pydantic |
| **Frontend** | React, Next.js, Tailwind CSS |
| **Database** | SQLite (`branding_engine.db`) |
| **AI / LLM** | Google Gemini API |
| **Image Generation** | Gemini Imagen / VisualDirector pipeline |
| **Publishing API** | LinkedIn REST API (`/rest/posts`) |
| **CI/CD** | GitHub Actions, Render (hosting) |
| **Auth** | HMAC-SHA256 signed webhook secrets |

---

## 📁 Repository Structure

```
personal-branding-engine/
├── backend/
│   └── app/
│       ├── api/          # FastAPI routers & endpoints
│       ├── services/     # Business logic: PublishingOrchestrator, VisualDirector
│       └── models/       # SQLAlchemy models, Pydantic schemas
│       └── tests/        # Pytest test suites
├── branding-engine-ui/   # Next.js frontend dashboard
├── .github/
│   └── workflows/
│       └── daily-draft.yml   # Scheduled automation (cron @ 04:00 UTC)
├── docs/                 # Project documentation
├── render.yaml           # Render hosting config
└── ARCHITECTURE_SPEC.md  # Core system invariants (read before modifying)
```

---

## 🚀 Setup & Installation

### Prerequisites
- Python 3.11+
- Node.js 18+
- A Google Gemini API key
- A LinkedIn developer app (Client ID + Secret + OAuth token)

### Backend

```bash
# Clone the repo
git clone https://github.com/OmmprakashMohanty01/personal-branding-engine.git
cd personal-branding-engine/backend

# Create a virtual environment
python -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your GEMINI_API_KEY, LINKEDIN_ACCESS_TOKEN, WEBHOOK_SECRET

# Run the dev server
uvicorn app.main:app --reload
```

### Frontend

```bash
cd branding-engine-ui
npm install
npm run dev
# Open http://localhost:3000
```

### Key API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/automation/daily` | Trigger daily draft generation (HMAC-secured) |
| `GET` | `/api/v1/drafts` | List all drafts pending review |
| `POST` | `/api/v1/drafts/{id}/approve` | Approve and publish a draft to LinkedIn |
| `GET` | `/api/v1/publish-log` | View publish history |

---

## 🔒 Core Design Constraints

| Constraint | Detail |
|---|---|
| **Idempotency** | Daily automation enforces key `daily-automation-YYYY-MM-DD` to prevent duplicate posts |
| **Constant-time auth** | HMAC webhook secret uses constant-time comparison to prevent timing attacks |
| **Fail-safe publishing** | Image generation failures are caught gracefully — posts always publish as text-only if media upload fails |
| **Single dispatch source** | `PublishingOrchestrator.publish_draft()` is the only place that calls LinkedIn's `/rest/posts` API |

---

## 📄 License

MIT © [Ommprakash Mohanty](https://github.com/OmmprakashMohanty01)
