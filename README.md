# 🛡️ AI Insurance Inbox Triage & Autonomous Guardrail Agent

An enterprise-grade, production-validated AI agent for automated email triage, intent classification, guardrail validation, and human-in-the-loop approval routing for motor & health insurance support desks.

Built with **n8n**, **FastAPI**, **Google Gemini / Inception Mercury LLM**, **SQLite**, and **Telegram Bot Webhooks**.

---

## 🖥️ Live Operations Dashboard Console

![Insurance Triage Ops Dashboard Console](docs/images/dashboard_preview.png)

*The Web Operations Dashboard (`http://localhost:8008/dashboard`) provides real-time visibility into incoming claims, critical emergencies, human escalations, and automated guardrail verification status.*

---

## 🏗️ System Architecture

```
                                  +-----------------------+
                                  |   Customer Email      |
                                  |   (IMAP Poll 60s)     |
                                  +-----------+-----------+
                                              |
                                              v
                                  +-----------+-----------+
                                  |   Deduplication Check |
                                  |   (SQLite DB)         |
                                  +-----------+-----------+
                                              |
                                              v
                                  +-----------+-----------+
                                  |  Customer DB Lookup   |
                                  | (Policies / Claims)   |
                                  +-----------+-----------+
                                              |
                                              v
+-----------------------+         +-----------+-----------+
|  Deterministic        | <-----> |   LLM Reasoning Engine|
|  SQLite Guardrail     |         | (Gemini / Mercury-2.5)|
+-----------+-----------+         +-----------+-----------+
            |                                 |
     FAILED |                                 | PASSED
            v                                 v
+-----------+-----------+         +-----------+-----------+
|  Auto-Escalated       |         | Telegram Approval Card|
|  (Suppressed Reply)   |         | (Interactive Webhook) |
+-----------------------+         +-----------+-----------+
                                              |
                                     APPROVE  |  REJECT
                                  +-----------+-----------+
                                  | SMTP Dispatch Email   |
                                  | (Live Customer Reply) |
                                  +-----------------------+
```

---

## ✨ Key Capabilities

1. **24 Insurance Intent Classifications**: Categorizes incoming customer emails into 24 distinct intents (Claims, Renewals, Roadside Assistance, Complaints, Policy Changes, etc.) with urgency scoring (1-5).
2. **Zero-Hallucination Guardrail Engine**: Deterministic Python guardrail validates that every policy number (`POL-...`), claim number (`CLM-...`), and monetary amount (`Rs. / ₹`) in suggested replies strictly exists in customer database records before approval.
3. **Human-in-the-Loop Telegram Approval**: Generates interactive Telegram approval cards for support desk supervisors. Clicking **Approve** dispatches the email via SMTP instantly.
4. **Automated SLA Escalation Cron**: Background cron checks for pending reviews exceeding 2 hours, auto-escalating items and notifying supervisory channels.
5. **Deduplication Engine**: Hash-based SQLite tracker prevents re-processing duplicate incoming emails across poll cycles.
6. **Optional JEV Pre-Filter & Grounding Extension**: Enterprise add-on module for pre-filtering non-insurance spam and semantic policy grounding ([`docs/JEV_EXTENSIONS.md`](docs/JEV_EXTENSIONS.md)).

---

## 📁 Repository Structure

```
.
├── api/
│   ├── main.py                # FastAPI sidecar server (Inbox, Guardrails, Approvals, Logging)
│   └── guardrails.py          # Deterministic Regex & Fact-Checking Engine
├── db/
│   ├── schema.sql             # Relational SQLite database schema
│   ├── seed_data.py           # Synthetic database seeder (100% synthetic @example.com records)
│   └── insurance.db           # Generated SQLite database
├── workflows/
│   ├── 01_subworkflow_classify_guardrail.json  # Classification & Guardrail Subworkflow
│   ├── 02_subworkflow_telegram_approval.json   # Telegram Approval Subworkflow
│   ├── 03_cron_sla_escalation.json             # SLA Escalation Cron Workflow
│   ├── 04_orchestrator_email_ingestion.json    # Core Orchestrator Workflow
│   └── extensions/
│       └── 04_orchestrator_email_ingestion_jev.json # Optional JEV-enabled Orchestrator
├── scripts/
│   └── run_golden_tests.py    # Unified E2E Golden Test Runner
├── tests/
│   ├── run_synthetic_test_suite.py  # 20-Email Synthetic Benchmark
│   ├── test_prompt_injection.py     # Security Benchmark
│   └── test_fault_tolerance.py      # Timeout & Fault Resilience Benchmark
├── docs/
│   ├── ARCHITECTURE.md        # Full Architectural Specifications
│   ├── DECISIONS.md           # Architecture Decision Records (ADR 001 - 028)
│   ├── JEV_EXTENSIONS.md      # Optional JEV Extension Integration Guide
│   └── STEP7_PORTFOLIO_PACKAGING_PLAN.md
├── docker-compose.yml         # Container Orchestration (n8n + FastAPI Sidecar)
├── Dockerfile                 # Sidecar Container Build Definition
├── .env.example               # Environment Variables Template
└── README.md                  # Project Documentation
```

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- Docker & Docker Compose
- Python 3.10+

### 2. Configuration
Clone the repository and copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in your credentials in `.env`:
- `GEMINI_API_KEY` or `INCEPTION_API_KEY`
- `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID`
- `IMAP_USER`, `IMAP_PASSWORD`, `SMTP_USER`, `SMTP_PASSWORD`

### 3. Initialize Synthetic Database
Regenerate a clean SQLite database containing synthetic customer records:
```bash
python db/seed_data.py
```

### 4. Start Containers
Launch n8n and the FastAPI sidecar container:
```bash
docker-compose up -d --build
```
Access the Dashboard UI at `http://localhost:8008/dashboard`.

---

## 🧪 Testing & Verification

Run the automated E2E Golden Test Suite against the classification and guardrail engine:
```bash
python scripts/run_golden_tests.py
```

Run security and fault-tolerance benchmarks:
```bash
pytest tests/test_prompt_injection.py
pytest tests/test_fault_tolerance.py
```

---

## 📚 Documentation & ADRs

- **[System Architecture](docs/ARCHITECTURE.md)**: Deep dive into workflow nodes, API contracts, and database schema.
- **[Architecture Decision Records](docs/DECISIONS.md)**: Complete chronological log of 28 ADRs detailing design choices, bug fixes, and safety trade-offs.
- **[JEV Extension Guide](docs/JEV_EXTENSIONS.md)**: Specifications for optional pre-filter gate and semantic policy grounding.

---

## 📄 License

Distributed under the MIT License.
