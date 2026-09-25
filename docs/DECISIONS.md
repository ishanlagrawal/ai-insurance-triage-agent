# Architecture Decisions & Engineering Log

This log tracks architectural decisions, schema refinements, security configurations, and bug fixes for the AI Insurance Inbox Triage Agent project.

---

### Record: ADR-001 — SQLite Schema Constraints & Foreign Key Integrity
- **Date:** 2026-09-23
- **Component:** `db/schema.sql`, `db/seed_data.py`
- **Observation:**
  - Initial draft of `support_tickets` omitted explicit `FOREIGN KEY` constraints on `customer_id`, `policy_number`, and `claim_number`.
  - Enum-like columns (`status`, `priority`, `policy_type`, `claim_type`, `guardrail_status`) accepted arbitrary text without database-level rejection of malformed or misspelled statuses.
- **Decision & Fix:**
  1. Added `FOREIGN KEY` relationships to `support_tickets`:
     - `FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE`
     - `FOREIGN KEY(policy_number) REFERENCES policies(policy_number) ON DELETE SET NULL`
     - `FOREIGN KEY(claim_number) REFERENCES claims(claim_number) ON DELETE SET NULL`
  2. Implemented strict SQLite `CHECK` constraints on:
     - `policies.policy_type` and `policies.status`
     - `claims.status` and `claims.claim_type`
     - `claim_documents.status`
     - `payments.status`
     - `renewals.status`
     - `support_tickets.priority` and `support_tickets.status`
     - `triage_results.priority`, `urgency_score`, `guardrail_status`, `approval_status`, `reply_status`
  3. Kept default `NO ACTION` cascade behavior on financial tables (`claims`, `payments`, `renewals`) to prevent accidental cascade deletion of audit-critical claims data.
- **Validation:**
  - Re-executed `seed_data.py`. Confirmed 100% row insertion without constraint violations.

---

### Record: ADR-002 — Network Isolation & Port Binding Security
- **Date:** 2026-09-23
- **Component:** `docker-compose.yml`, FastAPI service
- **Observation:**
  - The SQLite FastAPI sidecar hosts internal REST endpoints and customer data views.
  - Exposing port 8008 to `0.0.0.0` would make the dashboard and internal API accessible on the public VPS IP without authentication.
- **Decision & Fix:**
  - Explicitly bind container/service to localhost loopback `127.0.0.1:8008`.
  - Public exposure (if needed later) must be routed securely through Cloudflare Tunnel / Access or Traefik with basic auth.
- **Validation:**
  - Verified port 8008 is unused on host; confirmed loopback-only binding in upcoming docker-compose definition.

---

### Record: ADR-003 — Free-Tier LLM Architecture Alignment _(superseded by ADR-019)_
- **Date:** 2026-09-23
- **Component:** n8n HTTP Request node / LLM classifier
- **Observation:**
  - Groq free tier is deprecated/restricted.
  - VPS environment already contains active, valid credentials for `GEMINI_API_KEY` (in n8n allowlist) and `INCEPTION_API_KEY`.
- **Decision:**
  - Primary LLM: Google Gemini Free Tier (`gemini-2.5-flash` / `gemini-1.5-flash`).
  - Secondary/Fallback: Inception API.
  - Zero out-of-pocket LLM operational costs.
- **⚠️ Superseded:** The Gemini free-tier limits documented here (`15 RPM / 1,500 RPD`) were incorrect.
  Empirical testing (Step 6 Tier A) revealed the actual effective limit is **20 requests/day** total.
  See **ADR-019** for the corrected architecture decision and revised $0-cost framing.

---

### Record: ADR-004 — Entity Extraction Regex Hardening in Guardrails
- **Date:** 2026-09-23
- **Component:** `api/guardrails.py`
- **Observation:**
  - Naive regex `\bPOL[-_\w\d]+\b` matched the standard English word `"policy"`, falsely flagging valid replies as referencing an unknown policy named `'POLICY'`.
- **Decision & Fix:**
  - Refined regex patterns to require a hyphen, underscore, or numeric character immediately after the prefix:
    - `POLICY_REGEX = re.compile(r'\bPOL[-_0-9][A-Za-z0-9_-]*\b', re.IGNORECASE)`
    - `CLAIM_REGEX = re.compile(r'\bCLM[-_0-9][A-Za-z0-9_-]*\b', re.IGNORECASE)`
- **Validation:**
  - Valid reply containing the word "policy" and legitimate policy `POL-2026-8810` passed with `passed=True`.
  - Reply with hallucinated `POL-9999-FAKE` correctly failed with `passed=False`.

---

### Record: ADR-005 — Strict Dependency Version Pinning in requirements.txt
- **Date:** 2026-09-23
- **Component:** `requirements.txt`, Docker image
- **Observation:**
  - Initial `requirements.txt` used `>=` range operators, violating deterministic build standards and risking breaking changes on future builds.
- **Decision & Fix:**
  - Froze exact runtime versions via `pip freeze` and pinned all 22 dependencies with `==` operators.
- **Validation:**
  - Rebuilt image via `docker compose up -d --build`. Container started and `/health` returned `status: ok, customers_count: 10`.

---

### Record: ADR-006 — Monetary Amount Hallucination Guardrail Check
- **Date:** 2026-09-23
- **Component:** `api/guardrails.py`
- **Observation:**
  - `validate_suggested_reply()` initially only checked policy numbers (`POL-...`) and claim numbers (`CLM-...`), leaving monetary values vulnerable to hallucination (e.g., claiming approval for ₹85,000 when the actual record is ₹38,000).
