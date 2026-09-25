"""
FastAPI Sidecar Service for AI Insurance Inbox Triage Agent.
Provides SQLite data access, entity context retrieval, idempotency dedup,
guardrail verification, execution logging, and enterprise dashboard.
"""

import os
import csv
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from api.guardrails import validate_suggested_reply

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "db", "insurance.db")
CSV_PATH = os.path.join(BASE_DIR, "triage_results.csv")
TEMPLATES_DIR = os.path.join(BASE_DIR, "api", "templates")

app = FastAPI(title="Insurance Inbox Triage API", version="1.0.0")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

# ─── Pydantic Models ──────────────────────────────────────────────────────────

class DedupRequest(BaseModel):
    message_id: str
    sender: str
    subject: str
    received_at: str

class TriageLogRequest(BaseModel):
    message_id: str
    sender: str
    subject: str
    customer_id: Optional[str] = None
    policy_number: Optional[str] = None
    claim_number: Optional[str] = None
    category: str
    intent: str
    priority: str
    urgency_score: int = Field(default=1, ge=1, le=5)
    sentiment: Optional[str] = "Neutral"
    escalation_needed: int = Field(default=0, ge=0, le=1)
    summary: Optional[str] = ""
    suggested_reply: Optional[str] = ""
    routed_to: Optional[str] = "Customer Support"
    guardrail_status: str = "PASSED"
    rejection_reason: Optional[str] = None
    approval_status: str = "PENDING"
    reply_status: str = "NOT_SENT"

class GuardrailVerifyRequest(BaseModel):
    suggested_reply: str
    customer_context: Dict[str, Any]

class TriageApproveRequest(BaseModel):
    message_id: str
    action: str  # 'APPROVE', 'REJECT', 'AUTO_ESCALATE'
    reviewer_note: Optional[str] = None
    telegram_message_id: Optional[int] = None
    telegram_chat_id: Optional[str] = None

# ─── Core API Endpoints ───────────────────────────────────────────────────────

@app.get("/")
def root():
    return RedirectResponse(url="/dashboard")

@app.get("/health")
def health():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM customers;")
        cnt = cur.fetchone()[0]
        conn.close()
        return {"status": "ok", "customers_count": cnt}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/dedup/check")
def check_email_dedup_only(req: DedupRequest):
    """Read-only dedup check. Returns duplicate=True if message_id exists in processed_emails."""
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


@app.post("/api/v1/dedup/check-and-record")
def check_and_record_email(req: DedupRequest):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT message_id, status FROM processed_emails WHERE message_id = ?;", (req.message_id,))
        existing = cur.fetchone()
        if existing:
            conn.close()
            return {"duplicate": True, "message_id": req.message_id, "status": existing["status"]}

        cur.execute(
            "INSERT INTO processed_emails (message_id, sender, subject, received_at, status) VALUES (?, ?, ?, ?, 'Processed');",
            (req.message_id, req.sender, req.subject, req.received_at)
        )
        conn.commit()
        conn.close()
        
        # Mark email read in Gmail only for processed insurance emails
        mark_gmail_read_by_msgid(req.message_id)
        
        return {"duplicate": False, "message_id": req.message_id, "status": "Recorded"}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))


class SkipEmailRequest(BaseModel):
    """ADR-021: Records Jev-filtered non-insurance emails. Prevents LLM quota waste."""
    message_id: str
    sender: str
    subject: str
    status: str = "Ignored"
    jev_choice: Optional[str] = None
    jev_confidence: Optional[float] = None

