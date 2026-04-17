#!/usr/bin/env python3
"""Force-align MERID paper state from a venue snapshot (default Kalshi).

Use when reconciliation discrepancies block the execution gate in paper mode.
This script lives under ``scripts/`` so it is tracked; root ``fix_*.py`` files
are gitignored as scratch helpers.

Usage:
    python scripts/kalshi_force_align_paper.py
    python scripts/kalshi_force_align_paper.py --venue kalshi
"""

from __future__ import annotations

import argparse
import os
import sys

# Repo root on sys.path (same pattern as scripts/run_reconciliation.py)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--venue",
        default="kalshi",
        help="Venue name passed to force_align_from_venue (default: kalshi)",
    )
    parser.add_argument(
        "--user-id",
        default="operator",
        help="User id for alignment bookkeeping (default: operator)",
    )
    args = parser.parse_args()

    print(f"Force-align from venue={args.venue!r} (paper)...")

    try:
        from merid.reconciliation import (
            force_align_from_venue,
            get_reconciliation_status,
        )

        result = force_align_from_venue(args.venue, user_id=args.user_id)
        if result.get("error"):
            print(f"Force alignment failed: {result['error']}")
            return 1
        print("Force alignment completed.")
        print(f"Result: {result}")

        status = get_reconciliation_status()
        print(f"Reconciliation status: {status}")
        return 0

    except ImportError as e:
        print(f"Import error: {e}")
        print("Trying alternative reset...")
        try:
            from core.reconciliation import reset_reconciliation_state

            reset_reconciliation_state()
            print("Reconciliation state reset.")
            return 0
        except ImportError as e2:
            print(f"Alternative import failed: {e2}")
            return 1

    except Exception as e:
        print(f"Error during alignment: {e}")
        print("This may be expected in paper mode with no positions.")
        return 1

    finally:
        print("\nYou can restart the MERID loop, for example:")
        print("  python -m merid.loop --execute")


if __name__ == "__main__":
    raise SystemExit(main())