- **Decision & Fix:**
  - Added monetary pattern extraction supporting `Rs.`, `Rs`, `₹`, and `INR` prefixes with commas and decimals.
  - Extracted and normalized valid amounts across all financial fields (`claim_amount`, `approved_amount`, `premium_amount`, `renewal_quote`, `payment.amount`).
  - Added strict equality matching (with standard 0.01 floating point currency tolerance).
  - Populated `"amounts_referenced"` into `detected_entities`.
- **Validation:**
  - Valid amount test (`Rs. 38,000`) returned `passed=True`.
  - Hallucinated amount test (`Rs. 85,000`) returned `passed=False` with explicit rejection reason.

---

### Record: ADR-007 — CSV Audit Log Timestamp Column Alignment
- **Date:** 2026-09-23
- **Component:** `api/main.py` (`/api/v1/triage/log`), `triage_results.csv`
- **Observation:**
  - CSV header defined 16 columns including `created_at`, but `writer.writerow()` only output 15 values, causing a 1-column offset in spreadsheet tools.
- **Decision & Fix:**
  - Appended UTC ISO-8601 timestamp (`datetime.now(timezone.utc).isoformat()`) as the 16th element in `writer.writerow()`.
- **Validation:**
  - Tested `/api/v1/triage/log` with message `test-msg-002`. Verified both header and data rows have exactly 16 columns.

---

### Record: ADR-008 — Sub-Workflow Call Order & Fault-Tolerant Guardrail Architecture
- **Date:** 2026-09-23
- **Component:** `workflows/01_subworkflow_classify_guardrail.json`
- **Observation:**
  - Allowing suggested replies to reach human approval or dispatch before deterministic validation creates hallucination vulnerability.
  - LLM API rate limits or malformed responses could crash the parent polling loop if unhandled.
- **Decision:**
  - Enforced mandatory 4-stage linear execution: LLM -> Strict Parser -> Guardrail POST -> IF Branch.
  - Added safe error fallback in Node 2: automatically marks failed LLM calls as `escalation_needed=1` and `passed=False` without halting workflow execution.
  - Used internal Docker network address `http://insurance-triage-api:8008` for zero external exposure.

---

### Record: ADR-009 — Redaction of Gemini API Key via Header Authentication
- **Date:** 2026-09-23
- **Component:** `workflows/01_subworkflow_classify_guardrail.json`, Gemini HTTP node
- **Observation:**
  - Passing `?key=...` in request URLs exposes the raw API key in plaintext within n8n's execution logs and web UI.
- **Decision & Fix:**
  - Migrated authentication from URL query parameter to Google's officially supported `x-goog-api-key` HTTP header.
  - Utilized n8n's `httpHeaderAuth` generic credential type, ensuring keys are masked and redacted in execution logs.
- **Validation:**
  - Executed live API call using `x-goog-api-key`. Verified successful HTTP 200 response with zero credentials in URL string.

---

### Record: ADR-010 — Strict Guardrail Precedence Overriding LLM Escalation
- **Date:** 2026-09-23
- **Component:** `workflows/01_subworkflow_classify_guardrail.json` (Code node)
- **Observation:**
  - If the LLM returns `escalation_needed: 0` but generates a hallucinated reply, relying on the LLM's flag could allow an ungrounded or suppressed response to bypass escalation.
- **Decision & Fix:**
  - Enforced deterministic code node rule:
    `finalEscalationNeeded = (!guardrailPassed) ? 1 : (llm.escalation_needed ? 1 : 0);`
    `finalSuggestedReply = guardrailPassed ? llm.suggested_reply : "";`
  - When guardrail fails (`passed=false`), `escalation_needed` is forced to `1` and draft reply is suppressed.
- **Validation:**
  - Verified with test script `tests/test_step3_logic.py`. Output confirmed `escalation_needed=1` and `suggested_reply=""` despite LLM returning `escalation_needed=0`.

---

### Record: ADR-011 — Intentional Fail-Safe Error Degradation & Sanitization Policy
- **Date:** 2026-09-23
- **Component:** `workflows/01_subworkflow_classify_guardrail.json`, n8n CLI import
- **Observation:**
  - If the LLM node fails, `is_llm_failure=true` forces human review. If the sidecar guardrail call fails or times out, the guardrail output object is undefined. In JavaScript, `undefined === true` evaluates to `false`, causing the precedence check to treat it as failed (`guardrailPassed=false`), forcing `escalation_needed=1` and suppressing draft replies.
  - While this default behavior is favorable, it must be documented as an intentional design constraint so future refactoring does not alter this fail-safe posture.
- **Decision:**
  - Documented explicit reliance on fail-safe default: any missing, undefined, or malformed guardrail verification must strictly evaluate to `guardrail_status: "REJECTED"`, `escalation_needed: 1`, and `suggested_reply: ""`.
  - Workflow imported into n8n via CLI using exact project ID `zB5SIgX0PFh81hSh` and workflow ID `InsTriageSubWf01`.
  - Established rule: Local instance credential ID `YOUR_N8N_GEMINI_CRED_ID` will be stripped back to placeholder `{{GEMINI_HEADER_AUTH_CREDENTIAL_ID}}` in the public GitHub export.
  - Established rule: Live n8n database (`database.sqlite`) is restricted to read-only queries; all mutations must execute through n8n CLI or UI to protect state integrity.

---

