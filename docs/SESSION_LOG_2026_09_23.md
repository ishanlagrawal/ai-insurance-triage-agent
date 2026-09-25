# Engineering Journal & Session Log — 2026-09-23

## 1. Executive Summary & Status
Today we developed and verified the **AI Insurance Inbox Triage Agent** from foundational architecture up to live, end-to-end email ingestion and SMTP dispatch on the Hostinger VPS. All 4 n8n workflows are active, the FastAPI sidecar and dashboard are running on port `8008`, and live tests with real Gmail emails succeeded 100% green.

- **Current Progress:** Steps 1 through 5 are 100% complete and verified against live external email and Telegram.
- **Next Steps:** Step 6 (Synthetic Test Suite of 30 test cases) and Step 7 (Portfolio Packaging & Sanitized Export).

---

## 2. Chronological Milestones Completed Today

### Step 1: Database Architecture & Synthetic Seeding
- **Component:** `db/schema.sql`, `db/seed_data.py`, `db/insurance.db`.
- **Achievement:** 
  - Designed 12 relational SQLite tables matching enterprise insurance specs: `customers`, `policies`, `claims`, `support_tickets`, `triage_results`, `processed_emails`, `coverage_types`, `garages_hospitals`, `sla_policies`, etc.
  - Seeded 100% synthetic, realistic customer records, policies, and claims.
  - Verified constraints and indexes locally.

### Step 2: FastAPI Sidecar & Operations Dashboard
- **Component:** `api/main.py`, `api/templates/dashboard.html`, `docker-compose.yml`.
- **Achievement:**
  - Built Dockerized FastAPI sidecar (`insurance-triage-api`) bound to `127.0.0.1:8008`.
  - Exposed REST endpoints for deduplication (`/api/v1/dedup/check-and-record`), context retrieval (`/api/v1/customer/context`), triage persistence (`/api/v1/triage/log`), approval transitions (`/api/v1/triage/approve`), and KPI statistics (`/api/v1/stats`).
  - Implemented high-contrast, modern Ops Console dashboard at `http://127.0.0.1:8008/dashboard` with live 1-minute auto-refresh.

### Step 3: Intent Classification & Guardrail Engine
- **Component:** `workflows/01_subworkflow_classify_guardrail.json` (`InsTriageSubWf01`), `api/guardrails.py`.
- **Achievement:**
  - Integrated Google Gemini 2.5 Flash via native n8n HTTP Request node.
  - Built strict JSON schema validator for LLM output (`category`, `intent`, `priority`, `urgency_score`, `sentiment`, `suggested_reply`, `escalation_needed`).
  - Implemented deterministic regex fact-checking guardrails against SQLite context (verifies policy numbers, claim numbers, monetary amounts).
  - Enforced guardrail precedence: guardrail failures force `approval_status = 'AUTO_ESCALATED'` and `reply_status = 'SUPPRESSED'`.

### Step 4: Human-in-the-Loop Telegram Approval Gate & SLA Cron
- **Component:** `workflows/02_subworkflow_telegram_approval.json` (`InsTriageSubWf02`), `workflows/03_cron_sla_escalation.json` (`InsTriageCronSLA03`).
- **Achievement:**
  - Configured dedicated bot token `Telegram Insurance Triage Bot` (`YOUR_N8N_TELEGRAM_CRED_ID`) to prevent webhook collisions with other bots.
  - Added webhook origin security verification (`ADR-016`): validates `X-Telegram-Bot-Api-Secret-Token` on all incoming callbacks.
  - Implemented 15-minute cron job polling `/api/v1/triage/pending-expired?hours=4` to auto-escalate stagnant pending reviews.

### Step 5: Real Email Ingestion, Deduplication & SMTP Dispatch Orchestrator
- **Component:** `workflows/04_orchestrator_email_ingestion.json` (`InsTriageOrch04`), `api/main.py`.
- **Achievement:**
  - Added IMAP polling (`/api/v1/inbox/poll-unread`) querying Gmail IMAP SSL (`imap.gmail.com:993`) on a 1-minute schedule.
  - Enforced duplicate prevention via `processed_emails` table before invoking LLM.
  - Wired full orchestration: IMAP Poll -> Dedup -> Context Retrieval -> Subworkflow 01 -> Guardrail Gate -> Telegram Review Card -> Reviewer Approval -> Verified SMTP Dispatch (`smtp.gmail.com:465`) -> In-place Telegram audit stamp.

---

