#!/usr/bin/env python3
"""Snapshot dumper for Kalshi markets — captures raw market state for replay debugging.

Usage:
    from merid.event_venues.kalshi.tools.snapshot_dump import dump_kalshi_markets_snapshot

    # Inside live cycle where you have 'markets' list:
    snapshot_path = dump_kalshi_markets_snapshot(
        markets,
        asset="BTC",
        timeframe="15m",
        cycle_id=cycle_id,
    )
    logger.info("Kalshi snapshot written", extra={"path": str(snapshot_path)})

Upstream checks this unlocks:
- Confirm series→bucket mapping matches FilterPipeline input
- Diagnose "raw=0" cases by inspecting snapshot content vs catalog
"""

from __future__ import annotations

import json
import datetime
import pathlib
from typing import Any, Iterable, Dict, Set, List, Optional
import logging

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, ACTIVE_CRYPTO_WS_TIMEFRAMES

logger = logging.getLogger(__name__)

SNAPSHOT_DIR = pathlib.Path("var/kalshi_snapshots")

# Expected 5-asset universe and their timeframes for validation (derived from canonical config)
EXPECTED_ASSETS: Set[str] = set(ACTIVE_CRYPTO_ASSETS)
EXPECTED_TIMEFRAMES: Dict[str, List[str]] = {
    asset: list(ACTIVE_CRYPTO_WS_TIMEFRAMES) for asset in ACTIVE_CRYPTO_ASSETS
}


def _default_serializer(obj: Any) -> Any:
    """Serialize objects for JSON dump — handles dataclasses, MarketCandidate, datetime."""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dataclass_fields__"):
        # Handle dataclass instances
        return {k: getattr(obj, k) for k in obj.__dataclass_fields__}
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    return getattr(obj, "__dict__", str(obj))


def validate_snapshot_coverage(
    snapshot_payload: Dict[str, Any],
    cycle_id: int | None = None,
) -> Dict[str, Any]:
    """Validate snapshot payload contains expected 5-asset universe + timeframes.
    
    Performs the following checks:
    1. All 5 assets (BTC, ETH, SOL, XRP, DOGE) present in discovered set
    2. Expected timeframes per asset (15m, 1h, daily, weekly) all present
    3. Per-asset tracking: discovered, candidates, tradeable, traded
    
    Args:
        snapshot_payload: The snapshot payload with 'meta' and 'markets' keys
        cycle_id: Optional cycle identifier for logging context
        
    Returns:
        Dict with coverage validation results:
        {
            'valid': bool,
            'assets_missing': List[str],
            'timeframe_gaps': Dict[str, List[str]],
            'per_asset_summary': Dict[str, Dict],
        }
    """
    meta = snapshot_payload.get("meta", {})
    markets = snapshot_payload.get("markets", [])
    cycle_tag = f"cycle={cycle_id} " if cycle_id else ""
    
    result = {
        "valid": True,
        "assets_missing": [],
        "timeframe_gaps": {},
        "per_asset_summary": {},
    }
    
    # Extract assets from market tickers
    discovered_assets: Set[str] = set()
    per_asset_tickers: Dict[str, Set[str]] = {}
    
    for m in markets:
        ticker = None
        if isinstance(m, dict):
            ticker = m.get("ticker") or m.get("market_ticker") or m.get("ticker_symbol")
        elif hasattr(m, "ticker"):
            ticker = getattr(m, "ticker")
        elif hasattr(m, "market_ticker"):
            ticker = getattr(m, "market_ticker")
            
        if not ticker or not isinstance(ticker, str):
            continue
            
        # Infer asset from ticker prefix
        asset = None
        for expected in EXPECTED_ASSETS:
            if ticker.startswith(f"KX{expected}") or ticker.startswith(expected):
                asset = expected
                break
                
        if asset:
            discovered_assets.add(asset)
            per_asset_tickers.setdefault(asset, set()).add(ticker)
    
    # Check missing assets
    missing_assets = EXPECTED_ASSETS - discovered_assets
    if missing_assets:
        result["valid"] = False
        result["assets_missing"] = sorted(missing_assets)
        logger.error(
            "[SNAPSHOT-COVERAGE-ERROR] %scycle missing_assets={%s} expected={%s}",
            cycle_tag,
            ",".join(sorted(missing_assets)),
            ",".join(sorted(EXPECTED_ASSETS))
        )
    
    # Check per-asset timeframe coverage
    for asset in discovered_assets:
        tickers = per_asset_tickers.get(asset, set())
        
        # Infer timeframes from tickers
        found_timeframes: Set[str] = set()
        for ticker in tickers:
            # Extract timeframe from ticker (e.g., KXBTC15M-12345 -> 15m)
            if "15M" in ticker or "15m" in ticker.lower():
                found_timeframes.add("15m")
            elif "1H" in ticker or "1h" in ticker.lower():
                found_timeframes.add("1h")
            elif "D1" in ticker or "D" in ticker:
                found_timeframes.add("daily")
            elif "W1" in ticker or "W" in ticker:
                found_timeframes.add("weekly")
                
        expected_tfs = set(EXPECTED_TIMEFRAMES.get(asset, []))
        missing_tfs = expected_tfs - found_timeframes
        
        if missing_tfs:
            if asset not in result["timeframe_gaps"]:
                result["timeframe_gaps"][asset] = []
            result["timeframe_gaps"][asset] = sorted(missing_tfs)
            result["valid"] = False
            logger.warning(
                "[SNAPSHOT-TF-MISSING] %sasset=%s missing_timeframes={%s} tickers=%d",
                cycle_tag,
                asset,
                ",".join(sorted(missing_tfs)),
                len(tickers)
            )
        
        # Per-asset summary
        result["per_asset_summary"][asset] = {
            "discovered": True,
            "ticker_count": len(tickers),
            "timeframes_found": sorted(found_timeframes),
            "timeframes_missing": sorted(missing_tfs) if missing_tfs else [],
        }
    
    # Log summary for missing assets
    for asset in missing_assets:
        result["per_asset_summary"][asset] = {
            "discovered": False,
            "ticker_count": 0,
            "timeframes_found": [],
            "timeframes_missing": EXPECTED_TIMEFRAMES.get(asset, []),
        }
    
    # Final coverage summary
    if result["valid"]:
        logger.info(
            "[SNAPSHOT-COVERAGE-OK] %sassets={%s} timeframes_per_asset=%s",
            cycle_tag,
            ",".join(sorted(discovered_assets)),
            {
                a: len(result["per_asset_summary"][a]["timeframes_found"])
                for a in sorted(discovered_assets)
            }
        )
    else:
        logger.error(
            "[SNAPSHOT-COVERAGE-FAIL] %sassets_discovered={%s} assets_missing={%s} "
            "timeframe_gaps=%d",
            cycle_tag,
            ",".join(sorted(discovered_assets)),
            ",".join(sorted(missing_assets)),
            len(result["timeframe_gaps"])
        )
    
    return result


