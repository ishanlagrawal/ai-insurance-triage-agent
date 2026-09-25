# Step 5: Email Ingestion, Deduplication & Auto-Reply Dispatch Orchestrator

## 1. Executive Summary & Design Principles

Step 5 builds the top-level orchestration layer that ingests incoming customer emails, executes idempotency/deduplication checks, enriches context from the SQLite database via the FastAPI sidecar, invokes the LLM classification & guardrails engine (Sub-workflow 01), and enforces an absolute **100% Human-in-the-Loop Approval Gate** via Telegram prior to dispatching responses over SMTP.

### Core Architecture Rules:
1. **Zero Auto-Bypass Policy:** 100% of emails with valid generated drafts (whether Low, Medium, High, or Critical priority) **MUST** route through Telegram for human review (`APP:<id>` or `REJ:<id>`). No draft email is ever dispatched without a human click.
2. **Strict Dispatch Ownership:** Only the SMTP dispatch node transitions `reply_status` to `'SENT'` after verified transmission over the wire. Neither LLM, nor sidecar ingestion, nor reviewer approval marks it `'SENT'`.
3. **Decoupled Asynchronous State Machine:** Long-running in-memory "Wait" nodes in n8n do not survive container restarts or server reboots. Step 5 separates ingestion from dispatch:
   - **Pipeline A (Ingestion & Card Generation):** Ingests email -> Dedup -> Sidecar Context -> Sub-workflow 01 -> Writes `PENDING` / `NOT_SENT` to SQLite -> Posts interactive Telegram card -> **Terminates cleanly**.
   - **Pipeline B (Dispatch Trigger):** When reviewer clicks **Approve** in Telegram, Sub-workflow 02 immediately answers the callback query (instant UI feedback), atomically updates the database, sends the approved reply via SMTP, and marks `reply_status = 'SENT'`.

---

## 2. Ingestion & Dispatch Orchestration Order

```
[Customer Email Arrives]
         │
         ▼
[1. Email Trigger (IMAP / Poller)]
         │
         ▼
[2. Deduplication Check (Sidecar: POST /api/v1/dedup/check-and-record)]
   ├── duplicate == true ──► [Log & Halt: Duplicate ignored]
   └── duplicate == false (Recorded in processed_emails)
         │
         ▼
[3. Customer Context Retrieval (Sidecar: GET /api/v1/customer/context?email=...)]
   - Pull customer profile, active policies, recent claims, open tickets
         │
         ▼
[4. Execute Sub-workflow 01 (Gemini 2.5 Flash + Guardrail Verifier)]
   - Relies on Sub-workflow 01's existing, verified sanitization (ADR-012):
     zero-width stripping + 8,000 char prompt boundary.
   - Deterministic guardrail check (Grounding, PII, Scope limits)
         │
         ▼
[5. Guardrail Status Branch]
   ├── FAILED (Hallucination / Toxic / Scope Leak)
   │     │
   │     ▼
   │   [Sidecar: POST /api/v1/triage/ingest]
   │     - approval_status = 'AUTO_ESCALATED'  (Valid CHECK constraint value)
   │     - reply_status = 'SUPPRESSED'
   │     - escalation_needed = 1
   │     - suggested_reply = ""
   │     - Support Ticket created as Open/Critical
   │     - Halt (No Telegram Card sent to reviewer; routed straight to human desk)
   │
   └── PASSED
         │
         ▼
[6. Sidecar Ingestion (POST /api/v1/triage/ingest)]
   - approval_status = 'PENDING'
   - reply_status = 'NOT_SENT'
         │
         ▼
[7. Post Telegram Review Card (Telegram Bot API)]
   - Card context: Customer name/email, Intent, Category, Priority, Urgency score,
     Full suggested reply, Guardrail PASSED badge.
   - Inline Keyboard: [✅ Approve & Send] [❌ Reject]
   - Capture `telegram_message_id` & `chat_id` -> update triage record.
   - Pipeline A terminates cleanly.
```

---

