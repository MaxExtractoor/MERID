"""
Kalshi Live Trade Script — BTC 15m Market
==========================================
⚠️  PRODUCTION HARDENING: THIS SCRIPT IS DISABLED  ⚠️

This script contains a DIRECT HTTP BYPASS to Kalshi API that circumvents the
canonical order_router and ALL risk guards (GlobalRiskGuard 1-2% cap, Top-3 batch
gate, PreTradeGate, execution gate, kill switches).

To enable this bypass (NOT RECOMMENDED): set MERID_ALLOW_LIVE_TRADE_BYPASS=1
See: kalshi_live_trade.py.DISABLED for full documentation.

If you need live trading, use the canonical path:
  - POST /api/v1/kalshi/orders (web API) -> order_router -> risk guards -> venue
  - KalshiContinuousTrader with proper strategy configuration
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════
# PRODUCTION HARDENING — CRITICAL BYPASS DISABLED
# ═══════════════════════════════════════════════════════════════════════════
import os
if os.getenv("MERID_ALLOW_LIVE_TRADE_BYPASS", "").lower() not in ("1", "true", "yes"):
    raise RuntimeError(
        "[PRODUCTION HARDENING] kalshi_live_trade.py is DISABLED. "
        "This script contains a direct HTTP bypass that circumvents all risk guards. "
        "Use the canonical path: POST /api/v1/kalshi/orders or KalshiContinuousTrader. "
        "To bypass (NOT RECOMMENDED): MERID_ALLOW_LIVE_TRADE_BYPASS=1"
    )
# ═══════════════════════════════════════════════════════════════════════════

import argparse
import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ── Load credentials ─────────────────────────────────────────────────────

def _load_env():
    """Load .env file into os.environ."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key not in os.environ:  # Don't override explicit env
                    os.environ[key] = val

_load_env()

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
API_KEY_ID = os.environ.get("KALSHI_API_KEY_ID", "")
PRIVATE_KEY_PATH = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "kalshi_private_key.pem")

# Resolve relative key path from project root
_key_file = Path(PRIVATE_KEY_PATH)
if not _key_file.is_absolute():
    _key_file = Path(__file__).resolve().parent.parent / _key_file

if not _key_file.exists():
    print(f"ERROR: RSA private key not found at {_key_file}")
    sys.exit(1)

_private_key = serialization.load_pem_private_key(
    _key_file.read_bytes(), password=None
)
print(f"✓ RSA key loaded from {_key_file.name}")
print(f"✓ API Key ID: {API_KEY_ID[:8]}...{API_KEY_ID[-4:]}")
print(f"✓ Base URL: {BASE_URL}")
print()


# ── Auth helpers (matching Kalshi docs exactly) ───────────────────────────

def _sign(method: str, path: str) -> dict:
    """Generate Kalshi RSA-PSS auth headers.

    Signs: timestamp_ms + METHOD + full_path (no body).
    The full path MUST include the /trade-api/v2 prefix.
    """
    ts_ms = str(int(time.time() * 1000))
    full_path = "/trade-api/v2" + path
    message = ts_ms + method.upper() + full_path
    signature = _private_key.sign(
        message.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": API_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        "Content-Type": "application/json",
    }


def get(path: str, params: dict | None = None) -> requests.Response:
    """Authenticated GET request."""
    url = BASE_URL + path
    headers = _sign("GET", path)
    return requests.get(url, headers=headers, params=params, timeout=15)


def post(path: str, data: dict) -> requests.Response:
    """Authenticated POST request."""
    url = BASE_URL + path
    headers = _sign("POST", path)
    return requests.post(url, headers=headers, json=data, timeout=15)


def delete(path: str) -> requests.Response:
    """Authenticated DELETE request."""
    url = BASE_URL + path
    headers = _sign("DELETE", path)
    return requests.delete(url, headers=headers, timeout=15)


# ── Commands ──────────────────────────────────────────────────────────────

def cmd_balance():
    """Check account balance."""
    print("═══ Account Balance ═══")
    resp = get("/portfolio/balance")
    if resp.status_code == 200:
        bal = resp.json()
        print(json.dumps(bal, indent=2))
    else:
        print(f"ERROR {resp.status_code}: {resp.text}")