### Record: ADR-012 — Input Sanitization, Unicode Evasion Defense, & Observability Persistence
- **Date:** 2026-09-23
- **Component:** `workflows/01_subworkflow_classify_guardrail.json` (`Build Prompt & Payload`, `Parse & Validate LLM JSON`, `Enforce Guardrail Precedence`), `api/guardrails.py`
- **Observation:**
  - Raw email inputs can introduce malicious control characters (`\x00-\x1F`), zero-width characters (`\u200B-\u200D`, `\uFEFF`), and bidi directional overrides (`\u202A-\u202E`, `\u2066-\u2069`).
  - Adversarial injection of zero-width characters (e.g. `"POL-2026-88\u200B10"`) splits domain regex matching (`POL[-_0-9][A-Za-z0-9_-]*`), causing the entity detector to match `POL-2026-88` instead of the full identifier `POL-2026-8810`. If `POL-2026-88` exists in customer records, this evasion allows hallucinated/fake identifiers to slip past hallucination guardrails.
  - Oversized email bodies (>8,000 characters) can exceed LLM context windows or degrade parsing performance.
  - Truncation metadata (`was_truncated`, `original_length`) must not be dropped at node boundaries; it must surface into persistent audit logs (`triage_results.csv`, SQLite `triage_results`, and dashboard UI).
  - Explicit Architecture Boundary: Character sanitization stabilizes parsing, transport, and deterministic regex matchers, but does NOT solve semantic prompt injection.
- **Decision & Fix:**
  - **Sanitizer Placement:** Executes on `email_subject` and `email_body` inside `Build Prompt & Payload` strictly BEFORE interpolation into the Gemini prompt template.
  - **Character Classes:** Strips ASCII control characters `\x00-\x08`, `\x0B-\x0C`, `\x0E-\x1F`, `\x7F`, zero-width characters `\u200B-\u200D`, `\uFEFF`, and bidi overrides `\u202A-\u202E`, `\u2066-\u2069`, while preserving `\t`, `\n`, `\r`.
  - **Whitespace-Boundary Truncation:** Truncates bodies exceeding 8,000 characters at the nearest preceding whitespace boundary (or exact boundary if no whitespace exists within the last 20%), appending `\n[...TRUNCATED: Message exceeded 8,000 characters...]` and raising `was_truncated=true`, `original_length`.
  - **Observability Persistence:** Forwarded through `Parse & Validate LLM JSON` and `Enforce Guardrail Precedence`. Appends `[TRUNCATED from <N> chars]` to `summary` so truncation is logged in SQLite, `triage_results.csv`, and rendered on the dashboard UI.
- **Validation:**
  - **Adversarial Zero-Width Evasion Test:** Evaluated with adversarial string `"Please process refund for policy POL-2026-88\u200B10 immediately."`:
    - *Before Sanitization:* Entity regex matched `['POL-2026-88']` (erroneously passed guardrail as legitimate prefix).
    - *After Sanitization:* `\u200B` stripped, regex matched `['POL-2026-8810']`, and guardrail rejected: `Hallucinated policy number detected: 'POL-2026-8810' does not belong to customer records.`
  - **Truncation Test:** 150-char string with 50-char limit verified clean truncation at whitespace boundary, `was_truncated=true`, `original_length=150`, and summary annotation.

---

### Record: ADR-013 — Fresh State Retrieval on Concurrency Race Fallback (`rowcount == 0`)
- **Date:** 2026-09-23
- **Component:** `api/main.py` (`/api/v1/triage/approve`)
- **Observation:**
  - When two concurrent requests passed the non-blocking initial `SELECT` for a `PENDING` record, the losing request failed the atomic update (`cursor.rowcount == 0`).
  - The fallback handler returned `current_approval_status` from the pre-race snapshot, incorrectly reporting `"PENDING"` in the no-op response even though the winning request had already changed the state.
- **Decision & Fix:**
  - When `cursor.rowcount == 0` is detected, immediately re-query `triage_results` to capture the winning transaction's fresh `approval_status` and `reply_status` before returning the no-op payload.
- **Validation:**
  - Tested with concurrent `ThreadPoolExecutor(max_workers=2)` firing simultaneous `APPROVE` and `REJECT` calls on pending record `test-race-bug1-001`.
  - Output: Winner returned `status: success` (`approval_status: REJECTED`); loser returned `status: noop` with `current_approval_status: REJECTED` (verified not stale `"PENDING"`).

---

### Record: ADR-014 — Entity-Scoped Support Ticket Escalation
- **Date:** 2026-09-23
- **Component:** `api/main.py` (`/api/v1/triage/approve`)
- **Observation:**
  - On triage rejection or auto-escalation, updating `support_tickets` matching solely on `customer_id` caused all open tickets for that customer to escalate to `Critical` priority, corrupting unrelated tickets on other policies.
- **Decision & Fix:**
  - Scoped ticket escalation strictly to the specific entity referenced in the triage record (`policy_number` and/or `claim_number`).
  - If neither `policy_number` nor `claim_number` is present (unidentified sender), support ticket updates are safely bypassed.
- **Validation:**
  - Created two open tickets for `CUST-001`: `TCK-TEST-A` (`POL-2026-8810`, priority Medium) and `TCK-TEST-B` (`POL-2026-9999`, priority Low).
  - Dispatched `REJECT` action for triage record referencing `POL-2026-8810`.
  - Output: `TCK-TEST-A` escalated to `In-Progress` / `Critical`; `TCK-TEST-B` remained untouched at `Open` / `Low`.

---

### Record: ADR-015 — Telegram Human-Approval Gate & Stateless SLA Cron Architecture
- **Date:** 2026-09-23
- **Component:** `workflows/02_subworkflow_telegram_approval.json`, `workflows/03_cron_sla_escalation.json`, `api/main.py`
- **Observation:**
  - In-flight approval waiting inside execution pipelines risks state loss upon process restarts.
  - Sharing Telegram bot tokens between workflows causes webhook registration overwrites.
  - Setting `reply_status = 'SENT'` upon approval prematurely marks emails as delivered before SMTP transmission exists.
