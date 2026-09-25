#!/usr/bin/env python3
"""
Seed script for AI Insurance Triage Agent.
Generates 100% synthetic, fictional test data for SQLite database.
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "insurance.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

def init_and_seed():
    print(f"Connecting to database at {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Load and execute schema
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    cursor.executescript(schema_sql)

    # Clean existing data for clean idempotent seed
    tables = [
        "claim_documents", "claims", "payments", "renewals",
        "policies", "vehicles", "customers", "policy_coverage",
        "network_garages", "support_tickets", "processed_emails", "triage_results"
    ]
    for tbl in tables:
        cursor.execute(f"DELETE FROM {tbl};")

    print("Inserting synthetic customers...")
    customers = [
        ("CUST-001", "Rohit Verma", "rohit.verma.test@example.com", "+91-9820011223", "Mumbai"),
        ("CUST-002", "Priya Nair", "priya.nair.test@example.com", "+91-9845012345", "Bengaluru"),
        ("CUST-003", "Amitabh Sen", "amitabh.sen.test@example.com", "+91-9811023456", "Delhi"),
        ("CUST-004", "Sunita Rao", "sunita.rao.test@example.com", "+91-9876034567", "Hyderabad"),
        ("CUST-005", "Karan Malhotra", "karan.malhotra.test@example.com", "+91-9899045678", "Gurugram"),
        ("CUST-006", "Ananya Deshmukh", "ananya.deshmukh.test@example.com", "+91-9823056789", "Pune"),
        ("CUST-007", "Vikram Rathore", "vikram.rathore.test@example.com", "+91-9829067890", "Jaipur"),
        ("CUST-008", "Deepika Iyer", "deepika.iyer.test@example.com", "+91-9840078901", "Chennai"),
        ("CUST-009", "Manish Tiwari", "manish.tiwari.test@example.com", "+91-9839089012", "Lucknow"),
        ("CUST-010", "Sneha Kulkarni", "sneha.kulkarni.test@example.com", "+91-9822090123", "Pune")
    ]
    cursor.executemany("INSERT INTO customers (id, name, email, phone, city) VALUES (?, ?, ?, ?, ?);", customers)

    print("Inserting synthetic vehicles...")
    vehicles = [
        ("VEH-001", "CUST-001", "Hyundai", "Creta SX", 2023, "MALC381CLPM10001", "MH-02-EQ-8819"),
        ("VEH-002", "CUST-002", "Tata", "Nexon EV", 2024, "MAT622119PLM20002", "KA-01-MJ-4412"),
        ("VEH-003", "CUST-003", "Maruti Suzuki", "Brezza ZXi", 2022, "MA3ERB12SPLM30003", "DL-3C-AS-9910"),
        ("VEH-004", "CUST-004", "Kia", "Seltos GTX+", 2023, "MZ4K12908PLM40004", "TS-09-FA-7721"),
        ("VEH-005", "CUST-005", "Mahindra", "XUV700 AX7", 2024, "MA1X70020PLM50005", "HR-26-DK-3319"),
        ("VEH-006", "CUST-006", "Honda", "City ZX", 2021, "MAK193821PLM60006", "MH-12-RS-6624"),
        ("VEH-007", "CUST-007", "Toyota", "Innova Crysta", 2022, "MB1CR7820PLM70007", "RJ-14-CE-1188"),
        ("VEH-008", "CUST-008", "Volkswagen", "Taigun GT", 2023, "WVW128910PLM80008", "TN-07-BL-5509"),
        ("VEH-009", "CUST-009", "Tata", "Harrier Fearless", 2024, "MAT781290PLM90009", "UP-32-HN-2201"),
        ("VEH-010", "CUST-010", "Maruti Suzuki", "Swift ZXi+", 2023, "MA3SW9180PLM10010", "MH-14-JZ-9944")
    ]
    cursor.executemany("INSERT INTO vehicles (id, customer_id, make, model, year, vin, registration_number) VALUES (?, ?, ?, ?, ?, ?, ?);", vehicles)

    print("Inserting synthetic policies...")
    policies = [
        ("POL-2026-8810", "CUST-001", "VEH-001", "Comprehensive Zero-Dep", "2026-01-15", "2027-01-14", 24500.0, "Active", 25),
        ("POL-2026-9921", "CUST-002", "VEH-002", "Comprehensive EV", "2026-03-01", "2027-02-28", 19800.0, "Active", 20),
        ("POL-2026-3342", "CUST-003", "VEH-003", "Comprehensive", "2025-10-10", "2026-10-09", 14200.0, "Pending-Renewal", 35),
        ("POL-2026-7751", "CUST-004", "VEH-004", "Zero-Dep Bumper to Bumper", "2026-02-20", "2027-02-19", 28000.0, "Active", 0),
        ("POL-2026-5590", "CUST-005", "VEH-005", "Comprehensive", "2025-09-01", "2026-08-31", 31500.0, "Expired", 45),
        ("POL-2026-6614", "CUST-006", "VEH-006", "Comprehensive", "2026-04-12", "2027-04-11", 16800.0, "Active", 50),
        ("POL-2026-1188", "CUST-007", "VEH-007", "Third-Party + Own Damage", "2026-01-01", "2026-12-31", 21000.0, "Active", 30),
        ("POL-2026-4409", "CUST-008", "VEH-008", "Comprehensive Zero-Dep", "2026-05-15", "2027-05-14", 22500.0, "Active", 20),
        ("POL-2026-2201", "CUST-009", "VEH-009", "Comprehensive", "2026-02-01", "2027-01-31", 29000.0, "Active", 15),
        ("POL-2026-9944", "CUST-010", "VEH-010", "Third-Party Only", "2025-11-20", "2026-11-19", 7400.0, "Active", 0)
    ]
    cursor.executemany("INSERT INTO policies (policy_number, customer_id, vehicle_id, policy_type, start_date, end_date, premium_amount, status, ncb_percentage) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);", policies)

    print("Inserting policy coverage definitions...")
    coverage = [
        ("Comprehensive Zero-Dep", "Own Damage & Third Party", "100% coverage on plastic, fiber and metal parts without depreciation. Engine protector included.", 1),
        ("Comprehensive EV", "Electric Vehicle Protection", "Full battery pack protection against water ingress and internal short circuit. Wall charger cover.", 1),
        ("Comprehensive", "Standard Own Damage & Third Party", "Covers accidental damage, fire, theft, natural calamities with standard depreciation.", 1),
        ("Third-Party Only", "Mandatory Legal Liability", "Covers third-party injury, death, and property damage up to statutory limit. Own damage excluded.", 0)
    ]
    cursor.executemany("INSERT INTO policy_coverage (policy_type, coverage_name, coverage_details, roadside_assistance_included) VALUES (?, ?, ?, ?);", coverage)

    print("Inserting synthetic claims...")
    claims = [
        ("CLM-2026-4401", "POL-2026-8810", "CUST-001", "2026-08-10", "2026-08-11", 42500.0, 38000.0, "Approved", "Accidental", "Front bumper and headlight impact in traffic collision."),
        ("CLM-2026-7729", "POL-2026-7751", "CUST-004", "2026-09-02", "2026-09-03", 65000.0, 0.0, "Documents-Pending", "Accidental", "Right fender and door panel scrape in parking lot."),
        ("CLM-2026-5512", "POL-2026-1188", "CUST-007", "2026-08-25", "2026-08-26", 18500.0, 18500.0, "Settled", "Windshield", "Cracked front windshield caused by flying road stone on highway."),
        ("CLM-2026-9930", "POL-2026-6614", "CUST-006", "2026-09-15", "2026-09-16", 52000.0, 0.0, "Under-Review", "Accidental", "Rear bumper dent and tailgate damage caused by following vehicle."),
        ("CLM-2026-1104", "POL-2026-3342", "CUST-003", "2026-07-20", "2026-07-22", 12000.0, 0.0, "Rejected", "Accidental", "Driver license was expired at time of accident.")
    ]
    cursor.executemany("INSERT INTO claims (claim_number, policy_number, customer_id, incident_date, filing_date, claim_amount, approved_amount, status, claim_type, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);", claims)

    print("Inserting claim documents...")
    docs = [
        ("CLM-2026-4401", "Damage Photos", "front_bumper_damage.jpg", "Verified"),
        ("CLM-2026-4401", "Driving License", "rohit_dl.pdf", "Verified"),
        ("CLM-2026-4401", "Repair Estimate", "hyundai_mumbai_estimate.pdf", "Verified"),
        ("CLM-2026-7729", "Damage Photos", "door_scrape.jpg", "Verified"),
        ("CLM-2026-7729", "Repair Estimate", "pending_garage_quote.pdf", "Pending"),
        ("CLM-2026-9930", "RC Book", "honda_city_rc.pdf", "Verified"),
        ("CLM-2026-9930", "FIR Copy / Spot Intimation", "police_diary_entry.pdf", "Verified")
    ]
    cursor.executemany("INSERT INTO claim_documents (claim_number, document_type, document_name, status) VALUES (?, ?, ?, ?);", docs)

    print("Inserting payments...")
    payments = [
        ("PAY-99101", "POL-2026-8810", "CUST-001", 24500.0, "2026-01-15", "UPI", "Success"),
        ("PAY-99102", "POL-2026-9921", "CUST-002", 19800.0, "2026-03-01", "NetBanking", "Success"),
        ("PAY-99103", "POL-2026-7751", "CUST-004", 28000.0, "2026-02-20", "CreditCard", "Success"),
        ("PAY-99104", "POL-2026-6614", "CUST-006", 16800.0, "2026-04-12", "UPI", "Success")
    ]
    cursor.executemany("INSERT INTO payments (payment_id, policy_number, customer_id, amount, payment_date, payment_method, status) VALUES (?, ?, ?, ?, ?, ?, ?);", payments)

    print("Inserting renewals...")
    renewals = [
        ("POL-2026-3342", "CUST-003", "2026-10-09", 13500.0, "Due", 1),
        ("POL-2026-5590", "CUST-005", "2026-08-31", 29800.0, "Overdue", 2),
        ("POL-2026-9944", "CUST-010", "2026-11-19", 7400.0, "Eligible", 0)
    ]
    cursor.executemany("INSERT INTO renewals (policy_number, customer_id, expiry_date, renewal_quote, status, notice_sent) VALUES (?, ?, ?, ?, ?, ?);", renewals)

    print("Inserting network garages...")
    garages = [
        ("Shree Auto Care Center", "Mumbai", "Andheri East, Saki Naka Junction", "+91-22-28501122", 1, "Hyundai,Maruti Suzuki,Tata,Honda"),
        ("Apex Motors Workshop", "Bengaluru", "Koramangala 4th Block, 80ft Road", "+91-80-41223344", 1, "Tata,Mahindra,Hyundai,Kia"),
        ("Capital Express Garage", "Delhi", "Okhla Industrial Area Phase 2", "+91-11-46556677", 1, "Maruti Suzuki,Hyundai,Toyota,Volkswagen"),
        ("Deccan Auto Works", "Pune", "Senapati Bapat Road, Shivaji Nagar", "+91-20-25667788", 1, "Honda,Maruti Suzuki,Tata,Hyundai"),
        ("CyberCity Auto Hub", "Hyderabad", "Hitec City, Madhapur Main Road", "+91-40-66778899", 1, "Kia,Mahindra,Hyundai,Toyota")
    ]
    cursor.executemany("INSERT INTO network_garages (garage_name, city, address, phone, cashless_supported, supported_brands) VALUES (?, ?, ?, ?, ?, ?);", garages)

    print("Inserting support tickets...")
    tickets = [
        ("TCK-1001", "CUST-004", "POL-2026-7751", "CLM-2026-7729", "Claims", "High", "Delay in Repair Estimate Submission", "In-Progress", "Claims Desk"),
        ("TCK-1002", "CUST-003", "POL-2026-3342", None, "Renewal", "Medium", "Inquiry on NCB discount for renewal quote", "Open", "Underwriting")
    ]
    cursor.executemany("INSERT INTO support_tickets (ticket_id, customer_id, policy_number, claim_number, category, priority, subject, status, assigned_team) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);", tickets)

    conn.commit()
    conn.close()
    print("✅ Database initialized and seeded successfully with synthetic data!")

if __name__ == "__main__":
    init_and_seed()
