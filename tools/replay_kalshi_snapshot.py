#!/usr/bin/env python3
"""Offline replay runner for Kalshi snapshots — replay markets through FilterPipeline → NearSpotSelector with full grid inspector logging.

Usage:
    # Replay a single snapshot
    py tools/replay_kalshi_snapshot.py var/kalshi_snapshots/kalshi_BTC_15m_cycle000042_20260126T143000Z.json

    # Replay all BTC 15m snapshots
    py tools/replay_kalshi_snapshot.py "var/kalshi_snapshots/kalshi_BTC_15m_*.json"

    # Replay with verbose grid inspector output
    py tools/replay_kalshi_snapshot.py --verbose var/kalshi_snapshots/kalshi_ETH_1h_cycle*.json

Downstream checks this unlocks:
- PRE-ORDER logs show caps and position sizing using the same thresholds you think you configured
- You can change thresholds and rerun to diff results
- Diagnose when orders=0 but replay inspector shows close, high-edge candidates
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
from decimal import Decimal
from typing import Any, Callable

# Setup logging before imports
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("kalshi_replay")


def load_snapshot(path: pathlib.Path) -> dict[str, Any]:
    """Load and validate a versioned cycle snapshot JSON file."""
    from merid.event_venues.kalshi.cycle_snapshot_schema import assert_replayable_cycle_snapshot

    payload = json.loads(path.read_text())
    assert_replayable_cycle_snapshot(payload)
    return payload


def build_market_candidate_from_dict(data: dict[str, Any]) -> Any:
    """Reconstruct a MarketCandidate from serialized dict."""
    from merid.event_venues.kalshi.market_filter import MarketCandidate

    return MarketCandidate(
        ticker=data.get("ticker", "unknown"),
        underlying=data.get("underlying", ""),
        timeframe=data.get("timeframe", ""),
        expiry_ts=data.get("expiry_ts", 0.0),
        volume=data.get("volume", 0),
        open_interest=data.get("open_interest", 0),
        best_bid_cents=data.get("best_bid_cents", 0),
        best_ask_cents=data.get("best_ask_cents", 0),
        spread_cents=data.get("spread_cents", 0),
        mid_price_cents=data.get("mid_price_cents", 0),
        category=data.get("category", ""),
    )


def build_filter_pipeline(
    min_volume: int = 50,
    min_open_interest: int = 10,
    max_spread_cents: int = 12,
    min_price_cents: int = 10,
    max_price_cents: int = 90,
) -> Any:
    """Build FilterPipeline matching live wiring."""
    from merid.event_venues.kalshi.market_filter import MarketFilter, MarketFilterConfig

    config = MarketFilterConfig(
        min_volume=min_volume,
        min_open_interest=min_open_interest,
        max_spread_cents=max_spread_cents,
        min_price_cents=min_price_cents,
        max_price_cents=max_price_cents,
    )
    return MarketFilter(config=config)


def build_near_spot_selector(
    spot_source: dict[str, float] | None = None,
) -> Any:
    """Build NearSpotSelector with mock spot source for replay."""
    from merid.event_venues.kalshi.market_filter import NearSpotSelector

    spot_dict = spot_source or {}

    def get_spot(underlying: str) -> float:
        # Return mock spot for replay — caller should inject realistic values
        return spot_dict.get(underlying.upper(), 0.0)

    return NearSpotSelector(spot_source=get_spot)


def replay_snapshot(
    path: pathlib.Path,
    verbose: bool = False,
    spot_overrides: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Replay a single snapshot through the pipeline with full logging.

    Returns dict with replay results for assertion/testing.
    """
    from merid.event_venues.kalshi.market_filter import (
        log_tiered_grid_inspector,
        get_tiered_min_edge,
        get_tiered_max_price,
        get_series_timeframe_bucket,
    )

    payload = load_snapshot(path)
    meta = payload["meta"]
    raw_markets = payload["markets"]
    asset = meta["asset"]
    timeframe = meta["timeframe"]
    cycle_id = meta.get("cycle_id", "unknown")
    _raw_spots = payload.get("spots") if isinstance(payload.get("spots"), dict) else {}
    try:
        _from_file = {k: float(v) for k, v in _raw_spots.items()}
    except (TypeError, ValueError):
        _from_file = {}
    effective_spots = {**_from_file, **(spot_overrides or {})}

    log.info("=" * 80)
    log.info(
        "Replaying snapshot: asset=%s timeframe=%s cycle=%s markets=%d",
        asset, timeframe, cycle_id, len(raw_markets),
    )
    log.info("=" * 80)

    # Convert serialized markets back to MarketCandidate objects
    candidates = [build_market_candidate_from_dict(m) for m in raw_markets]
    log.info("Loaded %d candidates from snapshot", len(candidates))

    # Step 1: Run through FilterPipeline
    pipeline = build_filter_pipeline()
    filter_result = pipeline.filter_markets(candidates)

    log.info(
        "FilterPipeline results: passed=%d rejected=(volume=%d, oi=%d, spread=%d, price=%d, underlying=%d, timeframe=%d)",
        filter_result.passed,
        filter_result.rejected_volume,
        filter_result.rejected_oi,
        filter_result.rejected_spread,
        filter_result.rejected_price,
        filter_result.rejected_underlying,
        filter_result.rejected_timeframe,
    )

    # Step 2: Log grid inspector for all candidates (to verify series→bucket mapping)
    if verbose:
        # Build list of unique series tickers from candidates
        series_tickers = list(set(
            c.ticker.split("-")[0] if "-" in c.ticker else c.ticker
            for c in candidates
        ))
        log_tiered_grid_inspector(
            series_tickers=series_tickers,
            assets=[asset],
            log_live_candidates=True,
            live_candidates=candidates[:5],  # Show first 5
        )

    # Step 3: Run NearSpotSelector with mock spot
    selector = build_near_spot_selector(effective_spots)

    # Mock edge compute function for replay
    def mock_compute_edge(candidate: Any, spot: float, strike: float) -> Decimal:
        # Return a mock edge based on distance (closer = higher edge)
        if spot <= 0:
            return Decimal("0")
        distance = abs(strike - spot) if strike > 0 else 0
        distance_pct = distance / spot if spot > 0 else 1.0
        # Mock: closer to spot = higher edge (0.15 at 0% distance, drops to 0.05 at 10%)
        edge = Decimal("0.15") - Decimal(str(distance_pct * 1.0))
        return max(edge, Decimal("0.01"))

    # Run selector with tiered thresholds enabled
    near_spot_candidates = selector.select_near_spot(
        filter_result.candidates,
        compute_edge=mock_compute_edge,
        max_per_bucket=2,
        max_distance_pct=0.125,  # 12.5% band
        use_tiered_min_edge=True,
        use_tiered_max_price=True,
    )

    log.info(
        "[NearSpot replay] final=%d from %d filter-passed candidates",
        len(near_spot_candidates), len(filter_result.candidates),
    )

    # Step 4: Log per-candidate analysis
    if verbose and near_spot_candidates:
        log.info("-" * 80)
        log.info("Selected candidates analysis:")
        for c in near_spot_candidates[:5]:
            series = c.ticker.split("-")[0] if "-" in c.ticker else c.ticker
            bucket = get_series_timeframe_bucket(c.ticker)
            min_edge = get_tiered_min_edge(c.underlying, c.ticker)
            max_price = get_tiered_max_price(c.underlying, c.ticker)
            mid = c.mid_price_cents

            price_status = "✓" if mid <= max_price else "✗ PRICE"
            log.info(
                "  %s → bucket=%s | mid=%dc | max=%dc | min_edge=%.2f | %s",
                c.ticker, bucket, mid, max_price, float(min_edge), price_status,
            )

    # Build result summary
    result = {
        "path": str(path),
        "meta": meta,
        "input_count": len(candidates),
        "filter_passed": filter_result.passed,
        "filter_rejected": {
            "volume": filter_result.rejected_volume,
            "oi": filter_result.rejected_oi,
            "spread": filter_result.rejected_spread,
            "price": filter_result.rejected_price,
            "underlying": filter_result.rejected_underlying,
            "timeframe": filter_result.rejected_timeframe,
        },
        "near_spot_selected": len(near_spot_candidates),
        "selected_tickers": [c.ticker for c in near_spot_candidates],
    }

    log.info("=" * 80)
    log.info("Replay complete: %d final candidates selected", len(near_spot_candidates))
    log.info("=" * 80)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay Kalshi market snapshots through FilterPipeline → NearSpotSelector",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Snapshot JSON paths or glob patterns (e.g., var/kalshi_snapshots/*.json)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose grid inspector output",
    )
    parser.add_argument(
        "--spot",
        type=str,
        help="Spot price overrides as JSON dict, e.g., '{\"BTC\":80000,\"ETH\":4000}'",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=pathlib.Path,
        help="Write results summary to JSON file",
    )

    args = parser.parse_args()

    # Parse spot overrides
    spot_overrides = {}
    if args.spot:
        spot_overrides = json.loads(args.spot)

    # Expand glob patterns
    all_paths = []
    for pattern in args.paths:
        if "*" in pattern or "?" in pattern:
            all_paths.extend(pathlib.Path().glob(pattern))
        else:
            all_paths.append(pathlib.Path(pattern))

    # Sort and dedupe
    all_paths = sorted(set(all_paths))

    if not all_paths:
        log.error("No snapshot files found matching: %s", args.paths)
        return 1

    log.info("Found %d snapshot(s) to replay", len(all_paths))

    all_results = []
    for path in all_paths:
        if not path.exists():
            log.warning("Snapshot not found: %s", path)
            continue

        try:
            result = replay_snapshot(path, verbose=args.verbose, spot_overrides=spot_overrides)
            all_results.append(result)
        except Exception as e:
            log.exception("Failed to replay snapshot: %s", path)
            all_results.append({
                "path": str(path),
                "error": str(e),
            })

    # Summary
    log.info("\n" + "=" * 80)
    log.info("REPLAY SUMMARY: %d snapshots processed", len(all_results))
    log.info("=" * 80)

    total_input = sum(r.get("input_count", 0) for r in all_results if "error" not in r)
    total_selected = sum(r.get("near_spot_selected", 0) for r in all_results if "error" not in r)

    log.info("Total markets processed: %d", total_input)
    log.info("Total candidates selected: %d", total_selected)

    # Write output if requested
    if args.output:
        summary = {
            "snapshots": all_results,
            "totals": {
                "input": total_input,
                "selected": total_selected,
            },
        }
        args.output.write_text(json.dumps(summary, indent=2))
        log.info("Results written to: %s", args.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
