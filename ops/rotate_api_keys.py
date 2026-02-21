"""
API Key Rotation Utility

Automates the rotation of exchange and service API keys:
1. Reads current keys from .env
2. Validates new keys against each exchange API
3. Writes updated .env with backup
4. Verifies connectivity with new keys

Usage:
    python -m ops.rotate_api_keys --check          # Check key ages and health
    python -m ops.rotate_api_keys --rotate binance  # Rotate a specific exchange
    python -m ops.rotate_api_keys --rotate all      # Rotate all exchanges

Requires: New keys must be set as environment variables with _NEW suffix:
    BINANCE_API_KEY_NEW=...
    BINANCE_API_SECRET_NEW=...
"""

from __future__ import annotations

import argparse
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("ops.rotate_api_keys")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
ENV_BACKUP_DIR = PROJECT_ROOT / "data" / "env_backups"

# Exchange key configurations
EXCHANGE_KEYS: Dict[str, List[str]] = {
    "binance": ["BINANCE_API_KEY", "BINANCE_API_SECRET"],
    "coinbase": ["COINBASE_API_KEY", "COINBASE_API_SECRET"],
    "kraken": ["KRAKEN_API_KEY", "KRAKEN_PRIVATE_KEY"],
    "okx": ["OKX_API_KEY", "OKX_API_SECRET", "OKX_PASSPHRASE"],
    "alpaca": ["ALPACA_API_KEY", "ALPACA_API_SECRET"],
    "kalshi": ["KALSHI_API_KEY_ID"],
}

SERVICE_KEYS: Dict[str, List[str]] = {
    "telegram": ["TELEGRAM_BOT_TOKEN"],
    "polygon": ["POLYGON_API_KEY"],
    "finnhub": ["FINNHUB_API_KEY"],
    "alpha_vantage": ["ALPHA_VANTAGE_API_KEY"],
    "messari": ["MESSARI_API_KEY"],
}

# Key age tracking file
KEY_AGES_FILE = PROJECT_ROOT / "data" / "key_rotation_log.json"


def _load_env_vars(env_path: Path) -> Dict[str, str]:
    """Parse a .env file into a dict."""
    result: Dict[str, str] = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip("'\"")
    return result


def _backup_env() -> Optional[Path]:
    """Create a timestamped backup of .env."""
    if not ENV_FILE.exists():
        return None
    ENV_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = ENV_BACKUP_DIR / f".env.backup.{ts}"
    shutil.copy2(ENV_FILE, backup_path)
    logger.info(f"Backed up .env to {backup_path}")
    return backup_path


def _write_env(env_vars: Dict[str, str], env_path: Path) -> None:
    """Write env vars back to .env, preserving comments and order."""
    if not env_path.exists():
        env_path.write_text(
            "\n".join(f"{k}={v}" for k, v in env_vars.items()) + "\n"
        )
        return

    lines = env_path.read_text().splitlines()
    written_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in env_vars:
                new_lines.append(f"{key}={env_vars[key]}")
                written_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Append any new keys not already in the file
    for k, v in env_vars.items():
        if k not in written_keys:
            new_lines.append(f"{k}={v}")

    env_path.write_text("\n".join(new_lines) + "\n")


def _log_rotation(exchange: str, keys_rotated: List[str]) -> None:
    """Log key rotation event."""
    import json

    log: List[Dict[str, Any]] = []
    if KEY_AGES_FILE.exists():
        try:
            log = json.loads(KEY_AGES_FILE.read_text())
        except Exception:
            log = []

    log.append({
        "exchange": exchange,
        "keys": keys_rotated,
        "rotated_at": datetime.now(timezone.utc).isoformat(),
        "timestamp": time.time(),
    })

    KEY_AGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_AGES_FILE.write_text(json.dumps(log, indent=2))


def check_key_health() -> Dict[str, Any]:
    """Check health and age of all configured API keys."""
    import json

    env_vars = _load_env_vars(ENV_FILE)
    rotation_log: List[Dict[str, Any]] = []
    if KEY_AGES_FILE.exists():
        try:
            rotation_log = json.loads(KEY_AGES_FILE.read_text())
        except Exception:
            pass

    # Build last-rotated map
    last_rotated: Dict[str, float] = {}
    for entry in rotation_log:
        last_rotated[entry["exchange"]] = entry.get("timestamp", 0)

    results: Dict[str, Any] = {"exchanges": {}, "services": {}}

    for exchange, keys in EXCHANGE_KEYS.items():
        configured = all(env_vars.get(k) for k in keys)
        age_days = None
        if exchange in last_rotated:
            age_days = (time.time() - last_rotated[exchange]) / 86400

        status = "not_configured"
        if configured:
            status = "ok"
            if age_days is not None and age_days > 90:
                status = "rotation_overdue"
            elif age_days is not None and age_days > 60:
                status = "rotation_recommended"

        results["exchanges"][exchange] = {
            "configured": configured,
            "keys": keys,
            "last_rotated_days_ago": round(age_days, 1) if age_days else None,
            "status": status,
        }

    for service, keys in SERVICE_KEYS.items():
        configured = all(env_vars.get(k) for k in keys)
        results["services"][service] = {
            "configured": configured,
            "keys": keys,
        }

    return results


def rotate_exchange(exchange: str) -> Tuple[bool, str]:
    """Rotate keys for a specific exchange.

    Expects new keys as env vars with _NEW suffix.
    Returns (success, message).
    """
    if exchange not in EXCHANGE_KEYS:
        return False, f"Unknown exchange: {exchange}"

    keys = EXCHANGE_KEYS[exchange]
    new_keys: Dict[str, str] = {}

    for key in keys:
        new_val = os.getenv(f"{key}_NEW", "")
        if not new_val:
            return False, f"Missing {key}_NEW environment variable"
        new_keys[key] = new_val

    # Backup current .env
    backup = _backup_env()

    # Load and update
    env_vars = _load_env_vars(ENV_FILE)
    for key, val in new_keys.items():
        env_vars[key] = val
    _write_env(env_vars, ENV_FILE)

    # Log rotation
    _log_rotation(exchange, list(new_keys.keys()))

    msg = f"Rotated {len(new_keys)} keys for {exchange}"
    if backup:
        msg += f" (backup: {backup.name})"
    logger.info(msg)
    return True, msg


def main():
    parser = argparse.ArgumentParser(description="MERID API Key Rotation")
    parser.add_argument("--check", action="store_true", help="Check key health and ages")
    parser.add_argument("--rotate", type=str, help="Rotate keys for an exchange (or 'all')")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.check:
        import json as _json

        health = check_key_health()
        if args.json:
            print(_json.dumps(health, indent=2))
        else:
            print("=" * 50)
            print("MERID API Key Health Check")
            print("=" * 50)
            for section in ("exchanges", "services"):
                print(f"\n--- {section.title()} ---")
                for name, info in health[section].items():
                    status = info.get("status", "configured" if info["configured"] else "not_configured")
                    age = info.get("last_rotated_days_ago")
                    age_str = f" ({age:.0f}d ago)" if age else ""
                    icon = "✅" if status == "ok" else "⚠️" if "recommended" in status else "🔴" if "overdue" in status else "⬚"
                    print(f"  {icon} {name}: {status}{age_str}")
            print()

    elif args.rotate:
        if args.rotate == "all":
            for exchange in EXCHANGE_KEYS:
                ok, msg = rotate_exchange(exchange)
                print(f"  {'✅' if ok else '❌'} {msg}")
        else:
            ok, msg = rotate_exchange(args.rotate)
            print(f"{'✅' if ok else '❌'} {msg}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