def cmd_discover():
    """Find open BTC 15-minute markets."""
    print("═══ Discovering BTC Markets ═══")

    # Fetch open BTC markets using series_ticker filter
    # Kalshi BTC crypto markets use series like KXBTCD (daily), KXBTC (range)
    btc_prefixes = ["KXBTCD", "KXBTC", "KXBTCW"]
    markets = []
    for prefix in btc_prefixes:
        resp = requests.get(
            f"{BASE_URL}/markets",
            params={
                "limit": 50,
                "status": "open",
                "series_ticker": prefix,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            batch = resp.json().get("markets", [])
            markets.extend(batch)
            if batch:
                print(f"  Found {len(batch)} markets with series_ticker={prefix}")

    if not markets:
        print("No BTC markets via series_ticker. Trying event_ticker search...")
        # Try fetching events first
        resp = requests.get(
            f"{BASE_URL}/events",
            params={"limit": 50, "status": "open", "series_ticker": "KXBTCD"},
            timeout=15,
        )
        if resp.status_code == 200:
            events = resp.json().get("events", [])
            for ev in events[:5]:
                print(f"  Event: {ev.get('event_ticker', '?')} — {ev.get('title', '?')}")
                ev_resp = requests.get(
                    f"{BASE_URL}/markets",
                    params={"limit": 20, "status": "open", "event_ticker": ev["event_ticker"]},
                    timeout=15,
                )
                if ev_resp.status_code == 200:
                    markets.extend(ev_resp.json().get("markets", []))

    if not markets:
        print("Still no BTC markets. Trying broad keyword search...")
        resp = requests.get(
            f"{BASE_URL}/markets",
            params={"limit": 200, "status": "open"},
            timeout=15,
        )
        if resp.status_code == 200:
            markets = [
                m for m in resp.json().get("markets", [])
                if "btc" in m.get("ticker", "").lower()
                or "bitcoin" in m.get("title", "").lower()
                or "KXBTC" in m.get("ticker", "").upper()
            ]

    if not markets:
        print("No BTC markets found at all.")
        return

    # Sort by strike proximity to spot (~$70,500)
    import re
    SPOT = 70500
    def _strike(m):
        match = re.search(r"-T(\d+(?:\.\d+)?)$", m.get("ticker", ""))
        return float(match.group(1)) if match else 999999
    markets.sort(key=lambda m: abs(_strike(m) - SPOT))

    print(f"\nFound {len(markets)} BTC market(s) (sorted by proximity to spot ~${SPOT:,}):\n")
    for i, m in enumerate(markets[:20]):
        ticker = m.get("ticker", "")
        title = m.get("title", m.get("subtitle", ""))
        yes_bid = m.get("yes_bid", "?")
        yes_ask = m.get("yes_ask", "?")
        no_bid = m.get("no_bid", "?")
        no_ask = m.get("no_ask", "?")
        volume = m.get("volume", 0)
        oi = m.get("open_interest", 0)
        close_time = m.get("close_time", m.get("expiration_time", "?"))

        print(f"  [{i+1}] {ticker}")
        print(f"      Title: {title}")
        print(f"      YES bid/ask: {yes_bid}¢ / {yes_ask}¢")
        print(f"      NO  bid/ask: {no_bid}¢ / {no_ask}¢")
        print(f"      Volume: {volume}  |  OI: {oi}")
        print(f"      Closes: {close_time}")
        print()

    # Also get the orderbook for the first market
    if markets:
        first_ticker = markets[0]["ticker"]
        print(f"═══ Orderbook: {first_ticker} ═══")
        ob_resp = requests.get(
            f"{BASE_URL}/markets/{first_ticker}/orderbook",
            params={"depth": 5},
            timeout=15,
        )
        if ob_resp.status_code == 200:
            ob = ob_resp.json().get("orderbook", ob_resp.json())
            print(json.dumps(ob, indent=2))
        else:
            print(f"Orderbook fetch failed: {ob_resp.status_code}")


def cmd_buy(ticker: str, side: str, price_cents: int, count: int, auto_confirm: bool = False):
    """Place a live BUY order.

    Args:
        ticker: Market ticker (e.g. KXBTCD-26MAR2003-T79299.99)
        side: "yes" or "no"
        price_cents: Limit price in cents (1-99)
        count: Number of contracts
        auto_confirm: Skip interactive confirmation
    """
    print("═══ PLACING LIVE ORDER ═══")
    print(f"  Ticker:  {ticker}")
    print(f"  Side:    {side}")
    print(f"  Action:  buy")
    print(f"  Price:   {price_cents}¢")
    print(f"  Count:   {count}")
    print(f"  Max cost: ${count * price_cents / 100:.2f}")
    print()

    if price_cents < 1 or price_cents > 99:
        print("ERROR: Price must be 1-99 cents")
        return

    client_order_id = str(uuid.uuid4())

    order_data = {
        "ticker": ticker,
        "action": "buy",
        "side": side,
        "count": count,
        "type": "limit",
        f"{side}_price": price_cents,
        "client_order_id": client_order_id,
    }

    print(f"  Client Order ID: {client_order_id}")
    print(f"  Payload: {json.dumps(order_data)}")
    print()

    # Confirm with user
    if not auto_confirm:
        confirm = input("  ⚠️  CONFIRM LIVE ORDER? (type 'yes' to proceed): ").strip().lower()
        if confirm != "yes":
            print("  CANCELLED — no order placed.")
            return
    else:
        print("  ⚠️  Auto-confirmed via --confirm flag")

    resp = post("/portfolio/orders", order_data)

    if resp.status_code == 201:
        order = resp.json().get("order", resp.json())
        print()
        print("  ✅ ORDER PLACED SUCCESSFULLY!")
        print(f"  Order ID:        {order.get('order_id', '?')}")
        print(f"  Client Order ID: {client_order_id}")
        print(f"  Status:          {order.get('status', '?')}")
        print(f"  Remaining:       {order.get('remaining_count', '?')}")
        print()
        print("  Full response:")
        print(json.dumps(order, indent=2))
    else:
        print()
        print(f"  ❌ ORDER FAILED: {resp.status_code}")
        print(f"  {resp.text}")


def cmd_status(order_id: str):
    """Check order status."""
    print(f"═══ Order Status: {order_id} ═══")
    resp = get(f"/portfolio/orders/{order_id}")
    if resp.status_code == 200:
        order = resp.json().get("order", resp.json())
        print(json.dumps(order, indent=2))
    else:
        print(f"ERROR {resp.status_code}: {resp.text}")


def cmd_cancel(order_id: str):
    """Cancel an order."""
    print(f"═══ Cancelling Order: {order_id} ═══")
    confirm = input("  ⚠️  CONFIRM CANCEL? (type 'yes' to proceed): ").strip().lower()
    if confirm != "yes":
        print("  CANCELLED — order not cancelled.")
        return

    resp = delete(f"/portfolio/orders/{order_id}")
    if resp.status_code in (200, 204):
        print("  ✅ Order cancelled successfully.")
    else:
        print(f"  ❌ Cancel failed: {resp.status_code} - {resp.text}")


def cmd_positions():
    """List current positions."""
    print("═══ Current Positions ═══")
    resp = get("/portfolio/positions")
    if resp.status_code == 200:
        data = resp.json()
        positions = data.get("market_positions", data.get("positions", []))
        if not positions:
            print("  No open positions.")
        else:
            for p in positions:
                print(json.dumps(p, indent=2))
    else:
        print(f"ERROR {resp.status_code}: {resp.text}")


def cmd_orders():
    """List open orders."""
    print("═══ Open Orders ═══")
    resp = get("/portfolio/orders", params={"status": "resting"})
    if resp.status_code == 200:
        data = resp.json()
        orders = data.get("orders", [])
        if not orders:
            print("  No resting orders.")
        else:
            for o in orders:
                print(f"  {o.get('order_id','?')} | {o.get('ticker','?')} | "
                      f"{o.get('side','?')} {o.get('action','?')} {o.get('remaining_count','?')}x "
                      f"@ {o.get('yes_price', o.get('no_price','?'))}¢ | {o.get('status','?')}")
    else:
        print(f"ERROR {resp.status_code}: {resp.text}")


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Kalshi Live Trade — BTC 15m")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("discover", help="Find open BTC markets")
    sub.add_parser("balance", help="Check account balance")
    sub.add_parser("positions", help="List current positions")
    sub.add_parser("orders", help="List open orders")

    buy_p = sub.add_parser("buy", help="Place a live BUY order")
    buy_p.add_argument("--ticker", required=True, help="Market ticker")
    buy_p.add_argument("--side", required=True, choices=["yes", "no"], help="yes or no")
    buy_p.add_argument("--price", required=True, type=int, help="Limit price in cents (1-99)")
    buy_p.add_argument("--count", type=int, default=1, help="Number of contracts (default: 1)")
    buy_p.add_argument("--confirm", action="store_true", help="Skip interactive confirmation")

    stat_p = sub.add_parser("status", help="Check order status")
    stat_p.add_argument("--order-id", required=True, help="Order ID")

    cancel_p = sub.add_parser("cancel", help="Cancel an order")
    cancel_p.add_argument("--order-id", required=True, help="Order ID")

    args = parser.parse_args()

    if args.command == "discover":
        cmd_discover()
    elif args.command == "balance":
        cmd_balance()
    elif args.command == "positions":
        cmd_positions()
    elif args.command == "orders":
        cmd_orders()
    elif args.command == "buy":
        cmd_buy(args.ticker, args.side, args.price, args.count, auto_confirm=args.confirm)
    elif args.command == "status":
        cmd_status(args.order_id)
    elif args.command == "cancel":
        cmd_cancel(args.order_id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