@app.post("/api/v1/triage/skip-email")
def skip_email(req: SkipEmailRequest):
    """
    ADR-021 — Jev Pre-Filter Gate.
    Records non-insurance emails to processed_emails with Skipped-NonInsurance status.
    No triage_results row is created. Pipeline terminates here.
    Rollback: set JEV_GATE_ENABLED=false in .env — this endpoint becomes unreachable.
    """
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT message_id FROM processed_emails WHERE message_id = ?;",
            (req.message_id,)
        )
        if cur.fetchone():
            conn.close()
            return {"status": "already_recorded", "message_id": req.message_id}

        received_at = datetime.now(timezone.utc).isoformat()
        cur.execute(
            "INSERT INTO processed_emails (message_id, sender, subject, received_at, status) VALUES (?, ?, ?, ?, ?);",
            (req.message_id, req.sender, req.subject, received_at, req.status)
        )
        conn.commit()
        conn.close()
        return {
            "status": "skipped",
            "message_id": req.message_id,
            "jev_choice": req.jev_choice,
            "jev_confidence": req.jev_confidence
        }
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/customer/context")
def get_customer_context(email: str = Query(..., description="Customer sender email")):
    conn = get_db()
    cur = conn.cursor()
    try:
        # Search customer by email
        clean_email = email.strip().lower()
        cur.execute("SELECT * FROM customers WHERE LOWER(email) = ?;", (clean_email,))
        cust = cur.fetchone()

        if not cust:
            conn.close()
            return {
                "identified": False,
                "email": clean_email,
                "customer": None,
                "vehicles": [],
                "policies": [],
                "claims": [],
                "renewals": [],
                "payments": [],
                "network_garages": []
            }

        cust_id = cust["id"]
        customer_data = dict(cust)

        # Retrieve vehicles
        cur.execute("SELECT * FROM vehicles WHERE customer_id = ?;", (cust_id,))
        vehicles = [dict(r) for r in cur.fetchall()]

        # Retrieve policies with coverage info
        cur.execute("""
            SELECT p.*, c.coverage_details, c.roadside_assistance_included
            FROM policies p
            LEFT JOIN policy_coverage c ON p.policy_type = c.policy_type
            WHERE p.customer_id = ?;
        """, (cust_id,))
        policies = [dict(r) for r in cur.fetchall()]

        # Retrieve claims and documents
        cur.execute("SELECT * FROM claims WHERE customer_id = ?;", (cust_id,))
        claims = []
        for clm in cur.fetchall():
            clm_dict = dict(clm)
            cur.execute("SELECT * FROM claim_documents WHERE claim_number = ?;", (clm_dict["claim_number"],))
            clm_dict["documents"] = [dict(d) for d in cur.fetchall()]
            claims.append(clm_dict)

        # Retrieve renewals
        cur.execute("SELECT * FROM renewals WHERE customer_id = ?;", (cust_id,))
        renewals = [dict(r) for r in cur.fetchall()]

        # Retrieve payments
        cur.execute("SELECT * FROM payments WHERE customer_id = ? ORDER BY payment_date DESC LIMIT 5;", (cust_id,))
        payments = [dict(r) for r in cur.fetchall()]

        # Retrieve nearby network garages matching customer's city
        cust_city = cust["city"]
        cur.execute("SELECT * FROM network_garages WHERE LOWER(city) = LOWER(?);", (cust_city,))
        garages = [dict(r) for r in cur.fetchall()]

        # Retrieve existing support tickets
        cur.execute("SELECT * FROM support_tickets WHERE customer_id = ? ORDER BY created_at DESC;", (cust_id,))
        tickets = [dict(r) for r in cur.fetchall()]

        conn.close()
        return {
            "identified": True,
            "email": clean_email,
            "customer": customer_data,
            "vehicles": vehicles,
            "policies": policies,
            "claims": claims,
            "renewals": renewals,
            "payments": payments,
            "network_garages": garages,
            "support_tickets": tickets
        }
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

from api.guardrails import validate_suggested_reply, verify_semantic_grounding_with_jev