## 3. Asynchronous Resolution: How Dispatch Works Without In-Workflow Waiting & Without Blocking Telegram UX

### Step-by-Step Flow in Sub-workflow 02:
1. **Webhook Ingestion & Secret Verification:**
   - Webhook trigger receives Telegram update.
   - `Verify Secret Token` verifies `X-Telegram-Bot-Api-Secret-Token` (ADR-016).
2. **Immediate Callback Acknowledgment (Instant Reviewer Feedback):**
   - Node `Telegram Answer Callback` fires immediately: Telegram displays `✅ Approved — Dispatching email...` or `❌ Rejected — Suppressing email`.
   - **Zero SMTP blocking:** Telegram UI unblocks in <100ms.
3. **Atomic State Transition:**
   - Calls `POST /api/v1/triage/approve`:
     - If `action === 'APPROVE'`: transitions `approval_status = 'APPROVED'`, `reply_status = 'NOT_SENT'` (rowcount = 1).
     - If `action === 'REJECT'`: transitions `approval_status = 'REJECTED'`, `reply_status = 'SUPPRESSED'`, `escalation_needed = 1`.
4. **Conditional Branch (`Is Approved?`):**
   - **If REJECT:** Edit Telegram card to `[❌ REJECTED by Reviewer: Suppressed]` and finish.
   - **If APPROVE:**
     - **SMTP Send Node:** Sends email to customer (`To: customer_email`, `Subject: Re: <subject>`, `Body: suggested_reply`).
     - **Sidecar Mark Sent Node:** Calls `POST /api/v1/triage/mark-sent` (or `POST /api/v1/triage/approve` with `reply_status = 'SENT'`).
     - **Telegram Edit Card:** Edits card to `[✅ APPROVED & SENT by Reviewer: Delivered at <time>]`.

---

## 4. Mail Protocol & Technical Prerequisites

### Required from User Before Building:
To run live end-to-end tests with real email transmission, we need email credentials in `/docker/.env`:
1. **IMAP Configuration (for Ingestion):**
   - `EMAIL_IMAP_HOST` (e.g. `imap.gmail.com`)
   - `EMAIL_IMAP_PORT` (e.g. `993`)
   - `EMAIL_USER` (e.g. `your-test-account@gmail.com`)
   - `EMAIL_PASSWORD` (App Password generated from Google Account Security)
2. **SMTP Configuration (for Dispatch):**
   - `EMAIL_SMTP_HOST` (e.g. `smtp.gmail.com`)
   - `EMAIL_SMTP_PORT` (e.g. `465` or `587`)
   - `EMAIL_SMTP_SECURE` (`true` for 465 SSL, `false` for 587 STARTTLS)

*Note: For testing before user provides live credentials, a mock email injector script (`scripts/simulate_email_ingress.py`) will be provided to simulate incoming MIME emails directly into the pipeline.*

---

## 5. Verification Plan

1. **Test 1: Guardrail-Passed Low/Medium Email:**
   - Ingest email -> Dedup passes -> Context fetched -> Sub-workflow 01 passes.
   - Verifies Telegram card received with buttons.
   - Click `[✅ Approve & Send]`:
     - Verifies Telegram callback answers immediately (<200ms).
     - Verifies SMTP email received in inbox.
     - Verifies SQLite record has `approval_status = 'APPROVED'` and `reply_status = 'SENT'`.
     - Verifies Telegram card edits to `[✅ APPROVED & SENT]`.
2. **Test 2: Guardrail-Failed Toxic / Hallucinated Email:**
   - Ingest adversarial prompt injection or toxic claim email.
   - Sub-workflow 01 guardrail rejects draft.
   - Verifies **no** Telegram approval card is sent.
   - Verifies SQLite record has `approval_status = 'AUTO_ESCALATED'`, `reply_status = 'SUPPRESSED'`, `escalation_needed = 1`.
3. **Test 3: Duplicate Email Ingestion (Idempotency):**
   - Resend exact same email (same Message-ID/hash).
   - Ingestion halts at Dedup step; no duplicate database record, no duplicate Telegram card.

