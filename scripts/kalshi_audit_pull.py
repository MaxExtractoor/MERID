#!/usr/bin/env python3
"""
Kalshi Audit Pull

Read-only authoritative data pull for trading audit.
Fetches raw Kalshi fill history, portfolio history, open orders, positions,
and balance, plus a snapshot of local config/state, and writes versioned
JSON artifacts.  Does not mutate any trading or risk state.

Usage:
    python scripts/kalshi_audit_pull.py [--output-dir audit_output_<timestamp>]
"""

import argparse
import asyncio
import copy
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
from utils.logger import get_logger

logger = get_logger("scripts.kalshi_audit_pull")

PROJECT_ROOT = Path(__file__).parent.parent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _to_json_safe(obj: Any, _seen: Optional[set] = None) -> Any:
    """Recursively convert to JSON-safe primitives (no Decimal/bytes/circular refs)."""
    from decimal import Decimal
    import dataclasses

    if _seen is None:
        _seen = set()

    obj_id = id(obj)
    if obj_id in _seen:
        return "<circular-ref>"

    if obj is None:
        return None
    if isinstance(obj, (int, float, str, bool)):
        return obj
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (list, tuple)):
        _seen.add(obj_id)
        try:
            return [_to_json_safe(x, _seen) for x in obj]
        finally:
            _seen.discard(obj_id)
    if isinstance(obj, dict):
        _seen.add(obj_id)
        try:
            return {k: _to_json_safe(v, _seen) for k, v in obj.items()}
        finally:
            _seen.discard(obj_id)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        _seen.add(obj_id)
        try:
            return {k: _to_json_safe(v, _seen) for k, v in dataclasses.asdict(obj).items()}
        finally:
            _seen.discard(obj_id)
    # Exceptions / tracebacks: convert to string; never recurse into their internals
    if isinstance(obj, BaseException):
        return str(obj)
    # Unknown objects: use repr as a last resort
    return repr(obj)


def _safe_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_to_json_safe(data), f, indent=2, ensure_ascii=False, default=str)


def _load_text_lines(path: Path, max_lines: int = 200) -> List[str]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [line.rstrip("\n") for line in lines[-max_lines:]]
    except Exception as e:
        return [f"ERROR reading {path}: {e}"]


def _read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"Failed to parse {path}: {e}"}


def _is_non_secret_env(k: str) -> bool:
    lower = k.lower()
    if "key" in lower or "token" in lower or "secret" in lower or "password" in lower or "private" in lower:
        return False
    return True


def _build_snapshot() -> Dict[str, Any]:
    """Capture local server/config state without exposing secrets."""
    snapshot: Dict[str, Any] = {}
    snapshot["snapshot_time"] = _now_iso()

    # Process info
    pid: Optional[int] = None
    for line in _load_text_lines(PROJECT_ROOT / "server.pid", 10):
        try:
            pid = int(line.strip())
            break
        except ValueError:
            pass
    snapshot["server_pid_from_server.pid"] = pid
    snapshot["cwd"] = str(PROJECT_ROOT.resolve())

    # Env names only (no values for sensitive keys)
    env_names: Dict[str, str] = {}
    for k, v in os.environ.items():
        if _is_non_secret_env(k):
            env_names[k] = v
        else:
            env_names[k] = "<redacted>"
    snapshot["environment_variables"] = env_names

    # Config files
    config_paths = {
        "kalshi_crypto_15m_v2_yaml": PROJECT_ROOT / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml",
        "risk_limits_yaml": PROJECT_ROOT / "config" / "risk_limits.yaml",
        "start_15m_ps1": PROJECT_ROOT / "start_15m.ps1",
        "dotenv_file_names": PROJECT_ROOT / ".env",
    }
    for name, path in config_paths.items():
        if not path.exists():
            continue
        # Load config YAML/PS1 as text, but for .env we only list keys
        if name == "dotenv_file_names":
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    keys = [line.split("=", 1)[0].strip() for line in f if "=" in line and not line.strip().startswith("#")]
                snapshot[name] = {"_keys": keys, "_note": "Values are redacted"}
            except Exception as e:
                snapshot[name] = {"error": f"Failed to read .env keys: {e}"}
        else:
            snapshot[name] = _load_text_lines(path, 200)

    # Data files
    data_files = {
        "kalshi_session_metadata_json": PROJECT_ROOT / "data" / "kalshi_session_metadata.json",
        "reconciliation_record_json": PROJECT_ROOT / "data" / "reconciliation_record_6edd27fc.json",
        "risk_kill_switch_json": PROJECT_ROOT / "data" / "risk_kill_switch.json",
        "paper_session_state_json": PROJECT_ROOT / "data" / "paper_session_state.json",
    }
    for name, path in data_files.items():
        snapshot[name] = _read_json_if_exists(path)

    # Server log tail
    server_log = PROJECT_ROOT / "server_output.log"
    snapshot["server_output_log_tail"] = _load_text_lines(server_log, 50)

    return snapshot


