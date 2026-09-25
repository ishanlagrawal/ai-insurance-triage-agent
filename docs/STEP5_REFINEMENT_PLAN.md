# Step 5 Refinement & Hardening Plan (ADR-018)

## 1. Overview & Objective
Resolve three verified defects identified in Step 5 implementation and proactively enforce global production standards (static linting, network socket timeouts, SQLite WAL concurrency, email header sanitization, truthful audit sequencing) with zero regression on existing services.

---

## 2. Issues Being Addressed

| # | Component | Severity | Description | Target Resolution |
|---|---|---|---|---|
| 1 | `api/main.py:521` | High | `except HTTPException:` swallowed 400/404 exceptions without re-raising, returning `None` (HTTP 200). | Remove swallowed block; re-raise `HTTPException` cleanly and ensure database connection closes via `finally`. |
| 2 | `api/main.py:446` | Medium | Dead endpoint `mark_reply_sent` had incomplete `except` block with no `raise` or `return`. | Remove deprecated dead endpoint entirely since `dispatch-email` solely owns state transition. |
| 3 | `workflows/02` | High | Parallel fan-out stamped Telegram card as `APPROVED & SENT` before SMTP dispatch ran; called dispatch unconditionally on `REJECT`. | Gate dispatch behind `action === 'APPROVE'` IF node; edit Telegram card only after dispatch returns; separate success vs error audit card. |
| 4 | `api/main.py` | Medium | IMAP and SMTP connections lack socket timeouts; unhandled hangs can lock uvicorn worker threads. | Enforce `timeout=15` on `IMAP4_SSL`, `SMTP_SSL`, and `SMTP`. |
| 5 | `api/main.py` | Medium | Outbound email subject lacks CRLF stripping, leaving potential for header injection. | Sanitize subject line with `.replace('\r', ' ').replace('\n', ' ')`. |
| 6 | `db/insurance.db` | Medium | SQLite currently in `delete` journal mode with no connection timeout; prone to concurrency locking. | Set `PRAGMA journal_mode=WAL;` and `sqlite3.connect(..., timeout=30.0)`. |
| 7 | Tooling | Medium | No automated linting tool configured to catch swallowed exceptions or incomplete blocks. | Add `ruff check api/` verification script. |

---

## 3. Impact Assessment & Zero-Collision Guarantees

1. **FastAPI Sidecar (`api/main.py`)**:
   - Signature of `/api/v1/triage/dispatch-email` unchanged (`{ "message_id": ... }`).
   - Port binding remains strictly `127.0.0.1:8008`.
   - Sidecar docker container rebuilt in-place without touching external dependencies.
2. **Database Schema (`db/insurance.db`)**:
   - Zero schema changes. All status values (`APPROVED`, `REJECTED`, `SENT`, `NOT_SENT`, `SUPPRESSED`) remain 100% compliant with schema CHECK constraints.
   - WAL mode allows concurrent readers during IMAP polling and SMTP dispatch without locking.
3. **n8n Workflows**:
   - Workflow 01 (Classify & Guardrail), Workflow 03 (SLA Cron), and Workflow 04 (Ingestion Orchestrator) untouched.

### Rollback Strategy
All target files backed up:
- `/docker/insurance-triage-agent/api/main.py.bak`
- `/docker/insurance-triage-agent/workflows/02_subworkflow_telegram_approval.json.bak`
- `/docker/insurance-triage-agent/db/insurance.db.bak`

Instant rollback command if needed:
```bash
cp /docker/insurance-triage-agent/api/main.py.bak /docker/insurance-triage-agent/api/main.py
cp /docker/insurance-triage-agent/workflows/02_subworkflow_telegram_approval.json.bak /docker/insurance-triage-agent/workflows/02_subworkflow_telegram_approval.json
cp /docker/insurance-triage-agent/db/insurance.db.bak /docker/insurance-triage-agent/db/insurance.db
docker compose restart
```
   - Workflow 02 updated to add conditional branching on `action === 'APPROVE'` and split post-dispatch card updates. Webhook paths and secret tokens remain identical.

---

## 4. Proposed Implementation Steps

### Phase 1: Sidecar Code Hardening (`api/main.py`)
1. Remove dead endpoint `@app.post("/api/v1/triage/mark-reply-sent")`.
2. Refactor `dispatch_email`:
   - Connection closed cleanly via `try...finally: conn.close()`.
   - Exceptions re-raised properly (`except HTTPException: raise`, `except Exception as e: raise HTTPException(500, ...)`).
   - Sanitize subject: `subject = subject.replace("\r", " ").replace("\n", " ").strip()`.
   - Add `timeout=15` to `smtplib.SMTP_SSL` and `smtplib.SMTP`.
3. In `poll_unread_emails`:
   - Add `timeout=15` to `imaplib.IMAP4_SSL`.
4. In `get_db()`:
   - Add `timeout=30.0`.
5. Enable SQLite WAL mode:
   - Execute `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;` on `insurance.db`.

### Phase 2: Workflow 02 Re-sequencing (`workflows/02_subworkflow_telegram_approval.json`)
1. Keep `Telegram Answer Callback` attached to immediate acknowledgment ("Processing approval..." or "Processing rejection...").
2. Connect `Format Feedback` to an IF node: `action === 'APPROVE'`.
3. **REJECT Branch (False)**:
   - Route directly to `Telegram Edit Card (Rejected)` with stamp `❌ REJECTED by Reviewer... (escalation_needed: 1)`.
   - Zero call to SMTP dispatch.
4. **APPROVE Branch (True)**:
   - Route to `Dispatch Approved Email` (POST `/api/v1/triage/dispatch-email`).
   - Post-dispatch IF node: checks if HTTP request succeeded (`$json.status === 'success'`).
   - If Success: Route to `Telegram Edit Card (Sent)` with stamp `✅ APPROVED & SENT by Reviewer (reply_status: SENT)`.
   - If Error: Route to `Telegram Edit Card (Failed)` with stamp `⚠️ APPROVED but SMTP SEND FAILED (reply_status: NOT_SENT)`.
5. Re-import and publish updated Workflow 02 in n8n.

### Phase 3: Automated Static Analysis
1. Install `ruff` inside Python environment.
2. Run `ruff check api/` to verify zero syntax, style, or exception-swallowing errors.

---

## 5. Verification & Testing Plan

1. **Static Analysis Test**:
   - `ruff check api/` returns 0 errors.
2. **Negative Test (Simulated SMTP Failure)**:
   - Temporarily call `/api/v1/triage/dispatch-email` with non-existent message ID -> verify returns HTTP 404 (not 200).
   - Test approval callback with invalid email config or simulated failure -> verify Telegram card reflects failure banner, and `reply_status` remains `NOT_SENT`.
3. **Positive Test (End-to-End Approval & Dispatch)**:
   - Send live test email to test inbox.
   - Reviewer clicks `[Approve & Send]` in Telegram.
   - Verify:
     - Immediate callback banner displayed.
     - Dispatch executes.
     - Telegram card updates to `✅ APPROVED & SENT` only after dispatch confirmation.
     - Database row has `approval_status = 'APPROVED'` and `reply_status = 'SENT'`.
     - External inbox receives the email reply.
4. **Reject Path Test**:
   - Click `[Reject & Escalate]`.
   - Verify card updates to `❌ REJECTED`, zero SMTP calls made, `escalation_needed = 1`.

---

## 6. Documentation Updates
1. Record ADR-018 in `docs/DECISIONS.md`.
2. Update `docs/SESSION_LOG_2026_09_23.md`.
3. Update `docs/STEP5_WALKTHROUGH.md`.
