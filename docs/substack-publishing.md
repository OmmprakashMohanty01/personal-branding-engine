# Substack Publishing Integration Guide

This document details the architectural pivot, SMTP configuration, markdown parsing (title extraction and HTML body conversion), and error boundaries for the Substack publishing channel.

---

## 1. Architectural Pivot: SMTP vs. REST

Unlike LinkedIn, X, or Threads, which utilize HTTP REST APIs and complex OAuth 2.0 authorization code flows, the Substack integration utilizes an **architectural pivot to SMTP**. 

Substack does not provide a public posting API for external developer integrations. Instead, it offers a secure **"Email-to-Publish"** ingestion feature. Authorised authors can send rich text or HTML emails to a secret, unique Substack draft email address. Upon receiving the email, Substack parses the email body and converts it into a pending post draft on the user's dashboard.

```
[FastAPI Backend Engine]                 [SMTP Mail Server]                     [Substack Ingest Server]
           │                                      │                                         │
           │ ── 1. Connect & Auth ──────────────> │                                         │
           │    (SMTP / STARTTLS / SSL)           │                                         │
           │                                      │ ── 2. Route Ingestion Mail ───────────> │
           │                                      │    (From: authorized@domain.com)        │
           │                                      │    (To: secret-ingest@substack.post)    │
           │                                      │                                         │
           │ <── 3. Dispatch Acknowledgment ───── │                                         │
           │                                      │                                         │
           │                                      │                                         │ [User Substack Dashboard]
           │                                      │                                         │           │
           │                                      │ <── 4. Ingest and parse email as draft ────────────> │
```

---

## 2. Ingestion Flow & Payload Builder

When a draft is approved for Substack:

1. **Title Extraction**: The engine parses the content and extracts the first non-empty line of the draft (usually an H1 title or bold header). It strips out markdown delimiters (e.g. `#` hashes and `**` bold asterisks) and uses it as the **Email Subject**. Substack translates this subject into the **Post Title**.
2. **HTML Body Conversion**: The remainder of the markdown draft is parsed into standard HTML using the python `markdown` package. Standard extensions (`fenced_code` for syntax highlighting and `tables` for data structures) are explicitly enabled to preserve formatting.
3. **MIMEMultipart Assembly**: Constructs a `MIMEMultipart("alternative")` email payload, attaching the HTML version as a standard text/html mime-type.
4. **Asynchronous Dispatch**: The client connects to the configured global SMTP server in a non-blocking thread pool (`asyncio.to_thread`) to avoid blocking the API gateway, and dispatches the email to the secret Substack address.

---

## 3. Substack Configurations

No OAuth redirects are required. To connect the newsletter:
1. Call `POST /api/v1/publishing/substack/config` with:
   * `newsletter_name`: A descriptive name for the newsletter.
   * `secret_email_address`: The secret Substack draft address.
   * `author_email`: The email address authorized to post to the newsletter.
2. The details are stored in the `substack_accounts` table.

### How to Find Your Secret Draft Email on Substack
1. Log in to your **Substack Dashboard**.
2. Go to **Settings** in the left navigation bar.
3. Scroll down or search for **Email settings**.
4. Locate the section titled **Post by email**.
5. Copy the unique email address shown there (it usually ends in `@substack.post`).
6. *Ensure the email address configured as `author_email` in the brand engine is added to your Substack account as an author/contributor.* Substack silently discards emails sent from unauthorized senders.

---

## 4. Environment Setup

Configure the SMTP credentials in your `.env` file (see [backend/.env.example](file:///Users/ommprakashmohanty/.gemini/antigravity-ide/scratch/personal-branding-engine/backend/.env.example)):
```ini
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_sending_email_address@gmail.com
SMTP_PASSWORD=your_sending_email_password
```
*Port 465 triggers an SSL connection (`smtplib.SMTP_SSL`). Any other port (such as 587) establishes a TLS connection (`smtplib.SMTP` calling `.starttls()`).*

---

## 5. Failure Recovery Protocols

The `PublishingOrchestrator` implements recovery boundaries:
* **State updates on Success**: Sets status to `PUBLISHED` and updates `draft.llm_metadata` indicating successful SMTP dispatch.
* **SMTP Exception handling**: If the SMTP server returns an authentication failure (535), connection timeout, or invalid sender rejection, the orchestrator catches `smtplib.SMTPException`, transitions the draft status to `FAILED_PUBLISHING`, and records the exact SMTP error details in `feedback_notes` to allow corrective action.
