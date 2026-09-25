# Step 4 Technical Implementation Plan: Telegram Human-Approval Gate

## 1. Executive Summary & Architectural Scope
Step 4 introduces an asynchronous human-in-the-loop (HITL) approval gate for AI-generated insurance triage replies. When the classification and guardrail sub-workflow produces a `PASSED` result and `escalation_needed == 0`, the system must pause automated dispatch and route the draft response to a human supervisor via Telegram before sending the email to the customer.

---

## 2. Dedicated Telegram Bot & Credential Strategy

### Bot Token Isolation
- **Credential Variable:** `TELEGRAM_BOT_TOKEN_INSURANCE_TRIAGE`
- **Target Chat:** `TELEGRAM_CHAT_ID`
- **Architecture Rule:** Dedicated bot token strictly required.
- **Why NOT share `TELEGRAM_BOT_TOKEN_n8n_APPROVAL`:**
  1. **Telegram Webhook Exclusivity:** The Telegram Bot API allows exactly **one** registered webhook URL per bot token. The existing `TELEGRAM_BOT_TOKEN_n8n_APPROVAL` is already bound to the `LaunchWithAI - Approval Handler` workflow. Reusing it would overwrite that webhook and break existing production agency automation.
  2. **Audit Isolation:** Dedicated bot ensures all audit logs, notifications, and interaction histories remain clean and isolated to the insurance triage portfolio project.

---

## 3. Approval Message Context Specification

The Telegram notification card will be formatted in clean Telegram Markdown/HTML, providing full context so reviewers never have to open the n8n UI.

### Message Template Structure
```
🛡️ INSURANCE TRIAGE APPROVAL REQUEST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👤 Customer:     {{ customer_name }} ({{ customer_email }})
🆔 Identifier:   {{ customer_id || 'UNIDENTIFIED SENDER' }}
📋 Category:     {{ category }} | {{ intent }}
⚡ Priority:     {{ priority }} (Urgency Score: {{ urgency_score }}/5)
🏷️ Entities:     Policy: {{ policy_number || 'None' }} | Claim: {{ claim_number || 'None' }}
🔒 Guardrail:    ✅ PASSED (Zero ungrounded entities detected)
{{ truncation_notice }}

📝 SUGGESTED EMAIL REPLY:
─────────────────────────────
"{{ suggested_reply }}"
─────────────────────────────
Ref ID: {{ message_id }}
```

### Context Field Rules
1. **Sender Identification:** If `customer_context.identified == false`, prominently displays:
   `👤 Customer: ⚠️ UNIDENTIFIED SENDER (email@domain.com)`
2. **Entity Grounding:** Displays matched `policy_number` and `claim_number`.
3. **Guardrail Audit:** Explicitly displays `✅ PASSED` to assure the human reviewer that deterministic grounding passed.
4. **Truncation Flag:** If `was_truncated == true`:
   `⚠️ EMAIL BODY TRUNCATED: Original message was {{ original_length }} chars (truncated to 8,000 for safety).`
   If `was_truncated == false`, this field is omitted.
5. **Full Suggested Reply:** The complete proposed text is displayed in a distinct block.

---

## 4. Approve/Reject Button Flow & Multi-Message Correlation

### Telegram Inline Keyboard
The message is sent via Telegram Bot API `sendMessage` with an `inline_keyboard`:
```json
{
  "inline_keyboard": [
    [
      { "text": "✅ Approve & Send", "callback_data": "APP:{{ message_id }}" },
      { "text": "❌ Reject & Escalate", "callback_data": "REJ:{{ message_id }}" }
    ]
  ]
}
```

### Deterministic Correlation Mechanism
- Telegram restricts `callback_data` to **64 bytes**.
- Format: `APP:<message_id>` (e.g. `APP:msg-9a8b7c` = 14 bytes) and `REJ:<message_id>` (14 bytes).
- **Concurrency & Out-of-Order Handling:**
  - If 50 emails arrive simultaneously, each Telegram card contains its own immutable `message_id`.
  - Reviewers can approve or reject emails in any order. No head-of-line blocking or race conditions exist.
  - The webhook handler queries the database record by `message_id` directly.

### Reviewer Feedback & Card Update
When a button is tapped:
1. `answerCallbackQuery`: Telegram displays an instant banner:
   - Approved: *"✅ Approved. Email queued for dispatch."*
   - Rejected: *"❌ Rejected. Ticket escalated to human desk."*
2. `editMessageText`: The Telegram message is immediately updated in-place:
   - Removes the inline buttons (prevents double-clicking/replay attacks).
   - Appends audit stamp: `[Status: ✅ APPROVED by Reviewer at 2026-09-23 10:45 UTC]` or `[Status: ❌ REJECTED - Escalated]`.

---

## 5. Status & State Mapping Table

| Event | `approval_status` | `reply_status` | `escalation_needed` | Action Taken |
| :--- | :--- | :--- | :--- | :--- |
| **Email Ingested & Classified** | `PENDING` | `NOT_SENT` | `0` | Card sent to Telegram; awaiting human review |
| **Reviewer Clicks [Approve]** | `APPROVED` | `NOT_SENT` | `0` | Approved & ready for dispatch (Step 5 SMTP node owns `SENT` transition upon delivery) |
| **Reviewer Clicks [Reject]** | `REJECTED` | `SUPPRESSED` | `1` | Reply suppressed; assigned to human desk |
| **Guardrail Rejection (Step 3)** | `NOT_REQUIRED` | `SUPPRESSED` | `1` | Never reaches Telegram; straight to human desk |
| **Reviewer Timeout (4-Hr SLA)** | `AUTO_ESCALATED` | `SUPPRESSED` | `1` | SLA expired; auto-escalated to human queue |