- **Decision & Fix:**
  - Isolated Telegram bot using dedicated credential `Telegram Insurance Triage Bot` (`YOUR_N8N_TELEGRAM_CRED_ID`).
  - Implemented decoupled, stateless approval callback sub-workflow (`InsTriageSubWf02`) handling `APP:<id>` and `REJ:<id>`.
  - Implemented standalone 15-minute cron workflow (`InsTriageCronSLA03`) polling `GET /api/v1/triage/pending-expired?hours=4` to enforce 4-hour SLA auto-escalation.
  - Enforced dispatch boundary: reviewer approval transitions `approval_status = 'APPROVED'` and `reply_status = 'NOT_SENT'`. The subsequent Step 5 SMTP node is the sole owner of the transition to `'SENT'`.
  - Added in-place Telegram message editing to strip action buttons and display immutable audit trail stamps.
- **Validation:**
  - Sent live test notification card to Telegram chat.
  - Executed approval action: SQLite record updated to `APPROVED` / `NOT_SENT` (0 errors).
  - Executed in-place message edit: Telegram message updated with `✅ APPROVED by Reviewer` and buttons removed.

---

### Record: ADR-016 — Telegram Webhook Origin Verification via Secret Token Header
- **Date:** 2026-09-23
- **Component:** `workflows/02_subworkflow_telegram_approval.json`, `/docker/.env`, Telegram `setWebhook` API
- **Observation:**
  - The public webhook endpoint `/webhook/insurance-triage-approval-callback` lacked sender authentication, allowing forged `callback_query` payloads to approve or reject triage records without human review.
- **Decision & Fix:**
  - Generated cryptographically secure 256-bit token stored in `.env` as `TELEGRAM_WEBHOOK_SECRET`.
  - Re-registered Telegram webhook passing `secret_token` parameter so Telegram includes `X-Telegram-Bot-Api-Secret-Token` on every request.
  - Configured n8n environment mapping to expose `TELEGRAM_WEBHOOK_SECRET` securely to workflow nodes.
  - Added dedicated Code node (`Verify Secret Token`) immediately following the Webhook Trigger to enforce exact string comparison:
    `$request.headers['x-telegram-bot-api-secret-token'] === $env.TELEGRAM_WEBHOOK_SECRET`.
  - Non-matching or missing tokens immediately halt execution with an empty return (no data downstream, no diagnostic disclosure to potential attackers).
- **Validation:**
  - Empirically verified header visibility in live n8n execution data (`x-telegram-bot-api-secret-token: test-token-12345`).
  - Executed 3 test cases:
    1. Valid header matching secret: Processed through all 6 nodes; record transitioned to `APPROVED`.
    2. Missing header: Execution halted at Verify node; record remained untouched in `PENDING`.
    3. Wrong/tampered header string: Execution halted at Verify node; record remained untouched in `PENDING`.

---

### Record: ADR-017 — Production Email Ingestion, Telegram 64-Byte Callback Limit & Verified SMTP Dispatch
- **Date:** 2026-09-23
- **Component:** `workflows/04_orchestrator_email_ingestion.json`, `workflows/02_subworkflow_telegram_approval.json`, `api/main.py`
- **Observation:**
  - Standard Gmail `Message-ID` headers can exceed 70 characters (e.g. `CAJB2TQh6RkUbrYDzih2yPrgVnyng7y2ayBL3wo_jqGiG+WPGKQ@mail.gmail.com`).
  - Telegram Bot API enforces a hard 64-byte limit on `callback_data`. Setting `callback_data: APP:<long_message_id>` triggers `Bad Request: BUTTON_DATA_INVALID`.
  - In n8n HTTP Request node (`typeVersion: 4.2`), using raw template strings with unescaped newlines/quotes from LLM replies causes `The value in the "JSON Body" field is not valid JSON`.
- **Decision & Fix:**
  - **Compact Callback References:** Sub-workflow and orchestrator use integer `id` from `triage_results` for Telegram buttons (`APP:<id>` and `REJ:<id>`), requiring only 6-8 bytes.
  - **Dual ID Lookup in Sidecar:** Updated `/api/v1/triage/approve`, `/api/v1/triage/dispatch-email`, and `/api/v1/triage/update-telegram-meta` to query `WHERE message_id = ? OR CAST(id AS TEXT) = ?`, ensuring seamless compatibility with both RFC822 Message-IDs and database primary keys.
  - **Robust JSON Body Formatting:** Replaced string interpolations with dedicated Code formatting nodes using `JSON.stringify($json.payload)`.
  - **Native Inline Keyboard:** Configured native n8n Telegram node `replyMarkup: "inlineKeyboard"` structure rather than raw `reply_markup` parameter.
  - **Verified Dispatch Ownership:** Live SMTP transmission strictly owns `reply_status = 'SENT'`. Telegram approval only moves state to `APPROVED` / `NOT_SENT`.
- **Validation:**
  - Ingested live test email from `tester@example.com` with subject `Towing Support Needed for breakdowns`.
  - Dedup verified in `processed_emails` table.
  - LLM successfully classified as Roadside / Critical, verified through guardrails.
  - Telegram bot rendered interactive approval card with buttons.
  - Human review approval executed; SMTP transmission sent real response email to `tester@example.com`.
  - SQLite record `id = 17` transitioned to `approval_status = 'APPROVED'`, `reply_status = 'SENT'`.
  - Telegram card updated in-place with audit confirmation stamp.

---

