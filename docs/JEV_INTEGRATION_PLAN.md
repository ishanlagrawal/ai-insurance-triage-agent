# JEV_INTEGRATION_PLAN.md
**Date:** 2026-09-24
**Status:** APPROVED — Phase 1 only. Phases 2 & 3 are deferred stretch goals.
**ADR Reference:** ADR-021 in `docs/DECISIONS.md`

---

## Objective

Integrate TypeSafe AI's Jev model as a lightweight binary pre-filter gate inside **n8n Workflow 04
(`04_orchestrator_email_ingestion.json`)**, immediately after IMAP fetch and before deduplication.

**Goal:** Prevent non-insurance emails (Google notifications, LinkedIn, OTPs, mailer-daemon bounces,
promotions) from burning Inception Mercury-2.5 quota or polluting the `triage_results` table.

---

## Phases

| Phase | Description | Status |
|---|---|---|
| 1 | Gmail Pre-Filter Gate | **In Scope — This Document** |
| 2 | Priority Escalation Scoring | Deferred |
| 3 | Semantic Guardrail (PDF grounding) | Deferred |

---

## Phase 1: Gmail Pre-Filter Gate

### Prerequisites (MUST complete before implementation)
1. Obtain Jev API key from TypeSafe AI.
2. Confirm API schema (request/response format, auth header, exact endpoint URL).
3. Add to `.env`:
   ```
   JEV_API_KEY=<your_jev_key>
   JEV_API_URL=<jev_endpoint_url>
   ```
4. Confirm pricing / free-tier limits and document in ADR-021.

---

### Rollback Strategy (Defined Before Touching Anything)

| Mechanism | Detail |
|---|---|
| Workflow 04 backup | `04_orchestrator_email_ingestion.json.bak` created before any edit |
| `.env` flag | N/A (Rollback via backup only) |
| n8n node | Jev gate is a new conditional branch; existing path nodes are untouched |
| DB | `processed_emails.status = Skipped-NonInsurance` is additive; no schema change |

---

### Implementation Steps

#### Step 1: Backup Workflow 04
```bash
cp workflows/04_orchestrator_email_ingestion.json \
   workflows/04_orchestrator_email_ingestion.json.bak
```

#### Step 2: Add `.env` Keys
```
JEV_API_KEY=<key>
JEV_API_URL=https://api.typesafe.ai/v1/classify   # verify exact URL first
```

#### Step 3: n8n Workflow 04 Node Changes

Current flow:
```
IMAP Trigger → Dedup Check → Customer Lookup → SubWf01 → ...
```

New flow:
```
IMAP Trigger → [JEV GATE] → is_insurance=no → Mark Skipped → Stop
                           ↓ yes/uncertain
               Dedup Check → Customer Lookup → SubWf01 → ...
```

New nodes:
1. **HTTP Request — "Jev Insurance Gate"**
   - POST to `{{ $env.JEV_API_URL }}`
   - Header: `Authorization: Bearer {{ $env.JEV_API_KEY }}`
   - Body: subject + sender + first 150 chars of body

2. **IF — "Is Insurance Related?"**
   - `true` (no) → Mark Skipped node
   - `false` (yes/uncertain) → existing Dedup Check

3. **Set — "Mark Skipped (Non-Insurance)"**
   - Updates `processed_emails` status = `Skipped-NonInsurance`, halts pipeline

Note: Exact request body schema TBD after confirming Jev API docs.

#### Step 4: Re-import into n8n
```bash
docker cp workflows/04_orchestrator_email_ingestion.json n8n:/tmp/04_orch.json
docker exec n8n n8n import:workflow --input=/tmp/04_orch.json
```

#### Step 5: Restart n8n
```bash
docker compose restart n8n
```

---

### Test Plan (Phase 1)

#### Tier A — Synthetic
| # | From | Subject | Expected Status |
|---|---|---|---|
| A1 | noreply@google.com | "Your August 2026 Business Report" | Skipped-NonInsurance |
| A2 | mailer-daemon@googlemail.com | "Delivery Status Notification" | Skipped-NonInsurance |
| A3 | no-reply@linkedin.com | "You have 3 new connections" | Skipped-NonInsurance |
| A4 | rohit.verma@example.com | "Claim CLM-2026-4401 inquiry" | Processed (passes gate) |
| A5 | unknown.new@example.com | "Car insurance query" | Processed (uncertain → pass) |

#### Tier B — Live
1. Non-insurance email → `Skipped-NonInsurance`, no `triage_results` row.
2. Known customer insurance email → full pipeline, Telegram card appears.
3. Rollback: restore backup and verify non-insurance emails reach LLM as before.

---

### Rollback Steps (If Phase 1 Fails)
1. Restore the backup workflow JSON:
   ```bash
   cp workflows/04_orchestrator_email_ingestion.json.bak \
      workflows/04_orchestrator_email_ingestion.json
   docker cp ... && docker exec n8n n8n import:workflow ...
   ```
4. Document rollback in `DECISIONS.md` as ADR-021 addendum.

---

## Deferred Phases

### Phase 2: Priority Escalation Scoring
Jev assigns CRITICAL/HIGH/NORMAL/LOW before SubWf01. Telegram card urgency-styled.
Deferred until Phase 1 validated.

### Phase 3: Semantic Guardrail
Jev + PDF grounding verifies LLM draft reply against policy documents.
Requires Jev PDF grounding API confirmation. Deferred.

---

## Change Log
| Date | Change |
|---|---|
| 2026-09-24 | Initial plan. Phase 1 scoped. Phases 2-3 deferred. |
