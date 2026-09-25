# JEV_DEDUP_OPTIMIZATION_PLAN.md
**Date:** 2026-09-24
**Status:** IMPLEMENTED & VERIFIED
**ADR Reference:** ADR-022

---

## Objective

Optimize n8n Workflow 04 (`04_orchestrator_email_ingestion.json`) and FastAPI (`api/main.py`) by moving the **Deduplication Check BEFORE the Jev Pre-Filter Gate**.

**Goal:** Eliminate repeat Jev API token burn on unread non-insurance emails, while ensuring 100% deduplication coverage for both insurance and non-insurance emails.

---

## Current Problem vs Proposed Flow

### Current Flow (Causes Repeat Token Burn):
```
IMAP Fetch (Unread) ──► Split Emails ──► [JEV GATE (every 60s!)] ──► Is Insurance?
                                                                         ├─ no ──► Mark Skipped (writes 'Ignored' to DB)
                                                                         └─ yes ─► Dedup Check ──► Process
```
*Issue:* Unread non-insurance emails remain UNREAD in Gmail. Every 60s IMAP poll fetches them again and invokes Jev Gate *before* SQLite lookup happens.

### Proposed Flow (0 Repeat Jev Tokens):
```
IMAP Fetch (Unread) ──► Split Emails ──► [DEDUP CHECK (Read-Only)] ──► Is Not Duplicate?
                                                                            ├─ DUPLICATE (yes) ──► STOP (0 Jev tokens)
                                                                            └─ NEW EMAIL (no)  ──► [JEV GATE]
                                                                                                      ├─ non-insurance ──► Mark Skipped ('Ignored')
                                                                                                      └─ insurance     ──► Process & Mark Read ('Processed')
```

---

## Changes Required

### 1. `api/main.py`
Add lightweight read-only dedup endpoint `POST /api/v1/dedup/check`:
```python
@app.post("/api/v1/dedup/check")
def check_email_dedup_only(req: DedupRequest):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT message_id, status FROM processed_emails WHERE message_id = ?;", (req.message_id,))
        existing = cur.fetchone()
        conn.close()
        if existing:
            return {"duplicate": True, "message_id": req.message_id, "status": existing["status"]}
        return {"duplicate": False, "message_id": req.message_id, "status": "New"}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))
```

### 2. `workflows/04_orchestrator_email_ingestion.json`
- Update `Check & Record Dedup` node URL to `/api/v1/dedup/check`.
- Re-route node connections:
  - `Split Emails` → `Check & Record Dedup` → `Is Not Duplicate?`
  - `Is Not Duplicate?` (true branch) → `Jev Insurance Gate`
  - `Jev Insurance Gate` → `Is Insurance Email? (Jev)`
    - `yes` → `Get Customer Context`
    - `no / uncertain` → `Mark Skipped (Non-Insurance)`

---

## Rollback Plan

| Action | Revert Command |
|---|---|
| Restore Workflow 04 | `cp workflows/04_orchestrator_email_ingestion.json.bak workflows/04_orchestrator_email_ingestion.json` |
| Re-import Workflow | `docker cp ... && docker exec n8n n8n import:workflow ...` |
| Fast Reversion | Restore backup file |

---

## Test & Validation Plan

1. **Non-Insurance Email Test:**
   - Send non-insurance email to test Gmail.
   - Poll 1: Jev evaluates email (1 Jev call). Status logged as `Ignored`. Stays UNREAD in Gmail.
   - Poll 2 (60s later): Dedup check catches `Ignored` status in DB. Pipeline stops at `Is Not Duplicate?`. **0 Jev calls**.

2. **Insurance Email Test:**
   - Send insurance claim email.
   - Poll 1: Jev evaluates `yes`. Processed through Subworkflow 01. Telegram card generated. Marked READ in Gmail.
   - Poll 2: IMAP ignores read email. If retried, Dedup check catches `Processed` status in DB. **0 Jev calls**.