### Record: ADR-018 — Truthful Dispatch Audit Sequencing, Exception Re-raising & Production Concurrency Hardening
- **Date:** 2026-09-23
- **Component:** `workflows/02_subworkflow_telegram_approval.json`, `api/main.py`, `db/insurance.db`, `scripts/run_lint.sh`
- **Observation:**
  - `dispatch_email` swallowed `HTTPException` (lines 521-525) with `except HTTPException: conn.close()`, returning `None` (HTTP 200) on 400 and 404 client errors.
  - Superseded endpoint `mark_reply_sent` had an incomplete `except` block with no `raise` or `return`.
  - In Workflow 02, parallel fan-out edited Telegram card to `APPROVED & SENT` before the SMTP dispatch node had completed or confirmed success, creating a false audit trail if SMTP failed.
  - Workflow 02 fired the SMTP dispatch node unconditionally for both `APPROVE` and `REJECT` actions.
  - Socket connections in `smtplib.SMTP_SSL` and `imaplib.IMAP4_SSL` lacked explicit socket timeouts, risking worker hangs during network freezes.
  - SQLite database lacked WAL mode, running in `delete` journal mode with no connection timeout in `get_db()`.
- **Decision & Fix:**
  - **Exception Re-raising & Cleanup:** Refactored `dispatch_email` to use `try...finally: conn.close()` and cleanly re-raise `HTTPException` (404 on not found, 400 on not approved).
  - **Dead Code Removal:** Removed deprecated `mark_reply_sent` endpoint entirely.
  - **Truthful Audit Trail Sequencing:** Rewired Workflow 02:
    - Reviewer receives immediate popup acknowledgment via `answerCallbackQuery` ("Processing approval...").
    - Gated dispatch behind an explicit IF node (`action === 'APPROVE'`).
    - `REJECT` branch updates Telegram card to `❌ REJECTED` and halts with zero SMTP calls.
    - `APPROVE` branch calls `Dispatch Approved Email`. Only upon confirmed `status === 'success'` from SMTP does the card edit to `✅ APPROVED & SENT`.
    - If SMTP transmission fails, card edits to `⚠️ APPROVED by Reviewer ... Status: SMTP DISPATCH FAILED (reply_status: NOT_SENT)`.
  - **Network Timeouts & CRLF Sanitization:** Enforced `timeout=15` on `IMAP4_SSL`, `SMTP_SSL`, and `SMTP`. Sanitized outbound email subjects with `.replace('\r', ' ').replace('\n', ' ')`.
  - **SQLite WAL Concurrency:** Enabled `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;` on `insurance.db` and added `timeout=30.0` to `sqlite3.connect()`.
  - **WAL Sidecar & Backup Note:** In WAL mode, backing up `insurance.db` requires executing `PRAGMA wal_checkpoint(TRUNCATE);` prior to file copy or copying `insurance.db-wal` and `insurance.db-shm` alongside `insurance.db` to prevent snapshot inconsistency.
  - **Automated Linting:** Added `scripts/run_lint.sh` running `ruff check api/`.
- **Validation:**
  - Automated lint verification: `ruff check api/` executed.
  - HTTP 404 test: `POST /api/v1/triage/dispatch-email` with non-existent message ID returned HTTP 404 `{"detail": "Triage record not found"}`.
  - HTTP 400 test: `POST /api/v1/triage/dispatch-email` on `PENDING` record returned HTTP 400 `{"detail": "Cannot dispatch email with approval_status=PENDING"}`.
  - Negative SMTP test: Dispatched with malformed recipient; returned HTTP 500 `SMTP dispatch failed`. Verified database row preserved `approval_status = 'APPROVED'` and `reply_status = 'NOT_SENT'` (prevented false SENT transition).
  - Workflow active: `InsTriageSubWf02` re-imported and published in n8n.
---

### Record: ADR-019 — Corrected Gemini Free-Tier Limits & Inception Mercury-2.5 as De Facto Primary LLM
- **Date:** 2026-09-24
- **Component:** n8n HTTP Request node / LLM classifier, Step 6 Tier A test runner
- **Supersedes:** ADR-003 (partially)
- **Observation:**
  - During Step 6 Tier A (32 synthetic cases), all 32 Gemini API calls were issued in a single run.
    After 20 calls, all subsequent calls returned:
    `GenerateRequestsPerDayPerProjectPerModel-FreeTier` quota error — every response became a hard
    fail-safe fallback (Grievance Team escalation, empty reply), not a legitimate LLM classification.
  - The Gemini free tier documentation cited in ADR-003 stated `1,500 RPD`; the empirically observed
    limit is **20 requests/day** for `gemini-2.5-flash` under the `FreeTier` quota class.
    This is a discrepancy of 75x and renders Gemini effectively unusable as a primary LLM for any
    real email volume or automated test suite of non-trivial size.
  - Inception Mercury-2.5 (via `INCEPTION_API_KEY`) completed the entire 32-case suite with:
    - Zero rate-limit errors
    - 4.10s average latency (min 2.41s, max 12.47s)
    - 96.9% pass rate (31/32; the one failure was a test data error, not a model error)
- **Decision:**
  - **De facto primary LLM:** Inception Mercury-2.5. This is now the load-bearing provider for
    automated test suites and production triage volume.
  - **Gemini role revised:** Google Gemini free tier is retained as a low-volume fallback / manual
    verification tool only. It must NOT be relied upon for any batch operation >20 calls/day or for
    automated suites.
  - **$0-cost framing update:** The "Zero out-of-pocket LLM operational costs" claim from ADR-003
    remains valid under the following terms:
    - Inception Mercury-2.5 free tier provides **1,000 RPM** and **100 million free tokens** per new
      account (verified via inceptionlabs.ai, September 2026).
    - At the observed token consumption rate (~500 tokens/call average), 100M tokens supports
      approximately **200,000 triage calls** before any cost is incurred.
    - This is sufficient to classify as a $0-cost architecture for portfolio/demo purposes and
      reasonable production volume.
    - If Inception tokens are exhausted, pay-as-you-go pricing is $0.20/1M input + $0.75/1M output
      tokens — well below enterprise LLM costs.
  - The portfolio's $0-cost architecture claim should be re-stated as:
    _"Zero out-of-pocket LLM costs using Inception Mercury-2.5 free tier (100M free tokens; 1,000 RPM;
    no daily request cap), with Google Gemini retained as a low-volume secondary option."_