@app.post("/api/v1/guardrails/verify")
def verify_guardrails(req: GuardrailVerifyRequest):
    regex_passed, reason, entities = validate_suggested_reply(req.suggested_reply, req.customer_context)
    if not regex_passed:
        return {
            "passed": False,
            "rejection_reason": reason,
            "entities_detected": entities
        }

    # Phase 3: JEV Semantic Policy Grounding
    api_key = os.getenv("JEV_API_KEY") or os.getenv("TYPESAFE_API_KEY", "")
    grounded, ground_reason = verify_semantic_grounding_with_jev(req.suggested_reply, req.customer_context, api_key)
    
    if not grounded:
        return {
            "passed": False,
            "rejection_reason": ground_reason,
            "entities_detected": entities
        }

    return {
        "passed": True,
        "rejection_reason": None,
        "entities_detected": entities
    }

@app.post("/api/v1/triage/log")
def log_triage_result(req: TriageLogRequest):
    conn = get_db()
    cur = conn.cursor()
    try:
        # Insert into triage_results table
        cur.execute("""
            INSERT INTO triage_results (
                message_id, sender, subject, customer_id, policy_number, claim_number,
                category, intent, priority, urgency_score, sentiment, escalation_needed,
                summary, suggested_reply, routed_to, guardrail_status, rejection_reason,
                approval_status, reply_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            req.message_id, req.sender, req.subject, req.customer_id, req.policy_number, req.claim_number,
            req.category, req.intent, req.priority, req.urgency_score, req.sentiment, req.escalation_needed,
            req.summary, req.suggested_reply, req.routed_to, req.guardrail_status, req.rejection_reason,
            req.approval_status, req.reply_status
        ))

        # Automatic Support Ticket Creation / Association
        if req.customer_id:
            # Check existing open ticket for this customer
            cur.execute("""
                SELECT ticket_id FROM support_tickets 
                WHERE customer_id = ? AND status IN ('Open', 'In-Progress', 'Pending-Customer')
                LIMIT 1;
            """, (req.customer_id,))
            existing_ticket = cur.fetchone()

            if not existing_ticket:
                ticket_id = f"TCK-{os.urandom(3).hex().upper()}"
                cur.execute("""
                    INSERT INTO support_tickets (
                        ticket_id, customer_id, policy_number, claim_number,
                        category, priority, subject, status, assigned_team
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Open', ?);
                """, (
                    ticket_id, req.customer_id, req.policy_number, req.claim_number,
                    req.category, req.priority, req.subject, req.routed_to or "Claims Desk"
                ))

        row_id = cur.lastrowid

        # Ensure message_id is recorded in processed_emails as 'Processed' and marked read in Gmail
        try:
            cur.execute(
                "INSERT INTO processed_emails (message_id, sender, subject, received_at, status) VALUES (?, ?, ?, ?, 'Processed') ON CONFLICT(message_id) DO UPDATE SET status='Processed';",
                (req.message_id, req.sender, req.subject, datetime.now(timezone.utc).isoformat())
            )
            mark_gmail_read_by_msgid(req.message_id)
        except Exception as pe_err:
            print(f"Warning: Failed recording to processed_emails in log_triage_result: {pe_err}")

        conn.commit()
        conn.close()

        # Append to CSV
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    req.message_id, req.sender, req.subject, req.customer_id or "",
                    req.policy_number or "", req.claim_number or "", req.category, req.intent,
                    req.priority, req.urgency_score, req.sentiment, req.escalation_needed,
                    req.guardrail_status, req.approval_status, req.reply_status, timestamp
                ])
        except Exception as csv_err:
            print(f"Warning: Failed to write to CSV: {csv_err}")

        return {"status": "logged", "id": row_id, "message_id": req.message_id}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/triage/update-telegram-meta")
def update_telegram_meta(req: Dict[str, Any]):
    message_id = req.get("message_id")
    telegram_message_id = req.get("telegram_message_id")
    telegram_chat_id = req.get("telegram_chat_id")
    if not message_id or not telegram_message_id:
        raise HTTPException(status_code=400, detail="message_id and telegram_message_id are required")
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE triage_results
            SET telegram_message_id = ?, telegram_chat_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE message_id = ? OR CAST(id AS TEXT) = ?;
        """, (telegram_message_id, str(telegram_chat_id) if telegram_chat_id else None, str(message_id), str(message_id)))
        conn.commit()
        conn.close()
        return {"status": "success", "message_id": message_id}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/triage/approve")
def approve_triage_result(req: TriageApproveRequest):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, message_id, approval_status, reply_status, escalation_needed, 
                   customer_id, policy_number, claim_number, sender, subject
            FROM triage_results 
            WHERE message_id = ? OR CAST(id AS TEXT) = ?;
        """, (str(req.message_id), str(req.message_id)))
        existing = cur.fetchone()
        if not existing:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Triage record not found for message_id: {req.message_id}")

        # Idempotency early-exit check
        current_approval = existing["approval_status"]
        if current_approval != "PENDING":
            conn.close()
            return {
                "status": "noop",
                "message": "Action ignored; record is already in terminal state.",
                "message_id": req.message_id,
                "current_approval_status": current_approval,
                "current_reply_status": existing["reply_status"]
            }

        act = req.action.strip().upper()
        if act == "APPROVE":
            new_approval = "APPROVED"
            new_reply = "NOT_SENT"
            new_esc = 0
        elif act == "REJECT":
            new_approval = "REJECTED"
            new_reply = "SUPPRESSED"
            new_esc = 1
        elif act == "AUTO_ESCALATE":
            new_approval = "AUTO_ESCALATED"
            new_reply = "SUPPRESSED"
            new_esc = 1
        else:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Invalid action: {req.action}. Expected APPROVE, REJECT, or AUTO_ESCALATE.")

        # Atomic state transition with concurrency protection
        cur.execute("""
            UPDATE triage_results
            SET approval_status = ?, reply_status = ?, escalation_needed = ?,
                telegram_message_id = COALESCE(?, telegram_message_id),
                telegram_chat_id = COALESCE(?, telegram_chat_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE (message_id = ? OR CAST(id AS TEXT) = ?) AND approval_status = 'PENDING';
        """, (
            new_approval, new_reply, new_esc,
            req.telegram_message_id, req.telegram_chat_id,
            str(req.message_id), str(req.message_id)
        ))

        if cur.rowcount == 0:
            # Concurrent request already claimed the transition
            cur.execute("SELECT approval_status, reply_status FROM triage_results WHERE message_id = ? OR CAST(id AS TEXT) = ?;", (str(req.message_id), str(req.message_id)))
            fresh = cur.fetchone()
            conn.close()
            return {
                "status": "noop",
                "message": "Action ignored; concurrent transaction resolved pending state.",
                "message_id": req.message_id,
                "current_approval_status": fresh["approval_status"] if fresh else current_approval,
                "current_reply_status": fresh["reply_status"] if fresh else existing["reply_status"]
            }

        # Update support ticket if escalated (scoped strictly to matching policy or claim)
        pol = existing["policy_number"]
        clm = existing["claim_number"]
        cust_id = existing["customer_id"]

        if new_esc == 1 and cust_id and (pol or clm):
            query = """
                UPDATE support_tickets 
                SET status = 'In-Progress', priority = 'Critical'
                WHERE customer_id = ? AND status = 'Open'
            """
            params = [cust_id]
            if pol and clm:
                query += " AND (policy_number = ? OR claim_number = ?);"
                params.extend([pol, clm])
            elif pol:
                query += " AND policy_number = ?;"
                params.append(pol)
            elif clm:
                query += " AND claim_number = ?;"
                params.append(clm)

            cur.execute(query, tuple(params))

        conn.commit()
        conn.close()

        return {
            "status": "success",
            "message_id": req.message_id,
            "action": act,
            "approval_status": new_approval,
            "reply_status": new_reply,
            "escalation_needed": new_esc,
            "sender": existing["sender"],
            "subject": existing["subject"],
            "suggested_reply": existing["suggested_reply"]
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/triage/pending-expired")
def get_pending_expired(hours: float = Query(default=4.0, ge=0.01, description="Expiration threshold in hours")):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, message_id, sender, subject, customer_id, policy_number, claim_number,
                   category, intent, priority, urgency_score, escalation_needed,
                   telegram_message_id, telegram_chat_id, created_at
            FROM triage_results
            WHERE approval_status = 'PENDING'
              AND created_at <= datetime('now', '-' || ? || ' hours');
        """, (hours,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"count": len(rows), "hours_threshold": hours, "records": rows}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/triage/dispatch-email")
def dispatch_email(req: Dict[str, Any]):
    message_id = req.get("message_id")
    if not message_id:
        raise HTTPException(status_code=400, detail="message_id is required")
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, message_id, sender, subject, suggested_reply, approval_status, reply_status
            FROM triage_results
            WHERE message_id = ? OR CAST(id AS TEXT) = ?;
        """, (str(message_id), str(message_id)))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Triage record not found")
        
        if row["approval_status"] != "APPROVED":
            raise HTTPException(status_code=400, detail=f"Cannot dispatch email with approval_status={row['approval_status']}")
        
        if row["reply_status"] == "SENT":
            return {"status": "noop", "message": "Email already sent", "message_id": message_id}
        
        to_email = row["sender"]
        raw_subject = f"Re: {row['subject']}" if not row["subject"].startswith("Re:") else row["subject"]
        subject = raw_subject.replace("\r", " ").replace("\n", " ").strip()
        body = row["suggested_reply"] or "Thank you for contacting customer support. We are reviewing your inquiry."

        # Execute SMTP send
        import smtplib
        from email.mime.text import MIMEText
        
        user = os.getenv("EMAIL_USER")
        pwd = os.getenv("EMAIL_PASSWORD")
        host = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
        port = int(os.getenv("EMAIL_SMTP_PORT", "465"))
        
        if not user or not pwd:
            raise HTTPException(status_code=500, detail="SMTP credentials not configured in environment")
        
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = user
        msg["To"] = to_email
        msg["Subject"] = subject
        
        try:
            if port == 465:
                server = smtplib.SMTP_SSL(host, port, timeout=15)
            else:
                server = smtplib.SMTP(host, port, timeout=15)
                server.starttls()
            
            server.login(user, pwd)
            server.sendmail(user, [to_email], msg.as_string())
            server.quit()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"SMTP dispatch failed: {str(e)}")

        # Update reply_status strictly upon verified SMTP transmission
        cur.execute("""
            UPDATE triage_results
            SET reply_status = 'SENT', updated_at = CURRENT_TIMESTAMP
            WHERE (message_id = ? OR CAST(id AS TEXT) = ?) AND approval_status = 'APPROVED';
        """, (str(message_id), str(message_id)))
        conn.commit()

        return {
            "status": "success",
            "message_id": message_id,
            "recipient": to_email,
            "reply_status": "SENT"
        }
    finally:
        conn.close()

def mark_gmail_read_by_msgid(message_id: str):
    import imaplib
    user = os.getenv("EMAIL_USER")
    pwd = os.getenv("EMAIL_PASSWORD")
    host = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
    port = int(os.getenv("EMAIL_IMAP_PORT", "993"))
    if not user or not pwd or not message_id:
        return
    try:
        mail = imaplib.IMAP4_SSL(host, port, timeout=10)
        mail.login(user, pwd)
        mail.select("INBOX")
        status, search_data = mail.search(None, f'HEADER Message-ID "{message_id}"')
        if status == "OK" and search_data[0]:
            for mid in search_data[0].split():
                mail.store(mid, '+FLAGS', '\\Seen')
        mail.close()
        mail.logout()
    except Exception as e:
        print(f"Error marking email read: {e}")

@app.get("/api/v1/inbox/poll-unread")
def poll_unread_emails(limit: int = 5):
    import imaplib
    import email
    from email.header import decode_header
    
    user = os.getenv("EMAIL_USER")
    pwd = os.getenv("EMAIL_PASSWORD")
    host = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
    port = int(os.getenv("EMAIL_IMAP_PORT", "993"))
    
    if not user or not pwd:
        raise HTTPException(status_code=500, detail="IMAP credentials not configured in environment")
    
    try:
        mail = imaplib.IMAP4_SSL(host, port, timeout=15)
        mail.login(user, pwd)
        mail.select("INBOX")
        
        status, search_data = mail.search(None, "UNSEEN")
        if status != "OK":
            mail.close()
            mail.logout()
            return {"count": 0, "emails": []}
        
        msg_ids = search_data[0].split()
        if not msg_ids:
            mail.close()
            mail.logout()
            return {"count": 0, "emails": []}
        
        results = []
        # Process up to limit unread emails
        for mid in msg_ids[-limit:]:
            # PEEK prevents IMAP from automatically marking email as SEEN/READ
            status, fetch_data = mail.fetch(mid, "(BODY.PEEK[])")
            if status != "OK" or not fetch_data or not fetch_data[0]:
                continue
            
            raw_email = fetch_data[0][1]
            msg = email.message_from_bytes(raw_email)
            
            # Extract Message-ID
            message_id = msg.get("Message-ID")
            if message_id:
                message_id = message_id.strip("<> \t\r\n")
            else:
                import hashlib
                message_id = f"gen-{hashlib.sha256(raw_email).hexdigest()[:16]}"
            
            # Extract Subject
            raw_sub, encoding = decode_header(msg.get("Subject", "No Subject"))[0]
            if isinstance(raw_sub, bytes):
                subject = raw_sub.decode(encoding or "utf-8", errors="replace")
            else:
                subject = str(raw_sub)
            
            # Extract Sender
            raw_from = msg.get("From", "")
            import re
            email_match = re.search(r"[\w\.-]+@[\w\.-]+", raw_from)
            sender_email = email_match.group(0).lower() if email_match else raw_from
            
            # Extract Body
            body_text = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))
                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body_text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                            break
                if not body_text:
                    for part in msg.walk():
                        if part.get_content_type() == "text/html":
                            payload = part.get_payload(decode=True)
                            if payload:
                                html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                                # basic strip tags
                                body_text = re.sub(r"<[^>]+>", " ", html)
                                break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            
            received_at = msg.get("Date", datetime.now(timezone.utc).isoformat())
            
            results.append({
                "message_id": message_id,
                "sender": sender_email,
                "subject": subject,
                "body": body_text.strip(),
                "received_at": received_at
            })
            
        mail.close()
        mail.logout()
        return {"count": len(results), "emails": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"IMAP poll error: {str(e)}")


@app.get("/api/v1/stats")
def get_stats():
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT count(*) FROM triage_results;")
        total_inquiries = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM triage_results WHERE priority = 'Critical' OR urgency_score >= 4;")
        critical = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM triage_results WHERE escalation_needed = 1 OR approval_status = 'REJECTED';")
        escalations = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM triage_results WHERE reply_status = 'SENT';")
        auto_replied = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM triage_results WHERE approval_status = 'PENDING';")
        pending_approval = cur.fetchone()[0]

        conn.close()
        return {
            "total_inquiries": total_inquiries,
            "critical_emergencies": critical,
            "human_escalations": escalations,
            "auto_replied": auto_replied,
            "pending_approval": pending_approval
        }
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/triage/list")
def list_triage_results(limit: int = 50):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM triage_results ORDER BY id DESC LIMIT ?;", (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

# ─── Dashboard UI ─────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html")