## 3. Deep-Dive: Bugs Encountered & Technical Resolutions

### 1. Telegram 64-Byte `callback_data` Limit (`BUTTON_DATA_INVALID`)
- **Symptom:** Workflow 04 threw `Bad Request: BUTTON_DATA_INVALID` on the `Send Telegram Approval Card` node.
- **Root Cause:** Standard Gmail RFC822 `Message-ID` headers are often 70+ bytes (e.g. `CAJB2TQh6RkUbrYDzih2yPrgVnyng7y2ayBL3wo_jqGiG+WPGKQ@mail.gmail.com`). Telegram Bot API strictly limits inline button `callback_data` to 64 bytes.
- **Resolution (ADR-017):**
  - Updated `Build Telegram Card` to pass the auto-incrementing database primary key `id` in callback queries (`APP:<id>` and `REJ:<id>`, requiring ~6 bytes).
  - Updated sidecar endpoints (`/api/v1/triage/approve`, `/api/v1/triage/dispatch-email`, `/api/v1/triage/update-telegram-meta`) to use dual lookup: `WHERE message_id = ? OR CAST(id AS TEXT) = ?`.

### 2. n8n HTTP Request JSON Body Serialization Failure
- **Symptom:** `Log Pending Triage (Passed Guardrail)` threw: `The value in the "JSON Body" field is not valid JSON`.
- **Root Cause:** Using raw string interpolation (`jsonBody: "={\n \"suggested_reply\": $json.suggested_reply\n}"`) broke when the LLM returned multiline draft replies with double quotes or newlines.
- **Resolution:**
  - Replaced inline string interpolation with dedicated JavaScript Code nodes (`Format Pending Payload`, `Format Escalated Payload`, `Format Meta Payload`).
  - Set `jsonBody: "={{ JSON.stringify($json.payload) }}"`, guaranteeing RFC8259 valid JSON output regardless of reply content.

### 3. Telegram Inline Keyboard Schema Mismatch
- **Symptom:** Telegram message was sent as plain text without inline keyboard buttons.
- **Root Cause:** Attempted to inject `reply_markup` as an ad-hoc property inside `additionalFields` rather than using n8n's native `replyMarkup: "inlineKeyboard"` fixed-collection schema.
- **Resolution:**
  - Reconfigured node parameters to match n8n's native schema:
    ```json
    "replyMarkup": "inlineKeyboard",
    "inlineKeyboard": {
      "rows": [
        {
          "row": {
            "buttons": [
              { "text": "✅ Approve & Send", "additionalFields": { "callback_data": "=APP:{{ $json.triage_ref }}" } },
              { "text": "❌ Reject", "additionalFields": { "callback_data": "=REJ:{{ $json.triage_ref }}" } }
            ]
          }
        }
      ]
    }
    ```

### 4. IMAP Fetch Flag Side-Effects in Polling Loops
- **Symptom:** After an initial failed execution, subsequent 1-minute schedule polls returned `{"count": 0, "emails": []}`.
- **Root Cause:** Default `mail.fetch(mid, "(RFC822)")` causes Gmail IMAP to set the `\Seen` flag immediately. Subsequent searches for `UNSEEN` returned empty arrays.
- **Resolution:**
  - Built `scripts/reset_test_email.py` to reset flags (`-FLAGS \Seen`) and clear `processed_emails` during iterative testing.

### 5. Telegram Metadata Missing on Initial Post
- **Symptom:** `Update Telegram Meta in DB` returned `400 Bad Request: message_id and telegram_message_id are required`.
- **Root Cause:** n8n Telegram node returns response in `result.message_id` and previous expression `$json.message_id` evaluated to undefined.
- **Resolution:**
  - Added `Format Meta Payload` Code node before the HTTP node:
    `const telMsgId = telResp.message_id || telResp.result?.message_id;`
    `const msgId = buildCard.message_id || splitEmail.message_id;`

### 6. Strict SMTP Dispatch Boundary
- **Rule Enforced:** Telegram approval only marks `approval_status = 'APPROVED'` and `reply_status = 'NOT_SENT'`. The subsequent physical SMTP send node is the exclusive owner of `reply_status = 'SENT'`.

