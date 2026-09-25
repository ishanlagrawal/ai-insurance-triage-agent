# Optional Extension: JEV Pre-Filter Gate & Semantic Policy Grounding

**Module Status:** Optional Extension  
**Extension Workflow:** `workflows/extensions/04_orchestrator_email_ingestion_jev.json`  
**ADR References:** [ADR-021](DECISIONS.md#L398), [ADR-022](DECISIONS.md#L415), [ADR-024](DECISIONS.md#L452), [ADR-028](DECISIONS.md#L525)

---

## Overview

The **JEV Extension Module** provides two high-assurance capabilities for enterprise deployment:

1. **Pre-Filter Gate (Phase 1)**: Evaluates incoming emails prior to main LLM ingestion. Filters out non-insurance spam/promotions to minimize primary LLM token consumption.
2. **Semantic Policy Grounding (Phase 3)**: Evaluates generated draft replies using JEV policy grounding model to detect unverified coverage promises, illegal payout claims, or policy contradictions before dispatch.

---

## Architecture Diagram (With JEV Extension)

```
Incoming Email ──► Deduplication Check (SQLite read-only)
                          │ (new email only)
                          ▼
             ┌─────────────────────────┐
             │   JEV Insurance Gate    │ ◄── JEV API (TypeSafe AI)
             │   (is_insurance check)  │
             └────────────┬────────────┘
                          │
            ┌─────────────┴─────────────┐
            ▼                           ▼
      choice: "yes"              choice: "no"
            │                           │
            ▼                           ▼
  Customer DB Context           Mark Skipped ('Ignored')
            │                   (0 LLM tokens spent)
            ▼
  Subworkflow 01 (Classify)
            │
            ▼
  Sidecar Guardrail Verify ──► JEV Semantic Grounding (api/guardrails.py)
            │
            ▼
  Telegram Approval / Auto-Escalate
```

---

## Fail-Open & Fail-Closed Precedence Rules

1. **Pre-Filter Gate (Fail-OPEN)**: If `api.typesafe.ai` is down, rate-limited, or returns an error (`neverError: true`), the gate evaluates to `yes`, allowing the email to proceed to the main LLM triage pipeline rather than dropping customer emails.
2. **Semantic Policy Grounding (Fail-CLOSED)**: If JEV API fails during grounding check in `api/guardrails.py`, the check evaluates to `inconclusive` (`passed: false`), automatically routing the draft to human review per ADR-010 and ADR-011.

---

## Setup & Enabling JEV Extension

1. **Add Credentials to `.env`**:
   ```env
   JEV_API_KEY=your_typesafe_ai_key_here
   ```
2. **Import Extension Workflow**:
   Import `workflows/extensions/04_orchestrator_email_ingestion_jev.json` into n8n to replace the standard orchestrator workflow.
3. **Verify API Endpoints**:
   Ensure `insurance-triage-api` container is running with `JEV_API_KEY` set.

---

## Reverting to Core Workflow (Rollback)

To revert to the dependency-free core pipeline:
1. Re-import `workflows/04_orchestrator_email_ingestion.json` into n8n.
2. The core pipeline will process emails directly via Gemini / Mercury without third-party gate dependencies.
