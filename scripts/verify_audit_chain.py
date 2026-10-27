#!/usr/bin/env python3
"""CLI tool to verify tamper-evident audit chain integrity.

Usage:
    python scripts/verify_audit_chain.py
    python scripts/verify_audit_chain.py --export-bundle 100 200
    python scripts/verify_audit_chain.py --latest-hash
    python scripts/verify_audit_chain.py --show-events

Exit codes:
    0 - Chain valid
    1 - Chain broken or verification failed
    2 - Usage error
"""

import argparse
import json
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.risk_audit_chain import verify_audit_chain, get_risk_audit_chain


def main():
    parser = argparse.ArgumentParser(
        description="Verify tamper-evident risk audit chain"
    )
    parser.add_argument(
        "--log-path",
        help="Path to audit log file (default: data/risk_audit_chain.jsonl)"
    )
    parser.add_argument(
        "--export-bundle",
        nargs=2,
        type=int,
        metavar=("START", "END"),
        help="Export proof bundle for sequence range"
    )
    parser.add_argument(
        "--latest-hash",
        action="store_true",
        help="Print latest chain hash"
    )
    parser.add_argument(
        "--show-events",
        action="store_true",
        help="Show all events in chain"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format"
    )
    
    args = parser.parse_args()
    
    # Handle export bundle
    if args.export_bundle:
        start, end = args.export_bundle
        chain = get_risk_audit_chain(args.log_path)
        bundle = chain.export_proof_bundle(start, end)
        
        if args.json:
            print(json.dumps({
                "start_sequence": start,
                "end_sequence": end,
                "record_count": len(bundle),
                "records": bundle
            }, indent=2))
        else:
            print(f"=== Proof Bundle (sequences {start}-{end}) ===")
            print(f"Records: {len(bundle)}")
            for rec in bundle:
                print(f"\n[{rec['sequence']}] {rec['timestamp']}")
                print(f"  Event: {rec['event_type']}")
                print(f"  Hash: {rec['event_hash'][:32]}...")
                print(f"  Prev: {rec['prev_hash'][:32] if rec['prev_hash'] != 'GENESIS' else 'GENESIS'}...")
        return 0
    
    # Handle latest hash
    if args.latest_hash:
        chain = get_risk_audit_chain(args.log_path)
        latest = chain.get_latest_hash()
        seq = chain.get_sequence()
        
        if args.json:
            print(json.dumps({
                "latest_hash": latest,
                "sequence": seq
            }))
        else:
            print(f"Latest hash (sequence {seq}):")
            print(latest)
        return 0
    
    # Handle show events
    if args.show_events:
        chain = get_risk_audit_chain(args.log_path)
        bundle = chain.export_proof_bundle()
        
        if args.json:
            print(json.dumps({
                "record_count": len(bundle),
                "records": bundle
            }, indent=2))
        else:
            print(f"=== All Audit Events ({len(bundle)} records) ===")
            for rec in bundle:
                payload_preview = str(rec['payload'])[:60] + "..." if len(str(rec['payload'])) > 60 else str(rec['payload'])
                print(f"\n[{rec['sequence']:4d}] {rec['timestamp']}")
                print(f"       Event: {rec['event_type']}")
                print(f"       Payload: {payload_preview}")
                print(f"       Hash: {rec['event_hash'][:40]}...")
        return 0
    
    # Default: verify chain
    result = verify_audit_chain(args.log_path)
    
    if args.json:
        output = {
            "valid": result.valid,
            "records_checked": result.records_checked,
        }
        if not result.valid:
            output["broken_at"] = result.broken_at
            output["expected_hash"] = result.expected_hash
            output["actual_hash"] = result.actual_hash
        print(json.dumps(output, indent=2))
    else:
        print("=== Risk Audit Chain Verification ===")
        print(f"Records checked: {result.records_checked}")
        
        if result.valid:
            print("\n✓ Chain integrity: VALID")
            print(f"  All {result.records_checked} records verified")
            print(f"  Latest hash: {get_risk_audit_chain(args.log_path).get_latest_hash()[:40]}...")
        else:
            print("\n✗ Chain integrity: BROKEN")
            print(f"  Break at sequence: {result.broken_at}")
            print(f"  Expected: {result.expected_hash}")
            print(f"  Actual:   {result.actual_hash}")
    
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