### 7. Step 5 Refinement & Hardening (ADR-018)
- **Swallowed Exceptions in `dispatch_email`:** Removed faulty `except HTTPException: conn.close()` branch. Re-raised `HTTPException` cleanly and ensured database connection cleanup via `try...finally: conn.close()`. Verified 404 and 400 responses.
- **Dead Code Removal:** Deprecated and removed unused `mark_reply_sent` endpoint.
- **Truthful Audit Trail Sequencing:** Rewired Workflow 02 to answer the callback query immediately with a transient banner, gate dispatch behind `action === 'APPROVE'`, skip dispatch entirely on `REJECT`, and only edit the Telegram card to `✅ APPROVED & SENT` after the SMTP dispatch node confirms delivery.
- **Negative Failure State Audit:** Configured fallback card update in Workflow 02: if SMTP dispatch fails, the Telegram card updates to `⚠️ APPROVED by Reviewer ... Status: SMTP DISPATCH FAILED (reply_status: NOT_SENT)`. Verified empirically that `reply_status` in SQLite stays `NOT_SENT`.
- **Global Standards Enforced:**
  - Network timeouts: Enforced `timeout=15` on `IMAP4_SSL`, `SMTP_SSL`, and `SMTP`.
  - CRLF injection prevention: Stripped `\r` and `\n` from outgoing email subject headers.
  - Concurrency hardening: Switched SQLite database to `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;` and added `timeout=30.0` to `sqlite3.connect()`.
  - Automated linting: Added `scripts/run_lint.sh` (`ruff check api/`).

---

## 4. Empirical Test Verification Records

### Live Test 1:
- **Sender:** `tester@example.com`
- **Subject:** `Towing Support Needed for breakdowns`
- **Classification:** `Category: Roadside`, `Intent: ROADSIDE_ASSISTANCE`, `Priority: Critical`.
- **Guardrail:** `PASSED` (grounded).
- **Review:** Approved via Telegram.
- **Result:** SMTP sent real reply; database row 17 transitioned to `APPROVED` / `SENT`.

### Live Test 2:
- **Sender:** `tester@example.com`
- **Subject:** `Urgent: Accident claim status`
- **Classification:** `Category: Claims`, `Intent: CLAIM_STATUS`, `Priority: High`, `Sentiment: Frustrated`.
- **Guardrail:** `PASSED`.
- **Review:** Delivered with inline buttons; reviewer tapped `[Approve & Send]`.
- **Result:**
  - Subworkflow 02 executed 100% green (Webhook -> Verify Token -> Parse Callback -> Approve API -> Telegram Answer -> Telegram Edit -> Dispatch Email).
  - Real reply email received in Gmail inbox from `tester2@example.com`.
  - Database row 18 updated to `approval_status = 'APPROVED'`, `reply_status = 'SENT'`, `telegram_message_id = 7`.
  - Telegram card edited in-place with audit stamp: `ALREADY RESOLVED: APPROVED`.
  - Dashboard verified at `http://127.0.0.1:8008/dashboard`.

---

## 5. Live Architecture & Runtime Inventory

| Service / Workflow | Container / Identifier | Status | Port / URL |
|---|---|---|---|
| **FastAPI Sidecar** | `insurance-triage-api` | Healthy | `127.0.0.1:8008` |
| **Operations Dashboard** | Built into sidecar | Live | `http://127.0.0.1:8008/dashboard` |
| **SQLite Database** | `/docker/insurance-triage-agent/db/insurance.db` | Active | Local file |
| **Workflow 01 (LLM & Guardrails)** | `InsTriageSubWf01` | Active / Published | n8n internal subworkflow |
| **Workflow 02 (Telegram Approval)** | `InsTriageSubWf02` | Active / Published | Webhook: `/webhook/insurance-triage-approval-callback` |
| **Workflow 03 (SLA Cron)** | `InsTriageCronSLA03` | Active / Published | 15-minute cron |
| **Workflow 04 (Main Orchestrator)** | `InsTriageOrch04` | Active / Published | 1-minute schedule trigger |

---

## 6. Next Steps (To Resume In Future Session)
1. **Step 6: Synthetic Test Suite (Batch of 30)**
   - Create `tests/synthetic_emails.json` covering:
     - 8 core intents (Claim status, New claim, Claim delay, Document request, Policy details, Expiry, Renewal quote, Cashless garage locator).
     - Edge cases: spam/phishing, unidentified customer, intentional hallucination trigger.
   - Run test harness and record classification accuracy, latency, and guardrail interception rate.
2. **Step 7: Portfolio Packaging & Sanitized Export**
   - Export sanitized workflow JSONs with placeholder credentials.
   - Produce enterprise GitHub portfolio `README.md` with Mermaid sequence diagrams, UI screenshots, and setup guide.
