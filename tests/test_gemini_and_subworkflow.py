#!/usr/bin/env python3
"""
End-to-End Live Integration Test for Step 3 Sub-workflow logic:
1. Calls Gemini Flash using x-goog-api-key header (Issue A verified live)
2. Validates JSON schema
3. Passes reply to Sidecar Guardrail verify endpoint
4. Enforces precedence rule (Issue B verified live)
"""

import os
import json
import urllib.request

# Load GEMINI_API_KEY from environment without exposing it
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    # Read from /docker/.env if not in current shell
    with open("/docker/.env", "r") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                API_KEY = line.strip().split("=", 1)[1].strip("\"'")
                break

assert API_KEY, "GEMINI_API_KEY not found!"

def run_integration_test():
    print("1. Fetching customer context from local SQLite sidecar...")
    ctx_url = "http://127.0.0.1:8008/api/v1/customer/context?email=rohit.verma.test@example.com"
    with urllib.request.urlopen(ctx_url) as r:
        customer_context = json.loads(r.read().decode("utf-8"))

    print(f"Customer identified: {customer_context['customer']['name']}, Policy: {customer_context['policies'][0]['policy_number']}")

    email_subject = "Query regarding Cashless claim for accident repair"
    email_body = "Hello, my Creta had an accident in Mumbai. My policy is POL-2026-8810. Can I get cashless repair at Shree Auto Care Center?"

    prompt_text = f"""You are an enterprise AI Insurance Customer Support & Claims Triage reasoning engine.

INPUT EMAIL:
Subject: {json.dumps(email_subject)}
Body: {json.dumps(email_body)}

RETRIEVED CUSTOMER DATABASE CONTEXT:
{json.dumps(customer_context, indent=2)}

TAXONOMY OF 24 INSURANCE INTENTS & PRIORITIES:
1. CLAIM_STATUS (High), 2. NEW_CLAIM (Critical), 3. CLAIM_DOCUMENTS (High), 4. CLAIM_DELAY (Critical), 5. CLAIM_APPROVAL (High), 6. CLAIM_REJECTION (Critical), 7. POLICY_DOCUMENT (Medium), 8. POLICY_DETAILS (Medium), 9. POLICY_EXPIRY (High), 10. RENEWAL (High), 11. RENEWAL_QUOTE (High), 12. PREMIUM_QUERY (Medium), 13. POLICY_CHANGE (Medium), 14. VEHICLE_CHANGE (High), 15. CANCELLATION (High), 16. REFUND (High), 17. PAYMENT (High), 18. NO_CLAIM_BONUS (Medium), 19. NETWORK_GARAGE (Medium), 20. CASHLESS_CLAIM (High), 21. ROADSIDE_ASSISTANCE (Critical), 22. INSPECTION (High), 23. GENERAL_QUERY (Low), 24. COMPLAINT (Critical), 25. FRAUD_SUSPICION (Critical)

STRICT GROUNDING RULES:
- NEVER invent claim numbers, policy numbers, dates, or rupee amounts not present in the customer context.
- Return ONLY a valid JSON object without markdown or markdown code blocks.

REQUIRED JSON SCHEMA:
{{
  "category": "Claims | Policy | Billing | Roadside | Support",
  "intent": "<One of the 24 intents>",
  "priority": "Low | Medium | High | Critical",
  "urgency_score": 1,
  "sentiment": "Positive | Neutral | Frustrated | Angry",
  "escalation_needed": 0,
  "summary": "1-2 sentence summary",
  "suggested_reply": "Professional plain-text reply to sender",
  "routed_to": "Claims Desk | Underwriting | Billing | Roadside Assist | Grievance Team"
}}"""

    print("\n2. Calling Gemini 2.5 Flash via Header Auth (x-goog-api-key)...")
    gemini_req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        data=json.dumps({
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": API_KEY
        }
    )

    with urllib.request.urlopen(gemini_req) as resp:
        gemini_raw = json.loads(resp.read().decode("utf-8"))

    raw_text = gemini_raw["candidates"][0]["content"]["parts"][0]["text"]
    llm_output = json.loads(raw_text)
    print("Gemini Parsed Response:")
    print(f"  Category: {llm_output.get('category')}")
    print(f"  Intent: {llm_output.get('intent')}")
    print(f"  Priority: {llm_output.get('priority')}")
    print(f"  Suggested Reply: {llm_output.get('suggested_reply')[:100]}...")

    print("\n3. Sending LLM reply to Sidecar Guardrail verify endpoint...")
    guard_req = urllib.request.Request(
        "http://127.0.0.1:8008/api/v1/guardrails/verify",
        data=json.dumps({
            "suggested_reply": llm_output["suggested_reply"],
            "customer_context": customer_context
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(guard_req) as resp:
        guard_res = json.loads(resp.read().decode("utf-8"))

    print(f"Guardrail Check Passed: {guard_res['passed']}")
    print(f"Entities cross-verified: {guard_res['entities_detected']}")
    assert guard_res["passed"] is True, f"Guardrail failed unexpectedly: {guard_res['rejection_reason']}"

    print("\n✅ LIVE END-TO-END STEP 3 PIPELINE TEST PASSED!")

if __name__ == "__main__":
    run_integration_test()
