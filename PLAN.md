# Master Plan: AI Insurance Inbox Triage Agent (n8n + Hostinger VPS)

## 1. Resource Footprint & Impact Assessment

### Current VPS Health
- **RAM:** 7.8 GiB total | 3.9 GiB used | **3.8 GiB available** (49% free).
- **Swap:** 8.0 GiB total | **7.1 GiB available**.
- **Disk:** 96 GiB total | 69 GiB used | **27 GiB available** (72% utilized).

### Projected Resource Consumption of This Project
- **RAM:** ~45–70 MiB (FastAPI + SQLite sidecar service) + ~5 MiB during active n8n workflow execution.
  - *Impact:* **< 1% of total RAM**.
- **Disk:** ~35–60 MB total (codebase, virtualenv/container, SQLite DB with thousands of synthetic records).
  - *Impact:* **< 0.2% of free disk space (out of 27 GB available)**.
- **Port:** Internal port `8008` (verified completely free and unused).

### Impact on Existing Services
- **ZERO impact / NO collision:**
  - Existing folders (`hermes-agent-p5vk`, `money-printer`, `traefik`, `newspaper-pipeline`, `video-use-bot`, etc.) will NOT be touched.
  - Existing n8n workflows (`LaunchWithAI - Approval Handler`, `content-scheduler`, `linkedin-comment-drafter`, etc.) will continue running without interruption.
  - All new files remain isolated inside `/docker/insurance-triage-agent/`.

---

## 2. 100% Free-Tier & Model Provider Strategy

- **Groq Removed:** No longer free; removed from architecture.
- **Primary LLM Reasoning:** **Google Gemini Free Tier** (via `GEMINI_API_KEY`):
  - Uses `gemini-2.5-flash` or `gemini-1.5-flash` (15 RPM, 1500 RPD, zero cost).
  - Leverages existing n8n pattern: HTTP Request node to `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent`.
- **Secondary / Alternative LLM:** **Inception Free Models** (via `INCEPTION_API_KEY`):
  - Configurable as primary or fallback classifier.
- **Email:** Gmail App Password via standard IMAP/SMTP (zero cost).
- **Human-in-the-Loop:** Telegram Bot (zero cost, follows existing Telegram bridge / webhook pattern in `/docker/n8n`).
- **Database & Dashboard:** SQLite (zero memory overhead) + lightweight FastAPI service (port 8008).
- **Total Operational Cost:** **$0.00 / month**.

---

## 3. Why SQLite + FastAPI Sidecar Matches Your n8n Setup

By inspecting existing workflows in `/docker/n8n/workflows/`:
1. n8n heavily utilizes **HTTP Request nodes** with JSON payloads to interface with APIs and webhooks.
2. Official n8n Docker image has no SQLite node and no python/sqlite3 packages.
3. Dedicated **FastAPI sidecar service in `/docker/insurance-triage-agent/`**:
   - Manages SQLite schema & 100% synthetic seed data.
   - Exposes clean REST endpoints (`/api/v1/dedup`, `/api/v1/context`, `/api/v1/triage`, `/api/v1/stats`) called via standard n8n HTTP Request nodes.
   - Hosts the **Step 19 Enterprise Operations Dashboard** directly on port 8008 without overloading n8n with complex HTML webhook rendering.
   - Makes the repository 100% portable for GitHub portfolio (`docker compose up` + import workflow JSON).

---

## 4. GitHub Portfolio Strategy

1. **Two-Tier Hallucination Prevention:** Highlight deterministic regex/schema validation preventing invented policy/claim numbers.
2. **Deterministic Idempotency:** Watermark + SQLite unique constraints on message IDs to prevent duplicate email replies.
3. **Interactive Demo:** Clean README with Mermaid architecture diagram, visual workflow screenshot, and dashboard preview.
4. **Reproducible Test Harness:** 30 synthetic test emails covering 8 core intents, edge cases, spam, and unidentified customers.

---

## 5. Directory Layout

```
/docker/insurance-triage-agent/
├── PLAN.md                    # Architecture, resource audit, and build roadmap
├── README.md                  # Portfolio documentation, setup, credentials guide
├── .gitignore                 # Ignores *.db, .env, credentials, logs
├── docker-compose.yml         # Sidecar API + Dashboard container definition
├── db/
│   ├── schema.sql             # SQLite tables (customers, policies, claims, tickets, etc.)
│   ├── seed_data.py           # Synthetic test data seeder (100% fake data)
│   └── insurance.db           # SQLite database file (gitignored)
├── api/
│   ├── main.py                # FastAPI endpoints for n8n + Dashboard UI
│   ├── guardrails.py          # Hallucination checking logic & entity matching
│   └── templates/
│       └── dashboard.html     # Minimal enterprise dashboard (Step 19 spec)
├── workflows/
│   ├── 01_subworkflow_classify_guardrail.json  # Sanitized modular sub-workflow
│   └── 02_main_email_triage_orchestrator.json # Main n8n workflow
└── tests/
    ├── synthetic_emails.json  # 30 realistic test emails (8 intents + edge cases)
    └── send_test_emails.py    # Test runner script
```

---

## 6. Step-by-Step Implementation Roadmap

