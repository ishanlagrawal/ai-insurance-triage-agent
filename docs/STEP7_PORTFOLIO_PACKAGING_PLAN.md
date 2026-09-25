# Step 7 Portfolio Packaging & Release Plan

## 1. Secret Sweep & Git History Verification
- **Parent Git Audit**: Executed `git -C /docker/insurance-triage-agent rev-parse --show-toplevel` and `find /docker -name ".git"`. Confirmed `/docker/insurance-triage-agent` is an independent untracked folder (not inside `/docker/podcasts` or any parent git tree).
- **History Guarantee**: Zero git commit history exists on VPS. Initial git commit created during export will be 100% clean.
- **Automated Pre-Export Secret Sweep Gate**:
  ```bash
  grep -rE '(AIzaSy[A-Za-z0-9_-]{33}|[A-Za-z0-9_-]{20,}:[A-Za-z0-9_-]{35}|[0-9]{8,10}:[A-Za-z0-9_-]{35}|Bearer\s+[A-Za-z0-9._-]{20,}|(?:sk-|key-)[A-Za-z0-9]{20,})' /docker/insurance-triage-agent/
  ```

## 2. Environment Template (`.env.example`)
Create `/docker/insurance-triage-agent/.env.example` with exact placeholders:
```env
# Database Configuration
DATABASE_PATH=./db/insurance.db

# API Configuration
PORT=8008
HOST=0.0.0.0

# Telegram Bot Credentials
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN_HERE
TELEGRAM_CHAT_ID=YOUR_TELEGRAM_CHAT_ID_HERE
TELEGRAM_WEBHOOK_SECRET=YOUR_TELEGRAM_WEBHOOK_SECRET_HERE

# Primary LLM Credentials (Gemini / Mercury)
GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
INCEPTION_API_KEY=YOUR_INCEPTION_API_KEY_HERE

# Email Server Credentials (Gmail IMAP / SMTP)
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USER=your_email@gmail.com
IMAP_PASSWORD=your_app_password_here

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password_here

# Optional Extensions (JEV Model API)
JEV_API_KEY=YOUR_JEV_API_KEY_HERE
```

## 3. Workflow Credential ID Sanitization
Strip instance-specific n8n credential IDs (`YOUR_N8N_GEMINI_CRED_ID`, `YOUR_N8N_TELEGRAM_CRED_ID`, etc.) across all exported workflows in `workflows/` and `workflows/extensions/`, replacing with generic placeholders matching n8n template standards:
- `01_subworkflow_classify_guardrail.json`
- `02_subworkflow_telegram_approval.json`
- `03_cron_sla_escalation.json`
- `04_orchestrator_email_ingestion.json`
- `workflows/extensions/04_orchestrator_email_ingestion_jev.json`

## 4. Fresh Database Seed State
- **Database Sanitization**: `db/insurance.db` currently contains live test data (`tester@example.com`, `tester2@example.com`).
- **Action**: Prior to packaging, delete `db/insurance.db` and execute `python db/seed_data.py` to regenerate a clean SQLite database containing strictly synthetic `@example.com` records (`amitabh.sen.test@example.com`, etc.). Zero personal addresses will exist in the export.

## 5. File Cleanup & Test Suite Consolidation
### Files to REMOVE (Scratch / One-off ad-hoc files):
- Ad-hoc case execution scripts: `scripts/execute_case1.py`, `scripts/execute_case2.py`, `scripts/execute_case3.py`
- Ad-hoc workflow generator scripts: `scripts/generate_wf02.py`, `scripts/generate_wf04.py`
- Ad-hoc reset scripts: `scripts/reset_test_email.py`
- Local scratch backups: `*.bak` files across workspace
- IDE scratch directory contents: `/root/.gemini/antigravity-ide/brain/da9a3bad-a375-44a5-a536-6b2426bf168c/scratch/*`

### Files to KEEP & CONSOLIDATE (Core Production & Test Suite):
- **Core App**: `api/main.py`, `api/guardrails.py`
- **Database**: Clean `db/insurance.db` (re-seeded), `db/schema.sql`, `db/seed_data.py`
- **Workflows**: `workflows/*.json` (Sanitized core workflows) & `workflows/extensions/` (Sanitized JEV extension workflow)
- **Test Suite**:
  - `tests/run_synthetic_test_suite.py` (20-email synthetic benchmark)
  - `tests/test_prompt_injection.py` (Prompt injection suite)
  - `tests/test_fault_tolerance.py` (Resilience & timeout suite)
  - `tests/synthetic_emails.json` (Golden test dataset)
  - Create `scripts/run_golden_tests.py` as unified CLI entry point running end-to-end golden verification for portfolio reviewers.
- **Project Packaging**: `Dockerfile`, `docker-compose.yml`, `.env.example`, `requirements.txt`, `docs/`, `README.md`.
