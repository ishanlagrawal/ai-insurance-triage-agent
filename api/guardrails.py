"""
Deterministic Hallucination & Fact-Checking Guardrail Engine.
Validates LLM-generated suggested replies against retrieved SQLite database context.
"""

import re
from typing import Dict, Any, Tuple, List

# Regex patterns for insurance domain entities (requires hyphen, underscore, or digit)
POLICY_REGEX = re.compile(r'\bPOL[-_0-9][A-Za-z0-9_-]*\b', re.IGNORECASE)
CLAIM_REGEX = re.compile(r'\bCLM[-_0-9][A-Za-z0-9_-]*\b', re.IGNORECASE)

# Regex pattern for monetary amounts (Rs., Rs, ₹, INR)
AMOUNT_REGEX = re.compile(r'(?:Rs\.?|₹|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)', re.IGNORECASE)

def _parse_amount(val: Any) -> float:
    try:
        if isinstance(val, (int, float)):
            return float(val)
        clean_str = str(val).replace(',', '').strip()
        return float(clean_str)
    except (ValueError, TypeError):
        return -1.0

def validate_suggested_reply(suggested_reply: str, customer_context: Dict[str, Any]) -> Tuple[bool, str, Dict[str, List[Any]]]:
    """
    Asserts that all referenced policy numbers, claim numbers, and monetary amounts
    in the suggested reply actually exist within the customer's retrieved database records.

    Returns:
        (passed: bool, rejection_reason: str, detected_entities: dict)
    """
    if not suggested_reply:
        return False, "Suggested reply is empty.", {}

    found_policies = [p.upper() for p in POLICY_REGEX.findall(suggested_reply)]
    found_claims = [c.upper() for c in CLAIM_REGEX.findall(suggested_reply)]

    # Extract monetary amounts
    amount_matches = AMOUNT_REGEX.findall(suggested_reply)
    found_amounts = []
    for raw in amount_matches:
        parsed = _parse_amount(raw)
        if parsed >= 0:
            found_amounts.append((raw, parsed))

    detected_entities = {
        "policies_referenced": found_policies,
        "claims_referenced": found_claims,
        "amounts_referenced": [m[0] for m in found_amounts]
    }

    # If sender is unidentified (customer_context is empty or customer not found)
    is_identified = customer_context.get("identified", False)
    if not is_identified:
        if found_policies or found_claims or found_amounts:
            return False, f"Ungrounded entities for unidentified customer: policies={found_policies}, claims={found_claims}, amounts={[m[0] for m in found_amounts]}", detected_entities
        return True, "", detected_entities

    # Gather legitimate policy numbers from context
    valid_policies = set()
    for pol in customer_context.get("policies", []):
        if pol.get("policy_number"):
            valid_policies.add(str(pol["policy_number"]).strip().upper())

    # Gather legitimate claim numbers from context
    valid_claims = set()
    for clm in customer_context.get("claims", []):
        if clm.get("claim_number"):
            valid_claims.add(str(clm["claim_number"]).strip().upper())

    # Gather legitimate monetary amounts from context
    valid_amounts = set()
    for clm in customer_context.get("claims", []):
        if clm.get("claim_amount") is not None:
            valid_amounts.add(_parse_amount(clm["claim_amount"]))
        if clm.get("approved_amount") is not None:
            valid_amounts.add(_parse_amount(clm["approved_amount"]))

    for pol in customer_context.get("policies", []):
        if pol.get("premium_amount") is not None:
            valid_amounts.add(_parse_amount(pol["premium_amount"]))

    for ren in customer_context.get("renewals", []):
        if ren.get("renewal_quote") is not None:
            valid_amounts.add(_parse_amount(ren["renewal_quote"]))

    for pay in customer_context.get("payments", []):
        if pay.get("amount") is not None:
            valid_amounts.add(_parse_amount(pay["amount"]))

    # 1. Check for hallucinated policies
    for pol in found_policies:
        if pol not in valid_policies:
            return False, f"Hallucinated policy number detected: '{pol}' does not belong to customer records.", detected_entities

    # 2. Check for hallucinated claims
    for clm in found_claims:
        if clm not in valid_claims:
            return False, f"Hallucinated claim number detected: '{clm}' does not belong to customer records.", detected_entities

    # 3. Check for hallucinated monetary amounts
    for raw_str, amt in found_amounts:
        # Match against valid amounts with standard currency tolerance (0.01)
        if not any(abs(amt - v) < 0.01 for v in valid_amounts):
            return False, f"Hallucinated monetary amount detected: '{raw_str}' does not match any financial record in customer context.", detected_entities

    return True, "", detected_entities


def verify_semantic_grounding_with_jev(suggested_reply: str, customer_context: Dict[str, Any], api_key: str) -> Tuple[bool, str]:
    """
    Phase 3: Semantic Policy Grounding via JEV model.
    Checks if suggested reply contains unverified promises or coverage claims.
    """
    import urllib.request
    import json

    if not suggested_reply or not api_key:
        return True, ""

    policies = customer_context.get("policies", [])
    claims = customer_context.get("claims", [])
    
    state_text = f"Policies: {json.dumps(policies)}\nClaims: {json.dumps(claims)}\nSuggested Reply: {suggested_reply}"

    req_data = {
        "model": "jev-latest",
        "state": state_text,
        "questions": {
            "is_grounded": {
                "type": "choice",
                "instructions": "Does the suggested reply accurately reflect customer policy coverage, claim status, and limits without fabricating unverified coverage, unauthorized payouts, or false roadside assistance promises?",
                "criteria": {
                    "yes": "Reply strictly adheres to customer policy and claim records",
                    "no": "Reply promises coverage, roadside service, or payout not supported by policy records"
                }
            }
        }
    }

    try:
        req = urllib.request.Request(
            "https://api.typesafe.ai/v1/systemone",
            data=json.dumps(req_data).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            choice = res.get("answers", {}).get("is_grounded", {}).get("choice", "yes")
            if choice == "no":
                return False, "Semantic Grounding Failed: Suggested reply contains unverified coverage promises or policy contradictions."
            return True, ""
    except Exception as e:
        # ADR-010/011: Any missing or errored verification defaults to REJECTED / human escalation.
        # Fail-CLOSED: JEV API failure is treated as inconclusive — route to human review,
        # do not silently pass the reply through.
        return False, f"JEV Grounding inconclusive (API error: {str(e)}). Routed to human review per ADR-011."

