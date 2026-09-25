-- AI Insurance Triage Agent Database Schema (SQLite)
-- Global production standard with constraints, enum CHECKs, and indexes

PRAGMA foreign_keys = ON;

-- 1. Customers Table
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT,
    city TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email);

-- 2. Vehicles Table
CREATE TABLE IF NOT EXISTS vehicles (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    year INTEGER NOT NULL,
    vin TEXT UNIQUE,
    registration_number TEXT UNIQUE NOT NULL,
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_vehicles_customer ON vehicles(customer_id);

-- 3. Policies Table
CREATE TABLE IF NOT EXISTS policies (
    policy_number TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    vehicle_id TEXT NOT NULL,
    policy_type TEXT NOT NULL CHECK(policy_type IN (
        'Comprehensive',
        'Comprehensive Zero-Dep',
        'Comprehensive EV',
        'Zero-Dep Bumper to Bumper',
        'Third-Party + Own Damage',
        'Third-Party Only'
    )),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    premium_amount REAL NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'Active',
        'Expired',
        'Cancelled',
        'Pending-Renewal'
    )),
    ncb_percentage INTEGER DEFAULT 0 CHECK(ncb_percentage BETWEEN 0 AND 50),
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY(vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_policies_customer ON policies(customer_id);
CREATE INDEX IF NOT EXISTS idx_policies_status ON policies(status);

-- 4. Policy Coverage Definitions
CREATE TABLE IF NOT EXISTS policy_coverage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_type TEXT NOT NULL,
    coverage_name TEXT NOT NULL,
    coverage_details TEXT NOT NULL,
    roadside_assistance_included INTEGER DEFAULT 0 CHECK(roadside_assistance_included IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_coverage_type ON policy_coverage(policy_type);

-- 5. Claims Table (Financial audit safe: default NO ACTION on delete)
CREATE TABLE IF NOT EXISTS claims (
    claim_number TEXT PRIMARY KEY,
    policy_number TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    incident_date DATE NOT NULL,
    filing_date DATE NOT NULL,
    claim_amount REAL NOT NULL,
    approved_amount REAL DEFAULT 0,
    status TEXT NOT NULL CHECK(status IN (
        'Under-Review',
        'Documents-Pending',
        'Inspection-Scheduled',
        'Approved',
        'Rejected',
        'Settled'
    )),
    claim_type TEXT NOT NULL CHECK(claim_type IN (
        'Accidental',
        'Theft',
        'Third-Party',
        'Windshield',
        'Flood',
        'Fire'
    )),
    description TEXT,
    FOREIGN KEY(policy_number) REFERENCES policies(policy_number),
    FOREIGN KEY(customer_id) REFERENCES customers(id)
);
CREATE INDEX IF NOT EXISTS idx_claims_customer ON claims(customer_id);
CREATE INDEX IF NOT EXISTS idx_claims_policy ON claims(policy_number);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);

-- 6. Claim Documents Table
CREATE TABLE IF NOT EXISTS claim_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_number TEXT NOT NULL,
    document_type TEXT NOT NULL,
    document_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'Received',
        'Verified',
        'Pending',
        'Rejected'
    )),
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(claim_number) REFERENCES claims(claim_number) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_claim_docs_claim ON claim_documents(claim_number);

-- 7. Payments Table (Financial audit safe: default NO ACTION on delete)
CREATE TABLE IF NOT EXISTS payments (
    payment_id TEXT PRIMARY KEY,
    policy_number TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    amount REAL NOT NULL,
    payment_date DATE NOT NULL,
    payment_method TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'Success',
        'Failed',
        'Refunded',
        'Pending'
    )),
    FOREIGN KEY(policy_number) REFERENCES policies(policy_number),
    FOREIGN KEY(customer_id) REFERENCES customers(id)
);
CREATE INDEX IF NOT EXISTS idx_payments_policy ON payments(policy_number);

-- 8. Renewals Table (Financial audit safe: default NO ACTION on delete)
CREATE TABLE IF NOT EXISTS renewals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_number TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    expiry_date DATE NOT NULL,
    renewal_quote REAL NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'Eligible',
        'Due',
        'Overdue',
        'Renewed',
        'Lapsed'
    )),
    notice_sent INTEGER DEFAULT 0 CHECK(notice_sent IN (0, 1, 2)),
    FOREIGN KEY(policy_number) REFERENCES policies(policy_number),
    FOREIGN KEY(customer_id) REFERENCES customers(id)
);
CREATE INDEX IF NOT EXISTS idx_renewals_policy ON renewals(policy_number);

-- 9. Network Garages Table
CREATE TABLE IF NOT EXISTS network_garages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    garage_name TEXT NOT NULL,
    city TEXT NOT NULL,
    address TEXT NOT NULL,
    phone TEXT NOT NULL,
    cashless_supported INTEGER DEFAULT 1 CHECK(cashless_supported IN (0, 1)),
    supported_brands TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_garages_city ON network_garages(city);

-- 10. Support Tickets Table
CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    policy_number TEXT,
    claim_number TEXT,
    category TEXT NOT NULL,
    priority TEXT NOT NULL CHECK(priority IN ('Low', 'Medium', 'High', 'Critical')),
    subject TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'Open',
        'In-Progress',
        'Pending-Customer',
        'Resolved',
        'Closed'
    )),
    assigned_team TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY(policy_number) REFERENCES policies(policy_number) ON DELETE SET NULL,
    FOREIGN KEY(claim_number) REFERENCES claims(claim_number) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_customer ON support_tickets(customer_id);

-- 11. Processed Emails (Idempotency Table)
CREATE TABLE IF NOT EXISTS processed_emails (
    message_id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_at TIMESTAMP NOT NULL,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL CHECK(status IN ('Processed', 'Archived', 'Ignored', 'Error'))
);

-- 12. Triage Results (Audit & Dashboard Data Table)
CREATE TABLE IF NOT EXISTS triage_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    customer_id TEXT,
    policy_number TEXT,
    claim_number TEXT,
    category TEXT NOT NULL,
    intent TEXT NOT NULL,
    priority TEXT NOT NULL CHECK(priority IN ('Low', 'Medium', 'High', 'Critical')),
    urgency_score INTEGER DEFAULT 1 CHECK(urgency_score BETWEEN 1 AND 5),
    sentiment TEXT,
    escalation_needed INTEGER DEFAULT 0 CHECK(escalation_needed IN (0, 1)),
    summary TEXT,
    suggested_reply TEXT,
    routed_to TEXT,
    guardrail_status TEXT DEFAULT 'PENDING' CHECK(guardrail_status IN ('PENDING', 'PASSED', 'REJECTED', 'BYPASS')),
    rejection_reason TEXT,
    approval_status TEXT DEFAULT 'PENDING' CHECK(approval_status IN ('PENDING', 'APPROVED', 'REJECTED', 'AUTO_ESCALATED', 'AUTO_BYPASS')),
    reply_status TEXT DEFAULT 'NOT_SENT' CHECK(reply_status IN ('NOT_SENT', 'SENT', 'SUPPRESSED', 'FAILED')),
    telegram_message_id INTEGER,
    telegram_chat_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL,
    FOREIGN KEY(policy_number) REFERENCES policies(policy_number) ON DELETE SET NULL,
    FOREIGN KEY(claim_number) REFERENCES claims(claim_number) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_triage_intent ON triage_results(intent);
CREATE INDEX IF NOT EXISTS idx_triage_priority ON triage_results(priority);
CREATE INDEX IF NOT EXISTS idx_triage_created ON triage_results(created_at);