- **Validation:**
  - Step 6 Tier A: 32 consecutive calls to Inception Mercury-2.5 with zero quota failures.
  - Step 6 Tier A: Gemini quota exhausted at call #21 (confirmed via error message content).
  - Inception free tier limits cross-referenced against inceptionlabs.ai documentation (September 2026).

---

### Record: ADR-020 — n8n Subworkflow 01 Primary LLM Migration to Inception Mercury-2.5 & Rollback Safety
- **Date:** 2026-09-24
- **Component:** `workflows/01_subworkflow_classify_guardrail.json`, `workflows/01_subworkflow_classify_guardrail.json.bak`, n8n container
- **Observation:**
  - Background schedule trigger of n8n Orchestrator (`InsTriageOrch04` -> `InsTriageSubWf01`) polls unread emails every 60 seconds.
  - `InsTriageSubWf01` previously targeted Google Gemini 2.5 Flash (`generativelanguage.googleapis.com`), which returned HTTP 429 quota exhaustion (20 req/day limit discovered in ADR-019).
  - The fail-safe circuit breaker in Node 2 cleanly caught the HTTP 429 error and set `is_llm_failure: true`, defaulting to human review (`LLM inference failed.`, `suggested_reply: ""`, `approval_status = 'AUTO_ESCALATED'`). Zero ungrounded text leaked to dispatch.
- **Decision & Fix:**
  - **n8n Workflow Update:** Updated `workflows/01_subworkflow_classify_guardrail.json` to target Inception Mercury-2.5 (`https://api.inceptionlabs.ai/v1/chat/completions`) using `$env.INCEPTION_API_KEY` and OpenAI-compatible JSON schema format.
  - **Preserved Rollback Backup:** Created `workflows/01_subworkflow_classify_guardrail.json.bak` containing original Gemini-based subworkflow for 1-click instant rollback.
  - **n8n Container Import:** Transferred and imported workflow into n8n container via `docker cp` and `n8n import:workflow`.
- **Validation:**
  - Direct API probe against Inception Mercury-2.5 returned HTTP 200 OK with valid JSON.
  - Step 6 Tier B Case 1 executed successfully (`ROADSIDE_ASSISTANCE`, `PASSED`, `APPROVED`, `SENT`).



---

### Record: ADR-021 — Jev Pre-Filter Gate Integration (Discovery & Plan)
- **Date:** 2026-09-24
- **Component:** `workflows/04_orchestrator_email_ingestion.json`, `docs/JEV_INTEGRATION_PLAN.md`
- **Status:** APPROVED — Implementation pending Jev API access (Phase 1 only)
- **Observation:**
  - `processed_emails` table confirmed non-insurance emails reaching full LLM pipeline:
    - `businessprofile-noreply@google.com` → "Nandigram Mevasa, your performance report for August 2026" → full Inception Mercury-2.5 call consumed.
    - `mailer-daemon@googlemail.com` → "Delivery Status Notification (Failure)" → full Inception Mercury-2.5 call consumed.
  - Test Gmail inbox receives all kinds of email (Google Maps, LinkedIn, OTPs, promotions, delivery alerts). Every one burns a quota-limited LLM call and writes a junk row into `triage_results`.
  - User identified the need: pre-filter insurance-relevant emails before passing to the main pipeline.
- **Decision:**
  - Integrate TypeSafe AI's Jev model as a lightweight pre-filter gate inside Workflow 04, immediately after IMAP fetch and before deduplication/customer lookup.
  - **Phase 1 (Gmail Pre-Filter Gate):** Single Jev HTTP call with subject + sender domain + first 100 chars → binary `IS_INSURANCE_RELATED: yes | no | uncertain`. Only `no` hard-drops (marked `Skipped-NonInsurance`); `uncertain` and `yes` proceed to full pipeline.
  - **Phase 2 (Priority Scoring):** Future — same or extended Jev call assigns `CRITICAL/HIGH/NORMAL/LOW`.
  - **Phase 3 (Semantic Guardrail):** Future — Jev with PDF document grounding to catch paraphrased hallucinations.
  - **Rollback Strategy:**
    - All changes additive; existing pipeline nodes remain intact (not deleted).
    - Backup of Workflow 04 JSON created as `workflows/04_orchestrator_email_ingestion.json.bak` before any edit. (Note: Restoring this backup is the only supported rollback method; `.env` toggles are not implemented).
  - **Prerequisite Blockers:**
    - Jev API key / access must be obtained from TypeSafe AI.
    - API endpoint schema and pricing must be confirmed before implementation.
  - Full implementation plan in `docs/JEV_INTEGRATION_PLAN.md`.
- **Validation (Planned):**
  - Phase 1 Tier A: 5 synthetic non-insurance emails → `Skipped-NonInsurance` in `processed_emails`.
  - Phase 1 Tier B: 3 real customer emails pass through gate and complete full pipeline unchanged.
  - Rollback: Restore `.bak` file and confirm all emails reach LLM as before.

---