def dump_kalshi_markets_snapshot(
    markets: Iterable[Any],
    *,
    asset: str,
    timeframe: str,
    cycle_id: int | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> pathlib.Path:
    """Capture raw Kalshi markets to JSON for offline replay.

    Args:
        markets: Iterable of raw market objects (MarketCandidate, dict, etc.)
        asset: Underlying asset (BTC, ETH, SOL, XRP, DOGE)
        timeframe: Timeframe bucket (15m, 1h, D1, W1, 1M)
        cycle_id: Optional cycle identifier for tracing
        extra_meta: Optional additional metadata to include

    Returns:
        Path to written snapshot file
    """
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    cid = f"cycle{cycle_id:06d}" if cycle_id is not None else "cycle_unknown"
    fname = f"kalshi_{asset}_{timeframe}_{cid}_{ts}.json"
    path = SNAPSHOT_DIR / fname

    # Serialize markets
    market_list = list(markets)
    serialized_markets = []
    for m in market_list:
        try:
            serialized_markets.append(_default_serializer(m))
        except Exception:
            # Fallback: try to extract common fields
            if hasattr(m, "__dict__"):
                serialized_markets.append(m.__dict__)
            else:
                serialized_markets.append(str(m))

    payload = {
        "meta": {
            "asset": asset,
            "timeframe": timeframe,
            "cycle_id": cycle_id,
            "created_at": ts,
            "market_count": len(market_list),
            **(extra_meta or {}),
        },
        "markets": serialized_markets,
    }
    
    # Run 5-asset coverage validation and include results in metadata
    coverage_result = validate_snapshot_coverage(payload, cycle_id=cycle_id)
    payload["meta"]["coverage_validation"] = {
        "valid": coverage_result["valid"],
        "assets_missing": coverage_result["assets_missing"],
        "timeframe_gaps": coverage_result["timeframe_gaps"],
        "per_asset_summary": coverage_result["per_asset_summary"],
        "expected_assets": sorted(EXPECTED_ASSETS),
    }

    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def load_kalshi_snapshot(path: pathlib.Path) -> dict[str, Any]:
    """Load a previously dumped snapshot for replay.

    Args:
        path: Path to snapshot JSON file

    Returns:
        Dict with 'meta' and 'markets' keys
    """
    return json.loads(path.read_text())


def list_snapshots(
    asset: str | None = None,
    timeframe: str | None = None,
    limit: int = 10,
) -> list[pathlib.Path]:
    """List available snapshots, optionally filtered by asset/timeframe.

    Returns most recent snapshots first (sorted by filename timestamp).
    """
    if not SNAPSHOT_DIR.exists():
        return []

    pattern = "kalshi_"
    if asset:
        pattern += f"{asset}_"
    if timeframe:
        pattern += f"{timeframe}_"
    pattern += "*.json"

    snapshots = list(SNAPSHOT_DIR.glob(pattern))
    snapshots.sort(reverse=True)  # Most recent first (timestamp in filename)
    return snapshots[:limit]


def get_latest_snapshot(
    asset: str | None = None,
    timeframe: str | None = None,
) -> pathlib.Path | None:
    """Get the most recent snapshot matching filters."""
    snapshots = list_snapshots(asset=asset, timeframe=timeframe, limit=1)
    return snapshots[0] if snapshots else None


# Quick sanity test if run directly
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("snapshot_dump")

    # Test with dummy data
    class DummyMarket:
        def __init__(self, ticker: str, price: int):
            self.ticker = ticker
            self.price = price

    test_markets = [
        DummyMarket("KXBTC15M-TEST-15", 3500),
        DummyMarket("KXBTC15M-TEST-16", 3600),
    ]

    path = dump_kalshi_markets_snapshot(
        test_markets,
        asset="BTC",
        timeframe="15m",
        cycle_id=42,
    )
    logger.info(f"Test snapshot written to: {path}")

    # Load it back
    loaded = load_kalshi_snapshot(path)
    logger.info(f"Loaded {loaded['meta']['market_count']} markets from snapshot")
    logger.info(f"Meta: {loaded['meta']}")
