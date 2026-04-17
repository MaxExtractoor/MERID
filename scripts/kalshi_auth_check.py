"""Kalshi RSA auth diagnostic script.

Run this to verify your credentials produce a valid 200 response before
attempting any live or paper trading.

Usage:
    python scripts/kalshi_auth_check.py
    python scripts/kalshi_auth_check.py --env live

The script tests:
  1. Key file readable
  2. Key parseable by cryptography
  3. Signing produces a valid base64 signature
  4. GET /portfolio/balance returns 200 (not 401/403)
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from pathlib import Path

# Allow running from project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_env():
    """Load .env via python-dotenv if available."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def check_auth(env: str = "demo") -> bool:
    _load_env()

    if env == "live":
        key_id = os.environ.get("KALSHI_LIVE_API_KEY_ID") or os.environ.get("KALSHI_API_KEY_ID")
        key_path = os.environ.get("KALSHI_LIVE_PRIVATE_KEY_PATH") or os.environ.get("KALSHI_PRIVATE_KEY_PATH")
        base_url = os.environ.get("KALSHI_API_HOST", "https://api.elections.kalshi.com/trade-api/v2")
        if base_url.endswith("/"):
            base_url = base_url.rstrip("/")
    else:
        key_id = os.environ.get("KALSHI_DEMO_API_KEY_ID") or os.environ.get("KALSHI_API_KEY_ID")
        key_path = os.environ.get("KALSHI_DEMO_PRIVATE_KEY_PATH") or os.environ.get("KALSHI_PRIVATE_KEY_PATH")
        base_url = "https://demo-api.kalshi.co/trade-api/v2"

    print(f"\n{'='*60}")
    print(f"Kalshi Auth Check — env={env}")
    print(f"{'='*60}")
    print(f"  Key ID   : {key_id}")
    print(f"  Key path : {key_path}")
    print(f"  Base URL : {base_url}")
    print()

    # ── Step 1: Key file ──────────────────────────────────────────────────
    if not key_id:
        print("FAIL [1/4] No key ID — set KALSHI_API_KEY_ID or KALSHI_LIVE_API_KEY_ID")
        return False
    if not key_path or key_path == "change_me":
        print("FAIL [1/4] No key path — set KALSHI_PRIVATE_KEY_PATH or KALSHI_LIVE_PRIVATE_KEY_PATH")
        return False
    key_file = Path(key_path)
    if not key_file.exists():
        print(f"FAIL [1/4] Key file not found: {key_file}")
        return False
    print(f"  OK   [1/4] Key file exists: {key_file}")

    # ── Step 2: Parse key ─────────────────────────────────────────────────
    try:
        from cryptography.hazmat.primitives import serialization
        with open(key_file, "rb") as f:
            raw = f.read()
        private_key = serialization.load_pem_private_key(raw, password=None)
        key_size = private_key.key_size
        print(f"  OK   [2/4] Key parsed OK (RSA-{key_size})")
        # Detect PKCS#1 vs PKCS#8
        if raw.startswith(b"-----BEGIN RSA PRIVATE KEY-----"):
            print("  INFO [2/4] Key format: PKCS#1 (legacy) — cryptography handles this fine")
        elif raw.startswith(b"-----BEGIN PRIVATE KEY-----"):
            print("  INFO [2/4] Key format: PKCS#8")
    except ImportError:
        print("FAIL [2/4] cryptography package not installed: pip install cryptography")
        return False
    except Exception as exc:
        print(f"FAIL [2/4] Key parse error: {exc}")
        return False

    # ── Step 3: Sign a test message ───────────────────────────────────────
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        ts = str(int(time.time() * 1000))
        path_str = "/trade-api/v2/portfolio/balance"
        message = (ts + "GET" + path_str).encode()
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        sig_b64 = base64.b64encode(signature).decode()
        print(f"  OK   [3/4] Signing works (sig length: {len(sig_b64)} chars)")
    except Exception as exc:
        print(f"FAIL [3/4] Signing error: {exc}")
        return False

    # ── Step 4: HTTP request ──────────────────────────────────────────────
    try:
        import httpx

        headers = {
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "Content-Type": "application/json",
        }
        url = f"{base_url}/portfolio/balance"
        print(f"  INFO [4/4] Sending GET {url}")

        resp = httpx.get(url, headers=headers, timeout=10.0)
        print(f"  INFO [4/4] Response: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            balance = data.get("balance", data)
            print(f"  OK   [4/4] Auth SUCCESS — balance: {balance}")
            return True
        elif resp.status_code == 401:
            body = resp.text[:400]
            print(f"FAIL [4/4] 401 Unauthorized: {body}")
            print()
            print("  Checklist for 401:")
            print("  [ ] Public key uploaded to Kalshi dashboard (API Keys section)")
            print("  [ ] Key ID matches the uploaded key (not a different API key)")
            print("  [ ] Demo key used with demo URL / live key with live URL")
            print("  [ ] System clock within 5s of UTC (check: python -c \"import time; print(time.time())\")")
            return False
        elif resp.status_code == 403:
            print(f"FAIL [4/4] 403 Forbidden: {resp.text[:200]}")
            print("  Key ID may be correct but key is disabled or rate-limited.")
            return False
        else:
            print(f"FAIL [4/4] Unexpected {resp.status_code}: {resp.text[:200]}")
            return False

    except ImportError:
        print("FAIL [4/4] httpx not installed: pip install httpx")
        return False
    except Exception as exc:
        print(f"FAIL [4/4] Request error: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Kalshi auth diagnostic")
    parser.add_argument("--env", choices=["demo", "live"], default="demo",
                        help="Which environment to test (default: demo)")
    args = parser.parse_args()
    ok = check_auth(args.env)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
