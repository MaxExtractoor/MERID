#!/usr/bin/env python3
"""
Verification script for KalshiSettlementPoller live status.

This script demonstrates how to verify that the settlement poller is:
1. Configured and running
2. Actively polling (poll_count increases over time)
3. Processing settlements (settlement_count increases when markets settle)

Usage:
    python scripts/verify_settlement_poller.py [--host HOST] [--port PORT] [--watch]

Examples:
    # Single check
    python scripts/verify_settlement_poller.py

    # Watch mode - check every 10 seconds
    python scripts/verify_settlement_poller.py --watch

    # Check remote server
    python scripts/verify_settlement_poller.py --host production.example.com --port 8000
"""

import argparse
import json
import sys
import time
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: requests library not found. Install with: pip install requests")
    sys.exit(1)


def check_settlement_poller(
    host: str = "localhost",
    port: int = 8000,
    verbose: bool = True
) -> Optional[dict]:
    """Check settlement poller status via health endpoint.

    Args:
        host: Server hostname
        port: Server port
        verbose: Print detailed output

    Returns:
        Status dict if successful, None if request failed
    """
    url = f"http://{host}:{port}/health/settlement_poller"

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        if verbose:
            print(f"\n{'='*60}")
            print(f"Settlement Poller Status - {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}")
            print(f"Status:           {data.get('status')}")
            print(f"Health:           {data.get('health')}")
            print(f"Running:          {data.get('running')}")
            print(f"Poll Count:       {data.get('poll_count')}")
            print(f"Settlements:      {data.get('settlement_count')}")
            print(f"Last Cursor:      {data.get('last_cursor') or 'None'}")
            print(f"Seen IDs:         {data.get('seen_ids_count')}")
            print(f"Cursor History:   {data.get('cursor_history_len')}")

            if data.get('error'):
                print(f"\nError: {data.get('error')}")

            print(f"{'='*60}\n")

        return data

    except requests.exceptions.RequestException as e:
        if verbose:
            print(f"\nERROR: Failed to connect to {url}")
            print(f"Details: {e}\n")
        return None


def check_global_health(
    host: str = "localhost",
    port: int = 8000,
    verbose: bool = True
) -> Optional[dict]:
    """Check global health including settlement poller.

    Args:
        host: Server hostname
        port: Server port
        verbose: Print detailed output

    Returns:
        Health dict if successful, None if request failed
    """
    url = f"http://{host}:{port}/api/health"

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        if verbose:
            settlement_check = data.get('checks', {}).get('settlement_poller', {})
            print(f"\nGlobal Health Check:")
            print(f"  Overall Status:        {data.get('status')}")
            print(f"  Settlement Poller:")
            print(f"    Status:              {settlement_check.get('status')}")
            print(f"    Running:             {settlement_check.get('running')}")
            print(f"    Poll Count:          {settlement_check.get('poll_count')}")
            print(f"    Settlement Count:    {settlement_check.get('settlement_count')}")

        return data

    except requests.exceptions.RequestException as e:
        if verbose:
            print(f"\nERROR: Failed to connect to {url}")
            print(f"Details: {e}\n")
        return None


def watch_settlement_poller(
    host: str = "localhost",
    port: int = 8000,
    interval: int = 10
):
    """Continuously monitor settlement poller status.

    Args:
        host: Server hostname
        port: Server port
        interval: Seconds between checks
    """
    print(f"Watching settlement poller status (checking every {interval}s)")
    print("Press Ctrl+C to stop\n")

    prev_poll_count = None
    prev_settlement_count = None

    try:
        while True:
            data = check_settlement_poller(host, port, verbose=False)

            if data:
                status = data.get('status')
                running = data.get('running')
                poll_count = data.get('poll_count')
                settlement_count = data.get('settlement_count')

                # Calculate deltas
                poll_delta = ""
                if prev_poll_count is not None and poll_count > prev_poll_count:
                    poll_delta = f" (+{poll_count - prev_poll_count})"

                settlement_delta = ""
                if prev_settlement_count is not None and settlement_count > prev_settlement_count:
                    settlement_delta = f" (+{settlement_count - prev_settlement_count})"

                # Print status line
                timestamp = time.strftime('%H:%M:%S')
                icon = "✓" if running else "✗"
                print(f"[{timestamp}] {icon} Status: {status:15} | Polls: {poll_count:4}{poll_delta:8} | Settlements: {settlement_count:4}{settlement_delta:8}")

                prev_poll_count = poll_count
                prev_settlement_count = settlement_count
            else:
                timestamp = time.strftime('%H:%M:%S')
                print(f"[{timestamp}] ✗ Connection failed")

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\nStopped monitoring.")


def main():
    parser = argparse.ArgumentParser(
        description="Verify KalshiSettlementPoller live status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Server hostname (default: localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Server port (default: 8000)"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch mode - continuously check status every 10 seconds"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Watch mode interval in seconds (default: 10)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON"
    )

    args = parser.parse_args()

    if args.watch:
        watch_settlement_poller(args.host, args.port, args.interval)
    else:
        # Single check
        data = check_settlement_poller(args.host, args.port, verbose=not args.json)

        if args.json and data:
            print(json.dumps(data, indent=2))

        # Also check global health
        if not args.json:
            check_global_health(args.host, args.port, verbose=True)

        # Exit with appropriate code
        if data and data.get('running'):
            sys.exit(0)
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