### Step 1: Project Foundation & SQLite Schema
- Set up `/docker/insurance-triage-agent/` structure, `.gitignore`, and `docker-compose.yml`.
- Create `db/schema.sql` (10 tables matching PDF spec) and `db/seed_data.py` (synthetic test data).
- Verify SQLite queries locally on VPS.

### Step 2: Lightweight Service & Minimal Dashboard (Port 8008)
- Build FastAPI endpoints for dedup, customer context retrieval, and triage logging.
- Implement `api/templates/dashboard.html` matching Step 19 enterprise specifications (Inter font, KPI cards, ticket queue, detail drawer).

### Step 3: LLM Intent Classification & Hallucination Guardrail Sub-Workflow
- Build n8n Sub-workflow:
  - Input: clean email body + retrieved customer context JSON.
  - HTTP Request Node -> Gemini Flash (using existing n8n HTTP pattern) or Inception.
  - Code Node 1: Strict JSON parser and fallback handler.
  - Code Node 2: **Hallucination Validator** (regex checks that referenced policy/claim numbers belong to the customer context).
  - Output: normalized JSON `{ category, intent, priority, urgency_score, sentiment, suggested_reply, guardrail_passed, rejection_reason }`.

### Step 4: Human-in-the-Loop Approval Gate (Telegram Integration)
- **Reference Document:** Detailed in `docs/STEP4_PLAN.md`.
- **Bot Credential:** Dedicated `TELEGRAM_BOT_TOKEN_INSURANCE_TRIAGE` + `TELEGRAM_CHAT_ID`. Never shared with `TELEGRAM_BOT_TOKEN_n8n_APPROVAL` to prevent Telegram webhook collision.
- **Message Content:**
  - Sender: `customer_name (email)` or `⚠️ UNIDENTIFIED SENDER`.
  - Intent, category, priority, urgency score (1-5).
  - Referenced `policy_number` / `claim_number`.
  - Guardrail status: `✅ PASSED`.
  - Truncation notice (if `was_truncated == true`).
  - Full `suggested_reply` text block.
- **Inline Action Buttons & Correlation:**
  - `[✅ Approve & Send]` with `callback_data: "APP:<message_id>"`.
  - `[❌ Reject & Escalate]` with `callback_data: "REJ:<message_id>"`.
  - Multi-message correlation via immutable `message_id` (fits inside 64-byte Telegram limit).
  - Out-of-order execution safe; zero race conditions.
  - Updates card via `editMessageText` on click to prevent double-clicks.
- **Status Mapping & Idempotency:**
  - `POST /api/v1/triage/approve` strictly enforces atomic `WHERE approval_status = 'PENDING'` with `rowcount == 1`. Non-`PENDING` calls return a safe no-op response.
  - Approve: `approval_status = 'APPROVED'`, `reply_status = 'NOT_SENT'`. (Note: Step 5 SMTP dispatch node owns transition to `'SENT'` upon delivery).
  - Reject: `approval_status = 'REJECTED'`, `reply_status = 'SUPPRESSED'`, `escalation_needed = 1`.
- **Reviewer Inaction (Approved Option A — 4-Hour SLA Auto-Escalation):**
  - Standalone cron workflow: `workflows/03_cron_sla_escalation.json` (runs every 15 min).
  - Queries sidecar `GET /api/v1/triage/pending-expired?hours=4`.
  - Transitions to `approval_status = 'AUTO_ESCALATED'`, `reply_status = 'SUPPRESSED'`, `escalation_needed = 1`.
  - Edits Telegram card to `[⚠️ AUTO-ESCALATED: 4-Hour SLA Expired]`.




### Step 5: Email Ingestion, Dedup & Auto-Reply Dispatch (Main Workflow)
- In n8n, build main orchestrator:
  - Trigger: IMAP / Gmail polling (1 min interval).
  - Dedup check against SQLite service.
  - Preprocess & sanitize HTML body.
  - Fetch customer context via HTTP node.
  - Call Sub-workflow (Step 3).
  - Spam / Safety Filter IF node.
  - Telegram Approval Gate (Step 4).
  - SMTP Send Node (`Re: <subject>`).
  - Log execution result to SQLite & CSV.

### Step 6: End-to-End Test Suite with 30 Synthetic Emails
- Generate `tests/synthetic_emails.json` with 30 test cases covering:
  - Claim status, New claim, Claim delay, Document request.
  - Policy details, Policy expiry, Renewal quote.
  - Cashless claim & garage locator.
  - Spam / phishing.
  - Unidentified customer.
  - Hallucination trigger attempt (non-existent policy).
- Run test runner script to validate end-to-end processing.

### Step 7: Portfolio Packaging & Sanitized Export
- Export sanitized workflow JSONs with placeholder credential names.
- Create comprehensive `README.md` and architecture diagram.

---

## 7. Open Questions for User Approval

1. **Email Connection:** Do you prefer using **IMAP/SMTP** with a Gmail App Password, or setting up **Gmail OAuth2** in n8n? *(IMAP/SMTP recommended for fastest setup on throwaway account).*
2. **Approval Bot:** Should we route approvals through the existing `TELEGRAM_BOT_TOKEN_n8n_APPROVAL` bot or a dedicated bot token?
