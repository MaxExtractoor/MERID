"""
Audit Trail Soak Test — verifies chain integrity under sustained load.

Simulates a production-like workload by appending thousands of entries
over a configurable duration, then verifies the full hash chain.

Usage:
    python scripts/audit_trail_soak.py                  # 5-minute soak
    python scripts/audit_trail_soak.py --duration 3600  # 1-hour soak
    python scripts/audit_trail_soak.py --entries 10000  # fixed entry count
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.audit_trail import AuditTrail, AuditEntry
from core.streaming_bus import StreamEvent, EventChannel


def _banner(msg: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {msg}", flush=True)
    print(f"{'=' * 60}\n")


async def run_soak(duration_seconds: float, target_entries: int, storage_dir: str) -> dict:
    """Run the soak test, returning a results dict."""
    trail = AuditTrail(storage_path=storage_dir)

    _banner(f"Audit Trail Soak Test - {duration_seconds}s / {target_entries} entries")

    start = time.time()
    count = 0
    errors = []

    while True:
        elapsed = time.time() - start
        if duration_seconds and elapsed >= duration_seconds:
            break
        if target_entries and count >= target_entries:
            break

        # Simulate a realistic event
        event = StreamEvent(
            channel=EventChannel.EXECUTION,
            event_type="order_submitted",
            source=f"agent-{count % 5}",
            data={
                "order_id": f"ORD-{count:06d}",
                "symbol": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AAPL", "KXBTCD"][count % 5],
                "side": "buy" if count % 2 == 0 else "sell",
                "quantity": round(0.01 + (count % 100) * 0.001, 4),
                "price": round(50000 + (count % 1000), 2),
                "venue": ["binanceus", "coinbase", "alpaca", "kalshi"][count % 4],
            },
            timestamp=time.time(),
        )

        try:
            await trail._record_event(event)
            count += 1
        except Exception as exc:
            errors.append({"entry": count, "error": str(exc)})

        # Progress every 1000 entries
        if count % 1000 == 0 and count > 0:
            rate = count / (time.time() - start)
            print(f"  [{count:>7} entries] {rate:.0f} entries/sec  chain_len={len(trail.entries)}")

        # Small yield to simulate realistic pacing
        if count % 100 == 0:
            await asyncio.sleep(0.001)

    elapsed = time.time() - start
    rate = count / elapsed if elapsed > 0 else 0

    print(f"\n  Entries written: {count}")
    print(f"  Duration: {elapsed:.1f}s")
    print(f"  Rate: {rate:.0f} entries/sec")
    print(f"  Errors during write: {len(errors)}")

    # Verify chain integrity
    _banner("Verifying Hash Chain Integrity")
    verify_start = time.time()
    chain_valid = trail.verify_chain()
    verify_time = time.time() - verify_start
    print(f"  Chain valid: {chain_valid}")
    print(f"  Verification time: {verify_time:.2f}s")
    print(f"  Entries verified: {len(trail.entries)}")

    # Verify order index
    indexed_orders = len(trail._order_index)
    print(f"  Order index entries: {indexed_orders}")

    # Verify persistence - reload from disk
    _banner("Verifying Persistence (reload from disk)")
    trail2 = AuditTrail(storage_path=storage_dir)
    reload_valid = trail2.verify_chain()
    reload_count = len(trail2.entries)
    print(f"  Reloaded entries: {reload_count}")
    print(f"  Reloaded chain valid: {reload_valid}")
    print(f"  Entries match: {reload_count == count}")

    results = {
        "entries_written": count,
        "duration_seconds": round(elapsed, 2),
        "rate_per_second": round(rate, 1),
        "write_errors": len(errors),
        "chain_valid": chain_valid,
        "verify_time_seconds": round(verify_time, 3),
        "reload_valid": reload_valid,
        "reload_count_matches": reload_count == count,
        "order_index_count": indexed_orders,
        "passed": chain_valid and reload_valid and reload_count == count and len(errors) == 0,
    }

    _banner("RESULT: " + ("PASS [OK]" if results["passed"] else "FAIL [ERROR]"))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Trail Soak Test")
    parser.add_argument("--duration", type=float, default=300, help="Soak duration in seconds (default: 300)")
    parser.add_argument("--entries", type=int, default=0, help="Target entry count (0 = use duration)")
    parser.add_argument("--output", type=str, default="", help="JSON output file path")
    parser.add_argument("--keep", action="store_true", help="Keep temp storage dir after test")
    args = parser.parse_args()

    storage_dir = tempfile.mkdtemp(prefix="merid_audit_soak_")
    print(f"Storage dir: {storage_dir}")

    try:
        results = asyncio.run(run_soak(
            duration_seconds=args.duration if args.entries == 0 else 0,
            target_entries=args.entries if args.entries > 0 else 0,
            storage_dir=storage_dir,
        ))

        if args.output:
            with open(args.output, "w") as f:
                json.dump(results, f, indent=2)
            print(f"\nResults written to {args.output}")

        sys.exit(0 if results["passed"] else 1)
    finally:
        if not args.keep:
            shutil.rmtree(storage_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