async def _paginate_raw(
    client: KalshiVenueClient,
    method: str,
    endpoint: str,
    data_key: str,
    params_base: Optional[Dict[str, Any]] = None,
    max_pages: int = 50,
) -> Dict[str, Any]:
    """Fetch all pages of a Kalshi endpoint and return raw list + pagination metadata."""
    all_items: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    page = 0
    total_latency = 0.0
    total_retries = 0
    last_page_info: List[Dict[str, Any]] = []

    while page < max_pages:
        params = copy.deepcopy(params_base or {})
        if cursor:
            params["cursor"] = cursor

        result = await client._request_with_resilience(
            "GET", endpoint, params=params, operation_name=f"{method}_page_{page}"
        )

        total_latency += result.latency_ms or 0
        total_retries += result.retries or 0

        page_info: Dict[str, Any] = {
            "page": page,
            "success": result.success,
            "latency_ms": result.latency_ms,
            "retries": result.retries,
            "error": str(result.error) if result.error is not None else None,
            "cursor_used": cursor,
            "next_cursor": None,
            "raw": _to_json_safe(result.data),
        }

        if not result.success:
            page_info["next_cursor"] = None
            last_page_info.append(page_info)
            break

        data = result.data or {}
        items = data.get(data_key, [])
        all_items.extend(items)
        next_cursor = data.get("cursor")
        page_info["next_cursor"] = next_cursor
        page_info["items_count"] = len(items)
        last_page_info.append(page_info)

        if not next_cursor:
            break
        cursor = next_cursor
        page += 1

    if page >= max_pages:
        last_page_info[-1]["hit_max_pages"] = True

    return {
        "fetch_time": _now_iso(),
        "endpoint": endpoint,
        "params_base": params_base,
        "total_items": len(all_items),
        "pages_fetched": len(last_page_info),
        "total_latency_ms": total_latency,
        "total_retries": total_retries,
        "pagination": last_page_info,
        data_key: all_items,
    }


async def _fetch_live_positions(client: KalshiVenueClient) -> Dict[str, Any]:
    """Fetch /portfolio/positions with both market_positions and event_positions."""
    all_market: List[Dict[str, Any]] = []
    all_event: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    page = 0
    total_latency = 0.0
    total_retries = 0
    last_page_info: List[Dict[str, Any]] = []

    while page < 10:
        params: Dict[str, Any] = {"limit": 100}
        if cursor:
            params["cursor"] = cursor

        result = await client._request_with_resilience(
            "GET", "/portfolio/positions", params=params, operation_name=f"get_positions_page_{page}"
        )
        total_latency += result.latency_ms or 0
        total_retries += result.retries or 0

        page_info = {
            "page": page,
            "success": result.success,
            "latency_ms": result.latency_ms,
            "retries": result.retries,
            "error": str(result.error) if result.error is not None else None,
            "next_cursor": None,
        }

        if not result.success:
            last_page_info.append(page_info)
            break

        data = result.data or {}
        market_items = data.get("market_positions", [])
        event_items = data.get("event_positions", [])
        all_market.extend(market_items)
        all_event.extend(event_items)
        page_info["market_items"] = len(market_items)
        page_info["event_items"] = len(event_items)

        next_cursor = data.get("cursor")
        page_info["next_cursor"] = next_cursor
        last_page_info.append(page_info)

        if not next_cursor:
            break
        cursor = next_cursor
        page += 1

    return {
        "fetch_time": _now_iso(),
        "endpoint": "/portfolio/positions",
        "total_items": len(all_market) + len(all_event),
        "market_positions_count": len(all_market),
        "event_positions_count": len(all_event),
        "pages_fetched": len(last_page_info),
        "total_latency_ms": total_latency,
        "total_retries": total_retries,
        "pagination": _to_json_safe(last_page_info),
        "market_positions": _to_json_safe(all_market),
        "event_positions": _to_json_safe(all_event),
    }