### Record: ADR-022 — Jev Deduplication Token Optimization
- **Date:** 2026-09-24
- **Component:** `workflows/04_orchestrator_email_ingestion.json`, `api/main.py`, `docs/JEV_DEDUP_OPTIMIZATION_PLAN.md`
- **Status:** COMPLETED & VERIFIED
- **Observation:**
  - Non-insurance emails are kept UNREAD in Gmail inbox by design so user's inbox isn't modified unnecessarily.
  - On every 60-second IMAP poll cycle, `UNSEEN` query re-fetches unread non-insurance emails.
  - Because Jev Gate was placed *before* SQLite deduplication lookup, Jev evaluated the same unread non-insurance email repeatedly on every poll, wasting LLM tokens before `Mark Skipped` returned `already_recorded`.
- **Decision & Proposed Fix:**
  - Move SQLite Deduplication Check **BEFORE** Jev Gate in n8n Workflow 04.
  - Add read-only `POST /api/v1/dedup/check` endpoint in `api/main.py` to query `processed_emails` table without writing.
  - If email `message_id` already exists in `processed_emails` (with status `Ignored` or `Processed`), workflow stops immediately at `Is Not Duplicate?` node.
  - Jev Gate is invoked **exactly once** per new unread email (0 repeat tokens on subsequent 60s polls).
- **Files Involved:**
  - `api/main.py`
  - `workflows/04_orchestrator_email_ingestion.json`
  - `docs/JEV_DEDUP_OPTIMIZATION_PLAN.md`
- **Rollback Strategy:**
  - Workflow backup in `workflows/04_orchestrator_email_ingestion.json.bak`.
  - Revert node order by restoring the backup.

---

### Record: ADR-023 — Strict JEV Binary Filtering & Live Verification
- **Date:** 2026-09-24
- **Component:** `workflows/04_orchestrator_email_ingestion.json`, `docs/DECISIONS.md`
- **Status:** COMPLETED & VERIFIED
- **Observation:**
  - Ambiguous / generic test emails (e.g. `Test5` with subject "Test5" and body "Test5") returned `uncertain` choice from JEV.
  - Previous n8n IF condition checked `choice != 'no'`. Thus, `uncertain` emails slipped into the main LLM pipeline, generating draft fallback replies and triggering unwanted Telegram cards.
- **Decision & Fix:**
  1. Refined JEV Gate prompt instructions: explicitly instruct JEV to choose `no` for generic test text, spam, or non-insurance.
  2. Changed n8n IF condition (`Is Insurance Email? (Jev)`) from `choice != 'no'` to strict `choice == 'yes'`.
  3. `no` and `uncertain` choices now route directly to `Mark Skipped (Non-Insurance)` (`POST /api/v1/triage/skip-email`).
- **Validation:**
  - Live inbox evaluation of `Test6` (`subject: Test6`, `body: Twt`): JEV evaluated with `choice: "no"` (confidence `1.0`).
  - Pipeline routed `Test6` to `skip-email`, logging status `Ignored` in `processed_emails`.
  - Email remained **UNREAD** in Gmail; **0 Telegram alerts** sent.
  - Subsequent 60s poll cycles blocked `Test6` at Dedup Check node (**0 repeat JEV tokens spent**).

---

### Record: ADR-024 — Phase 2 JEV Priority Scoring & Phase 3 Semantic Policy Grounding
- **Date:** 2026-09-24
- **Component:** `workflows/04_orchestrator_email_ingestion.json`, `api/guardrails.py`, `api/main.py`, `docs/PHASE_2_3_JEV_ADVANCED_PLAN.md`
- **Status:** COMPLETED & VERIFIED
- **Observation:**
  - Need pre-classification of email urgency prior to subworkflow execution to optimize token budgets and desk routing.
  - Need semantic validation of LLM-generated reply text against SQLite customer context to catch policy contradictions before dispatch.