> [!NOTE]
> **Dispatch Ownership Boundary:** Step 4 only transitions `approval_status` to `'APPROVED'` while keeping `reply_status = 'NOT_SENT'`. The subsequent Step 5 SMTP dispatch node is the sole owner of the transition to `'SENT'` upon verified delivery.

---

## 6. Reviewer Inaction & Expiry: Option A Selected (4-Hour SLA Auto-Escalation)

### Architecture Decision: Standalone Cron Workflow (Zero Wait-Node State Fragility)
Instead of relying on an in-flight n8n `Wait` node (which loses state or fails to resume if n8n restarts or redeploys during the 4-hour window), SLA tracking is implemented as a **fully decoupled, stateless polling cron**:

1. **Dedicated Workflow File:** `workflows/03_cron_sla_escalation.json`
   - **Trigger:** n8n Schedule / Cron Trigger running every 15 minutes (`*/15 * * * *`).
   - **Action 1:** Invokes sidecar endpoint `GET /api/v1/triage/pending-expired?hours=4`.
   - **Action 2 (If expired records found):** Iterates over records:
     - Calls sidecar endpoint `POST /api/v1/triage/approve` with `action: "AUTO_ESCALATE"`.
     - Updates record: `approval_status = 'AUTO_ESCALATED'`, `reply_status = 'SUPPRESSED'`, `escalation_needed = 1`.
     - Calls Telegram Bot API `editMessageText` (removing inline keyboard and appending `[⚠️ AUTO-ESCALATED: 4-Hour SLA Expired]`).
2. **Sidecar Endpoint:** `GET /api/v1/triage/pending-expired`
   - Accepts query parameter `hours` (default `4`).
   - Query:
     ```sql
     SELECT id, message_id, subject, customer_id, created_at, telegram_message_id, telegram_chat_id
     FROM triage_results
     WHERE approval_status = 'PENDING'
       AND created_at <= datetime('now', '-' || ? || ' hours');
     ```
   - Eliminates direct SQLite database file locking or querying from n8n nodes.

---

## 7. Endpoint Idempotency Specification (`POST /api/v1/triage/approve`)

### Telegram Webhook Retry Protection
Telegram automatically retries webhook deliveries when an upstream endpoint responds slowly (>5 seconds) or returns temporary network errors. To prevent duplicate executions, state corruption, or double-sending emails:

1. **Pre-Condition Read (Telemetry Only):**
   - Query target row:
     `SELECT id, approval_status, reply_status FROM triage_results WHERE message_id = ?;`
2. **Idempotency Guard (Early Exit):**
   - If `approval_status != 'PENDING'`:
     - **NO-OP:** Do not re-update the record, do not re-dispatch email, and do not create duplicate support tickets.
     - Return HTTP 200 with payload:
       ```json
       {
         "status": "noop",
         "message": "Action ignored; record is already in terminal state.",
         "message_id": "...",
         "current_approval_status": "APPROVED",
         "current_reply_status": "NOT_SENT"
       }
       ```
3. **Atomic State Transition (Concurrency Guard):**
   - If `approval_status == 'PENDING'`, perform atomic update within an exclusive transaction:
     ```sql
     UPDATE triage_results
     SET approval_status = ?, reply_status = ?, escalation_needed = ?, updated_at = CURRENT_TIMESTAMP
     WHERE message_id = ? AND approval_status = 'PENDING';
     ```
   - Only trigger downstream email dispatch if exactly 1 row was updated (`cursor.rowcount == 1`).

> [!IMPORTANT]
> **Race-Condition Protection Mechanism:** True concurrency and race protection is guaranteed by the atomic SQL filter `WHERE message_id = ? AND approval_status = 'PENDING'` coupled with checking `cursor.rowcount == 1`. The initial SELECT is non-locking and used purely to populate diagnostic data in the no-op response. Future refactoring must never rely on the SELECT alone for concurrency control.


---

## 8. Technical Implementation Steps

1. **Sidecar API Extension (`api/main.py`):**
   - Add `GET /api/v1/triage/pending-expired?hours=4` for cron poller.
   - Add `POST /api/v1/triage/approve` with strict idempotency check against non-`PENDING` records.
   - Extend `triage_results` table schema / queries to optionally store `telegram_message_id` and `telegram_chat_id` for in-place card editing.
2. **Workflows Created Under `workflows/`:**
   - `workflows/02_subworkflow_telegram_approval.json`: Webhook handler for Telegram button callbacks (`APP:<id>` and `REJ:<id>`).
   - `workflows/03_cron_sla_escalation.json`: Standalone cron workflow running every 15 minutes to auto-escalate expired pending records.
3. **Testing Suite:**
   - **Test Case 1 (Duplicate Callback Idempotency):** Send concurrent/repeated `POST /api/v1/triage/approve` calls for the same `message_id`. Confirm the first transitions state and triggers dispatch, while the second returns `status: noop` with zero duplicate side effects.
   - **Test Case 2 (SLA Expiry Polling):** Insert synthetic pending triage record with timestamp older than 4 hours. Trigger `GET /api/v1/triage/pending-expired`, confirm detection, and verify state transition to `AUTO_ESCALATED`.