async def _fetch_raw_balance(client: KalshiVenueClient) -> Dict[str, Any]:
    result = await client._request_with_resilience(
        "GET", "/portfolio/balance", operation_name="get_balance"
    )
    return {
        "fetch_time": _now_iso(),
        "endpoint": "/portfolio/balance",
        "success": result.success,
        "latency_ms": result.latency_ms,
        "retries": result.retries,
        "error": str(result.error) if result.error is not None else None,
        "raw": _to_json_safe(result.data),
    }


async def run_audit_pull(output_dir: Optional[Path] = None) -> Path:
    """Run the full read-only audit pull and return the output directory."""
    ts = _ts_str()
    if output_dir is None:
        output_dir = PROJECT_ROOT / f"audit_output_{ts}"
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Kalshi audit pull starting. Output: %s", output_dir)

    # Build and write local snapshot first
    snapshot = _build_snapshot()
    snapshot_path = output_dir / f"snapshot_{ts}.json"
    _safe_write_json(snapshot_path, snapshot)
    logger.info("Wrote local snapshot: %s", snapshot_path)

    # Initialize Kalshi client
    config = get_kalshi_config()
    logger.info("Using Kalshi environment: %s", config.env)
    client = KalshiVenueClient(config)

    # 1a. Raw fills (authoritative /portfolio/fills)
    fills_raw = await _paginate_raw(client, "get_fills", "/portfolio/fills", "fills", max_pages=50)
    fills_path = output_dir / f"kalshi_fills_raw_{ts}.json"
    _safe_write_json(fills_path, fills_raw)
    logger.info("Wrote %d raw fills: %s", fills_raw["total_items"], fills_path)

    # 1b. Historical fills (fills before the current cutoff)
    historical_fills_raw = await _paginate_raw(client, "get_historical_fills", "/historical/fills", "fills", params_base={"limit": 1000}, max_pages=50)
    historical_path = output_dir / f"kalshi_historical_fills_raw_{ts}.json"
    _safe_write_json(historical_path, historical_fills_raw)
    logger.info("Wrote %d historical fills: %s", historical_fills_raw["total_items"], historical_path)

    # 2. Raw portfolio history
    hist_raw = await _paginate_raw(client, "get_portfolio_history", "/portfolio/history", "history", max_pages=50)
    hist_path = output_dir / f"kalshi_portfolio_history_raw_{ts}.json"
    _safe_write_json(hist_path, hist_raw)
    logger.info("Wrote %d history rows: %s", hist_raw["total_items"], hist_path)

    # 3. Raw open orders
    orders_raw = await _paginate_raw(client, "get_open_orders", "/portfolio/orders", "orders", params_base={"status": "open"}, max_pages=10)
    orders_path = output_dir / f"kalshi_open_orders_raw_{ts}.json"
    _safe_write_json(orders_path, orders_raw)
    logger.info("Wrote %d open orders: %s", orders_raw["total_items"], orders_path)

    # 4a. Raw positions
    positions_raw = await _fetch_live_positions(client)
    positions_path = output_dir / f"kalshi_positions_raw_{ts}.json"
    _safe_write_json(positions_path, positions_raw)
    logger.info("Wrote %d market/event positions: %s", positions_raw["total_items"], positions_path)

    # 4b. Raw historical positions (settled market PnL/positions)
    historical_positions_raw = await _paginate_raw(client, "get_historical_positions", "/historical/positions", "market_positions", params_base={"limit": 1000}, max_pages=50)
    historical_positions_path = output_dir / f"kalshi_historical_positions_raw_{ts}.json"
    _safe_write_json(historical_positions_path, historical_positions_raw)
    logger.info("Wrote %d historical positions: %s", historical_positions_raw["total_items"], historical_positions_path)

    # 5. Raw balance
    balance_raw = await _fetch_raw_balance(client)
    balance_path = output_dir / f"kalshi_balance_raw_{ts}.json"
    _safe_write_json(balance_path, balance_raw)
    logger.info("Wrote balance: %s", balance_path)

    # 6. Raw settlements (for residual PnL attribution)
    settlements_raw = await _paginate_raw(client, "get_settlements", "/portfolio/settlements", "settlements", params_base={"limit": 1000}, max_pages=50)
    settlements_path = output_dir / f"kalshi_settlements_raw_{ts}.json"
    _safe_write_json(settlements_path, settlements_raw)
    logger.info("Wrote %d settlements: %s", settlements_raw["total_items"], settlements_path)

    # 7. Raw deposits
    deposits_raw = await _paginate_raw(client, "get_deposits", "/portfolio/deposits", "deposits", max_pages=10)
    deposits_path = output_dir / f"kalshi_deposits_raw_{ts}.json"
    _safe_write_json(deposits_path, deposits_raw)
    logger.info("Wrote %d deposits: %s", deposits_raw["total_items"], deposits_path)

    # 8. Raw withdrawals
    withdrawals_raw = await _paginate_raw(client, "get_withdrawals", "/portfolio/withdrawals", "withdrawals", max_pages=10)
    withdrawals_path = output_dir / f"kalshi_withdrawals_raw_{ts}.json"
    _safe_write_json(withdrawals_path, withdrawals_raw)
    logger.info("Wrote %d withdrawals: %s", withdrawals_raw["total_items"], withdrawals_path)

    # 9. Manifest
    manifest = {
        "created_at": _now_iso(),
        "output_dir": str(output_dir),
        "files": {
            "snapshot": str(snapshot_path.relative_to(PROJECT_ROOT)),
            "fills_raw": str(fills_path.relative_to(PROJECT_ROOT)),
            "historical_fills_raw": str(historical_path.relative_to(PROJECT_ROOT)),
            "portfolio_history_raw": str(hist_path.relative_to(PROJECT_ROOT)),
            "open_orders_raw": str(orders_path.relative_to(PROJECT_ROOT)),
            "positions_raw": str(positions_path.relative_to(PROJECT_ROOT)),
            "historical_positions_raw": str(historical_positions_path.relative_to(PROJECT_ROOT)),
            "balance_raw": str(balance_path.relative_to(PROJECT_ROOT)),
            "settlements_raw": str(settlements_path.relative_to(PROJECT_ROOT)),
            "deposits_raw": str(deposits_path.relative_to(PROJECT_ROOT)),
            "withdrawals_raw": str(withdrawals_path.relative_to(PROJECT_ROOT)),
        },
        "totals": {
            "fills": fills_raw["total_items"],
            "historical_fills": historical_fills_raw["total_items"],
            "portfolio_history_rows": hist_raw["total_items"],
            "open_orders": orders_raw["total_items"],
            "positions": positions_raw["total_items"],
            "historical_positions": historical_positions_raw["total_items"],
            "settlements": settlements_raw["total_items"],
            "deposits": deposits_raw["total_items"],
            "withdrawals": withdrawals_raw["total_items"],
        },
        "kalshi_env": str(config.env),
        "client_key_id": (str(getattr(config, "key_id", getattr(config, "key", ""))[:8]) + "...")
        if getattr(config, "key_id", getattr(config, "key", "")) else "<none>",
    }
    manifest_path = output_dir / f"manifest_{ts}.json"
    _safe_write_json(manifest_path, manifest)
    logger.info("Wrote manifest: %s", manifest_path)

    await client.close()
    logger.info("Kalshi audit pull complete. Artifacts in %s", output_dir)
    return output_dir


def main():
    parser = argparse.ArgumentParser(description="Read-only Kalshi audit data pull")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory for artifacts")
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else None
    out = asyncio.run(run_audit_pull(output_dir))
    print(f"AUDIT_OUTPUT_DIR={out}")


if __name__ == "__main__":
    main()