- **Decision & Implementation:**
  1. **Phase 2 (Priority & Urgency Scoring):**
     - Expanded JEV Gate payload in `04_orchestrator_email_ingestion.json` to query `urgency_rating` (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`).
     - Mapped rating to numeric `urgency_score` (5, 4, 3, 1) in `Prepare Subworkflow Inputs` node and forwarded to subworkflow.
  2. **Phase 3 (Semantic Policy Grounding):**
     - Added `verify_semantic_grounding_with_jev()` in `api/guardrails.py`.
     - Integrated into `/api/v1/guardrails/verify` endpoint in `api/main.py`.
     - Ensures LLM draft replies do not promise unverified coverage or unauthorized payouts.
- **Validation:**
  - Tested `/api/v1/guardrails/verify` with identified customer context (`amitabh.sen.test@example.com` / `POL-2026-3342`): returned `passed: true`.
  - Tested with ungrounded/contradictory claim: JEV correctly rejected with `passed: false` and `Semantic Grounding Failed`.
  - Re-imported, published, and restarted n8n workflow `InsTriageOrch04` and `insurance-triage-api` container.




---

### Record: ADR-025 — Fixing SMTP Dispatch and Guardrail Email Handling
- **Date:** 2026-09-24
- **Component:** `api/main.py` (Endpoints `/api/v1/triage/approve`, `/api/v1/triage/dispatch-email`), `db/insurance.db`
- **Status:** COMPLETED & VERIFIED
- **Observation:**
  1. Emails from real senders (e.g., `tester@example.com`) mentioning policies not registered in `insurance.db` were correctly rejected by the guardrail (`passed: false`, "Ungrounded entities"), but their handling stopped at logging. They did not trigger Telegram notifications, leading to silent escalations.
  2. Manual approval via Telegram buttons logged a status of `SMTP DISPATCH FAILED` (HTTP 404) because the `insurance-triage-api` container was running older code without the new `/api/v1/triage/approve` and `/api/v1/triage/dispatch-email` endpoints.
- **Decision & Implementation:**
  1. **Database Update:** Added the real sender (`tester@example.com`) and corresponding test policy (`POL-2026-1234`) to the SQLite database to allow testing of the "happy path" (guardrail passing). Cleared the `processed_emails` deduplication record to force re-processing.
  2. **API Container Restart:** Restarted the `insurance-triage-api` Docker container to load the latest `api/main.py` code containing the approval and email dispatch endpoints.
- **Validation:**
  - Invoked the approval workflow; the `/api/v1/triage/approve` and `/api/v1/triage/dispatch-email` endpoints returned HTTP 200 OK.
  - SMTP email was successfully dispatched to `tester@example.com`.
  - Database record `10086` correctly reflected `approval_status: APPROVED` and `reply_status: SENT`.
  - The system works end-to-end for Telegram approval to SMTP dispatch.


---

### Record: ADR-026 — Dashboard Public Exposure
- **Date:** 2026-09-24
- **Component:** `api/main.py`, Docker configuration
- **Status:** COMPLETED & VERIFIED
- **Observation:**
  - Need public access to the dashboard UI for status check.
  - Previous ADR-002 restricted port 8008 to `127.0.0.1`.
- **Decision & Fix:**
  - Exposed port `8008` to the public interface `0.0.0.0:8008`.
  - Accessible via `http://<VPS_IP>:8008/dashboard`.
  - Enforced using the exact path `/dashboard` (not `/cashboard`).

---

### Record: ADR-027 — Telegram Approval Sub-Workflow Bug Fixes
- **Date:** 2026-09-24
- **Component:** `workflows/02_subworkflow_telegram_approval.json`
- **Status:** COMPLETED & VERIFIED
- **Observation:**
  - `02_subworkflow_telegram_approval.json` had multiple logic and state-passing bugs causing SMTP dispatch failures.
- **Decision & Fix:**
  - **Bug 1:** "No item with that key" on first click. The `Sidecar Approve API` node used `$json.sidecar_payload` which didn't exist after `Is Valid Callback?`. Fix: Built payload inline using `{ "message_id": $json.message_id, "action": $json.action, ... }`.
  - **Bug 2:** IF gate required `sidecar_status == 'success'`. Since Bug 1 crashed the first click, `sidecar_status` was never 'success', skipping dispatch. Fix: Changed condition to `action == 'APPROVE' AND current_reply_status != 'SENT'`, ensuring dispatch runs on first click and is idempotent on repeats.
  - **Bug 3:** `current_reply_status` not forwarded by `Format Decision & Context`. Fix: Added `current_reply_status` to the node output to enable the IF condition check.
- **Validation:**
  - Sent fresh insurance email.
  - Telegram card appeared, single click on ✅ fired SMTP reply immediately.


---

### Record: ADR-028 — Full Review & Refinement of JEV Integration (Safety, Fallbacks, & Notes)
- **Date:** 2026-09-24
- **Component:** `workflows/04_orchestrator_email_ingestion.json`, `api/guardrails.py`, `docs/DECISIONS.md`
- **Status:** COMPLETED & VERIFIED
- **Observation:**
  1. **Item 1 (Grounding Fail-Closed):** `verify_semantic_grounding_with_jev()` in `api/guardrails.py` previously caught exceptions and returned `True` (fail-open). This violated ADR-010/011 precedence requiring failed or inconclusive guardrail checks to evaluate to human escalation.
  2. **Item 2 (Urgency Score Fallback Regression):** `jev_urgency_score` defaulted to `3` in `Prepare Subworkflow Inputs` when JEV answers were missing/null. In `Format Pending Payload` (`prepInputs.jev_urgency_score || triageOutput.urgency_score`), this caused `3` to always evaluate as truthy, permanently overriding Gemini LLM classification urgency scores.
  3. **Item 3 (Workflow Notes Accuracy):** `Jev Insurance Gate` node notes in `04_orchestrator_email_ingestion.json` incorrectly claimed runtime control via `JEV_GATE_ENABLED` env var.
  4. **Item 4 (Pre-Filter Gate Fail-Open):** `Is Insurance Email? (Jev)` IF condition `leftValue: "={{ $json.answers.is_insurance.choice }}"` evaluated to `undefined` on JEV API downtime/error (`neverError: true`), causing the IF node to evaluate as `false` and silently drop incoming customer emails as `Ignored`.
- **Decision & Fix:**
  1. **Grounding Fail-Closed:** Updated `api/guardrails.py` exception block to return `False` with rejection reason `"JEV Grounding inconclusive (API error: ...). Routed to human review per ADR-011."`
  2. **Urgency Fallback Fix:** Updated `Prepare Subworkflow Inputs` in `04_orchestrator_email_ingestion.json` to return `null` for `jev_priority` and `jev_urgency_score` when JEV answers are absent. This allows `prepInputs.jev_urgency_score || triageOutput.urgency_score || 1` to fall back to the main LLM's urgency score when JEV is unavailable.
  3. **Node Notes Update:** Updated `Jev Insurance Gate` node notes in `04_orchestrator_email_ingestion.json` to state: *"Hard-wired node in workflow. Rollback: restore 04_orchestrator_email_ingestion.json.bak or remove node."*
  4. **Pre-Filter Gate Fail-Open:** Updated `Is Insurance Email? (Jev)` IF node condition in `04_orchestrator_email_ingestion.json` to `leftValue: "={{ $json.error || !$json.answers ? 'yes' : ($json.answers.is_insurance?.choice || 'no') }}"`. On JEV API failure, condition evaluates to `'yes'`, passing the email through to main LLM triage and human review per ADR-008.
- **Validation:**
  - Grounding exception handling verified in `api/guardrails.py`.
  - Workflow JSON validated; JEV gate failure fallback verified against null/error responses.


