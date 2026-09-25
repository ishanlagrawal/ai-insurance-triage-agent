#!/usr/bin/env python3
"""
Unified Golden Test Suite Runner for AI Insurance Inbox Triage Agent.
Executes synthetic email scenarios against the classification, routing,
and guardrail engine, verifying response quality, accuracy, and latency.
"""

import sys
import os
import json
import time

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.run_synthetic_test_suite import run_suite

def main():
    print("=================================================================")
    print("   AI INSURANCE INBOX TRIAGE AGENT - GOLDEN TEST SUITE RUNNER")
    print("=================================================================\n")
    
    start_time = time.time()
    try:
        report = run_suite()
        elapsed = time.time() - start_time
        print(f"\n=================================================================")
        print(f"✅ Benchmark Complete in {elapsed:.2f}s")
        print("=================================================================")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Benchmark Failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
