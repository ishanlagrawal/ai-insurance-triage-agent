import urllib.request
import urllib.parse
import json

def test_scenario(name, sender, subject, body):
    print(f"\n==========================================")
    print(f" TESTING: {name}")
    print(f" Sender: {sender}")
    print(f" Subject: {subject}")
    print(f"==========================================")
    
    import os
    jev_key = os.getenv("JEV_API_KEY", "")
    st = f"Subject: {subject}\nFrom: {sender}\nBody excerpt: {body}"
    req_data = {
        "model": "jev-latest",
        "state": st,
        "questions": {
            "is_insurance": {
                "type": "choice",
                "instructions": "Is this email related to insurance services (such as policy queries, claims, roadside assistance, breakdown towing, renewals, quotes, or complaints)? If the subject or body mentions policy numbers (POL-...), claims (CLM-...), roadside assistance, or motor insurance, choose yes.",
                "criteria": {
                    "yes": "The email is about insurance services, roadside assistance, policy queries, or claims",
                    "no": "The email is clearly unrelated to insurance"
                }
            },
            "urgency_rating": {
                "type": "choice",
                "instructions": "Rate the urgency of this insurance request based on customer impact.",
                "criteria": {
                    "CRITICAL": "Immediate emergency (vehicle stalled on highway, accident, towing request)",
                    "HIGH": "Time-sensitive issue (policy renewal expiring today, claim payment dispute)",
                    "MEDIUM": "Standard operational query (claim status update, document request)",
                    "LOW": "General inquiry, policy quote request, non-urgent feedback"
                }
            }
        }
    }
    req = urllib.request.Request(
        "https://api.typesafe.ai/v1/systemone",
        data=json.dumps(req_data).encode("utf-8"),
        headers={"Authorization": f"Bearer {jev_key}", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        jev_res = json.loads(resp.read().decode("utf-8"))["answers"]
    print(f"1. JEV Gate Result: choice={jev_res['is_insurance']['choice']}, urgency={jev_res['urgency_rating']['choice']}")

    if jev_res['is_insurance']['choice'] != 'yes':
        print("   Status: SKIPPED (Non-Insurance)")
        return

    # 2. Customer Context
    ctx_url = f"http://127.0.0.1:8008/api/v1/customer/context?email={urllib.parse.quote(sender)}"
    with urllib.request.urlopen(ctx_url) as resp:
        cust_ctx = json.loads(resp.read().decode("utf-8"))
    print(f"2. Customer Lookup: identified={cust_ctx.get('identified')}, customer_name={cust_ctx.get('customer', {}).get('full_name') if cust_ctx.get('customer') else 'UNIDENTIFIED'}")

    # 3. Guardrail Verification
    suggested_reply = "Thank you for reaching out to Insurance Triage Support. We have received your query and our team will assist you shortly."
    if cust_ctx.get("identified") and cust_ctx.get("policies"):
        pol = cust_ctx["policies"][0]["policy_number"]
        suggested_reply = f"Thank you for contacting us regarding policy {pol}. We have logged your request."

    gr_req = urllib.request.Request(
        "http://127.0.0.1:8008/api/v1/guardrails/verify",
        data=json.dumps({"suggested_reply": suggested_reply, "customer_context": cust_ctx}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(gr_req) as resp:
        gr_res = json.loads(resp.read().decode("utf-8"))
    print(f"3. Guardrail Result: passed={gr_res.get('passed')}, reason={gr_res.get('rejection_reason')}")

    if gr_res.get("passed"):
        print("   Status: PASSED -> Dispatches Telegram Approval Card with Active Approve & Reject Buttons")
    else:
        print("   Status: AUTO_ESCALATED -> Logged to DB for Human Review (No auto-telegram send)")

if __name__ == "__main__":
    # Test Scenario A: Registered Customer
    test_scenario(
        "Registered Customer Claim",
        "amitabh.sen.test@example.com",
        "Roadside assistance for POL-2026-3342",
        "My car stalled near Highway 4. Please send towing."
    )
    # Test Scenario B: Unidentified Sender General Quote Query
    test_scenario(
        "New Customer General Query",
        "newuser@example.com",
        "Inquiry regarding car insurance policy options",
        "Hi Team, I want to inquire about general motor insurance policy options."
    )
