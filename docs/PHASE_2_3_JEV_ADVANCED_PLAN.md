# PHASE 2 & PHASE 3: JEV ADVANCED TRIAGE & GROUNDING PLAN

**Date:** 2026-09-24  
**Status:** DRAFT — AWAITING APPROVAL  
**ADR References:** ADR-021, ADR-022, ADR-023, ADR-024  

---

## Executive Summary

Following the successful implementation and verification of **JEV Pre-Filter Gate (Phase 1)** and **JEV Deduplication Optimization (ADR-022/ADR-023)**, this document outlines the architecture, data flows, implementation steps, and rollback safety for **Phase 2** and **Phase 3**.

* **Phase 2 Goal:** Multi-dimensional JEV pre-classification to score email urgency (1–5) and priority (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`) *before* main LLM subworkflow execution.
* **Phase 3 Goal:** Semantic Guardrail Grounding using JEV + DB Policy Context to verify LLM-suggested replies against policy terms, preventing hallucinations before Telegram approval / SMTP dispatch.

---

## Phase 2: JEV Priority & Urgency Scoring

### 1. Objective
Currently, priority and urgency are determined during the downstream Gemini/Inception LLM subworkflow call. Implementing JEV Priority Scoring at the gate allows:
1. **Pre-Routing:** Direct routing of `CRITICAL` / high-urgency emails to expedited queues.
2. **Quota Optimization:** Setting dynamic token budgets and model fallbacks based on urgency.

### 2. JEV API Request Schema Expansion
Update the JEV API payload in `04_orchestrator_email_ingestion.json`:

```json
{
  "model": "jev-latest",
  "state": "Subject: ...\nFrom: ...\nBody excerpt: ...",
  "questions": {
    "is_insurance": {
      "type": "choice",
      "instructions": "Is this email explicitly related to insurance services such as policy queries, claims, renewals, roadside assistance, quotes, complaints, or fraud? If generic test text, ambiguous spam, or non-insurance, choose no.",
      "criteria": {
        "yes": "The email is explicitly about insurance services",
        "no": "The email is not explicitly about insurance"
      }
    },
    "urgency_rating": {
      "type": "choice",
      "instructions": "Rate the urgency of this insurance request based on customer impact (roadside breakdown, active accident, urgent claim, vs standard inquiry).",
      "criteria": {
        "CRITICAL": "Immediate emergency (vehicle stalled on highway, accident, towing request)",
        "HIGH": "Time-sensitive issue (policy renewal expiring today, claim payment dispute)",
        "MEDIUM": "Standard operational query (claim status update, document request)",
        "LOW": "General inquiry, policy quote request, non-urgent feedback"
      }
    }
  }
}
```

### 3. Workflow Data Mapping
* JEV returns `answers.urgency_rating.choice` (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`) and confidence score.
* Map urgency rating to numeric score:
  - `CRITICAL` → Urgency Score = 5
  - `HIGH` → Urgency Score = 4
  - `MEDIUM` → Urgency Score = 3
  - `LOW` → Urgency Score = 1
* Forward `jev_urgency` and `jev_priority` in subworkflow input context (`Execute Classify & Guardrail SubWf`).

---

## Phase 3: Semantic Guardrail & Policy Grounding

### 1. Objective
In addition to regex entity validation (`api/guardrails.py`), Phase 3 introduces **Semantic Policy Grounding**.
Before a suggested draft reply is sent to Telegram for human review or auto-dispatched, JEV evaluates whether the draft reply makes promises, coverage statements, or monetary approvals that contradict or exceed the customer's actual policy database context.

### 2. Grounding Flow Architecture

```
[LLM Draft Generated] ──► [Format Suggested Reply]
                                   │
                                   ▼
                      [JEV SEMANTIC GROUNDING GATE]
                      Input: 
                        - Customer Policy Coverage & Limits (SQLite)
                        - Claim History & Active Documents
                        - Generated Draft Reply
                                   │
                                   ├──► Grounded? (YES) ──► Telegram Approval Card (PASSED)
                                   └──► Contradiction/Hallucination (NO) 
                                           │
                                           ▼
                                  Set status 'AUTO_ESCALATED'
                                  Reason: "Grounding Failed: Exceeds policy terms"
                                  Telegram Alert with ⚠️ Warning Badge
```

### 3. JEV Semantic Grounding Prompt Schema

```json
{
  "model": "jev-latest",
  "state": "Customer Policy Coverage: {{ $json.customer_context.policies }}\nClaims: {{ $json.customer_context.claims }}\nSuggested Reply: {{ $json.suggested_reply }}",
  "questions": {
    "is_grounded": {
      "type": "choice",
      "instructions": "Does the suggested reply accurately reflect the customer's policy coverage, claim status, and limits without fabricating unverified coverage or unauthorized claim approvals?",
      "criteria": {
        "yes": "Reply strictly adheres to customer policy and claim records",
        "no": "Reply promises coverage, roadside service, or payout not supported by policy records"
      }
    }
  }
}
```

### 4. Guardrail Verification Integration
* Update `api/guardrails.py` endpoint `POST /api/v1/guardrails/verify` to invoke semantic grounding check alongside regex entity check.
* Return unified JSON:
```json
{
  "passed": true,
  "regex_passed": true,
  "semantic_grounded": true,
  "detected_entities": { ... },
  "rejection_reason": null
}
```

---

## Implementation Steps

| Step | Action | Files Affected | Target Status |
|---|---|---|---|
| **Step 1** | Add ADR-023 & ADR-024 to engineering log | `docs/DECISIONS.md` | Complete |
| **Step 2** | Update JEV Gate JSON body in Workflow 04 for Priority Scoring | `workflows/04_orchestrator_email_ingestion.json` | Tested |
| **Step 3** | Update `api/guardrails.py` with JEV Semantic Grounding helper | `api/guardrails.py` | Tested |
| **Step 4** | Import & publish updated n8n workflows | Container `n8n` | Active |
| **Step 5** | Execute end-to-end synthetic & inbox verification tests | `scripts/execute_case*.py` | Verified |
| **Step 6** | Update system documentation | `docs/ARCHITECTURE.md` | Updated |

---

## Rollback & Safety Guarantees

1. **Additive Design:** All JEV questions and grounding checks return structured fallbacks (`neverError: true`).
2. **Instant Rollback:**
   - Set `JEV_GROUNDING_ENABLED=false` in `.env` to bypass Phase 3 grounding without workflow restarts.
   - Restore the backup workflow JSON to bypass Phase 2 scoring and revert to classic pipeline.
3. **Backup Files:** `workflows/04_orchestrator_email_ingestion.json.bak` preserved.
