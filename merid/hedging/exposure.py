"""ExposureSnapshot — aggregates per-asset × per-timeframe directional exposure.

Reads from:
  - ``KalshiPositionCache`` (real-time fill events)
  - Pending orders in ``IdempotentOrderStore``
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.hedging.exposure")

# Task 5 & 6 Fix: Configurable hedge thresholds (not hardcoded)
# SEV-2 FIX: Use consistent environment variable names across the codebase
# MERID_HEDGE_NEUTRAL_THRESHOLD_CENTS is the canonical name used elsewhere
HEDGE_NEUTRAL_THRESHOLD_CENTS = int(os.environ.get("MERID_HEDGE_NEUTRAL_THRESHOLD_CENTS", "10"))
# SEV-2 FIX: Use consistent environment variable name MERID_MAX_HEDGE_COVERAGE_RATIO
# Default to 1.0 (100% coverage) which is the safer default
MAX_HEDGE_COVERAGE_RATIO = float(os.environ.get("MERID_MAX_HEDGE_COVERAGE_RATIO", "1.0"))


@dataclass
class CellExposure:
    """Directional exposure for one (asset, timeframe) cell.

    All values in **cents** (1 contract @ 50¢ = 50 cents notional).
    ``net_delta`` is signed: positive = net YES / long, negative = net NO / short.
    
    Task 2: Separate tracking for alpha vs hedge exposure to prevent
    double-counting (hedges hedging hedges).
    """

    asset: str
    timeframe: str
    
    # Alpha (trading) exposure
    yes_notional_cents: int = 0
    no_notional_cents: int = 0
    yes_contracts: int = 0
    no_contracts: int = 0
    
    # Hedge exposure (separate tracking)
    hedge_yes_notional_cents: int = 0
    hedge_no_notional_cents: int = 0
    hedge_yes_contracts: int = 0
    hedge_no_contracts: int = 0
    
    # Pending orders
    pending_yes_cents: int = 0
    pending_no_cents: int = 0
    
    # CRITICAL FIX (2026-07-29): Alpha position metadata for pairing
    # Tracks which alpha positions contribute to this cell's exposure
    alpha_positions: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # position_id -> {fill_id, entry_time, side, size}

    @property
    def net_delta_cents(self) -> int:
        """Signed net directional exposure from FILLED positions only.
        
        CRITICAL FIX (2026-07-29): Removed pending orders from exposure calculation.
        Hedge engine should only hedge filled positions, not pending orders that may be rejected.
        Pending orders are no longer included to prevent hedge orders before alpha fills.
        
        Task 2: Uses alpha exposure only (hedge exposure is the hedge, not exposure).
        """
        return (
            self.yes_notional_cents
            - self.no_notional_cents
        )
    
    @property
    def alpha_net_delta_cents(self) -> int:
        """Net alpha (trading) exposure only."""
        return self.yes_notional_cents - self.no_notional_cents
    
    @property
    def hedge_net_delta_cents(self) -> int:
        """Net hedge exposure (offset to alpha)."""
        return self.hedge_yes_notional_cents - self.hedge_no_notional_cents
    
    @property
    def hedged_exposure_cents(self) -> int:
        """Net exposure after hedging (alpha + hedge)."""
        return self.alpha_net_delta_cents + self.hedge_net_delta_cents

    @property
    def gross_cents(self) -> int:
        return (
            self.yes_notional_cents
            + self.no_notional_cents
            + self.pending_yes_cents
            + self.pending_no_cents
        )


@dataclass
class ExposureSnapshot:
    """Point-in-time exposure across all assets and timeframes."""

    cells: Dict[Tuple[str, str], CellExposure] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def get_cell(self, asset: str, tf: str) -> CellExposure:
        key = (asset.upper(), tf)
        if key not in self.cells:
            self.cells[key] = CellExposure(asset=asset.upper(), timeframe=tf)
        return self.cells[key]

    def net_delta_cents(self, asset: str, tf: str) -> int:
        cell = self.cells.get((asset.upper(), tf))
        return cell.net_delta_cents if cell else 0

    def all_asset_timeframes(self) -> List[Tuple[str, str]]:
        """Return all (asset, timeframe) pairs with non-zero exposure."""
        return [k for k, v in self.cells.items() if v.gross_cents > 0]


def build_exposure_snapshot() -> ExposureSnapshot:
    """Build snapshot from live position cache and pending order store.

    Task 2: Separates alpha (trading) exposure from hedge exposure to prevent
    the hedge engine from hedging its own hedges.

    Graceful-degrade: returns empty snapshot if infrastructure is unavailable.
    """
    snap = ExposureSnapshot()

    # ── 1. Position cache ─────────────────────────────────────────────
    # Task 2: Distinguish alpha vs hedge positions using fill_source
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        from merid.event_venues.kalshi.market_filter import (
            extract_asset_from_ticker,
            get_series_timeframe_bucket,
        )

        # Get fills ledger to check fill_source
        try:
            ledger = get_fills_ledger()
            fill_source_map = {
                fill.fill_id: fill.fill_source 
                for fill in ledger.get_all_fills().values()
            }
        except Exception:
            fill_source_map = {}

        for ticker, pos in get_position_cache().get_all_positions().items():
            asset = extract_asset_from_ticker(ticker)
            if not asset:
                continue
            tf = get_series_timeframe_bucket(ticker)
            cell = snap.get_cell(asset, tf)
            # CRITICAL FIX (2026-07-23): Handle None avg_price_cents (unknown entry price)
            notional = pos.contracts * pos.avg_price_cents if pos.avg_price_cents is not None else 0
            
            # Task 2: Check if position came from hedge fill
            # Use fill_source_map from ledger (primary) or client_order_id prefix (fallback)
            # SEV-0 FIX: Enhanced fallback to check for hedge markers in client_order_id content
            is_hedge = False
            # BUG-FIX: Actually use fill_source_map we just built
            if pos.fill_id and pos.fill_id in fill_source_map:
                is_hedge = fill_source_map[pos.fill_id] == "hedge"
            elif hasattr(pos, 'client_order_id') and pos.client_order_id:
                # Priority 1: Check HEDGE_ prefix
                if pos.client_order_id.startswith('HEDGE_'):
                    is_hedge = True
                # Priority 2: Check for hedge markers in content (matches position_cache logic)
                else:
                    client_order_id_lower = pos.client_order_id.lower()
                    is_hedge = "hedge" in client_order_id_lower or "hedge_engine" in client_order_id_lower
            
            if is_hedge:
                # Hedge exposure - separate tracking
                if pos.side == "yes":
                    cell.hedge_yes_notional_cents += notional
                    cell.hedge_yes_contracts += pos.contracts
                else:
                    cell.hedge_no_notional_cents += notional
                    cell.hedge_no_contracts += pos.contracts
            else:
                # Alpha exposure - what we hedge against
                if pos.side == "yes":
                    cell.yes_notional_cents += notional
                    cell.yes_contracts += pos.contracts
                else:
                    cell.no_notional_cents += notional
                    cell.no_contracts += pos.contracts
                
                # CRITICAL FIX (2026-07-29): Track alpha position metadata for pairing
                # Store market_id, fill_id, entry_time, side, and size for hedge pairing
                # BUG FIX (2026-07-29): CachedPosition uses market_id not position_id
                if hasattr(pos, 'market_id') and pos.market_id:
                    cell.alpha_positions[pos.market_id] = {
                        "fill_id": getattr(pos, 'fill_id', None),
                        "entry_time": getattr(pos, 'entry_time', None),
                        "side": pos.side,
                        "size": pos.contracts,
                        "avg_price_cents": pos.avg_price_cents,
                    }
    except Exception as exc:
        logger.debug("[exposure] position cache read failed: %s", exc)

    # ── 2. Pending orders (from IdempotentOrderStore) ─────────────────
    try:
        from merid.event_venues.kalshi.order_gate import get_pre_trade_gate, OrderStatus
        from merid.event_venues.kalshi.market_filter import (
            extract_asset_from_ticker as _eat,
            get_series_timeframe_bucket as _gstb,
        )

        gate = get_pre_trade_gate()
        for rec in gate._store.snapshot():
            if rec.status not in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.LIVE):
                continue
            asset = _eat(rec.contract_id)
            if not asset:
                continue
            tf = _gstb(rec.contract_id)
            cell = snap.get_cell(asset, tf)
            notional = rec.target_count * rec.price_cents
            if rec.side == "yes":
                cell.pending_yes_cents += notional
            else:
                cell.pending_no_cents += notional
    except Exception as exc:
        logger.debug("[exposure] pending orders read failed: %s", exc)

    # Task 2: Log hedge-aware exposure summary
    total_alpha = sum(c.alpha_net_delta_cents for c in snap.cells.values())
    total_hedge = sum(c.hedge_net_delta_cents for c in snap.cells.values())
    total_hedged = sum(c.hedged_exposure_cents for c in snap.cells.values())
    
    logger.debug(
        "[EXPOSURE-SNAPSHOT] cells=%d alpha=%d¢ hedge=%d¢ net=%d¢",
        len(snap.cells), total_alpha, total_hedge, total_hedged
    )

    return snap


# ---------------------------------------------------------------------------
# Task 7: Cross-Asset Exposure Aggregation
# ---------------------------------------------------------------------------

# Define asset groups for cross-asset hedging
# Task 1 Fix: Configurable via environment variable with sensible default
# CRITICAL FIX 2026-07-28: Include all 5 crypto assets by default (BTC, ETH, SOL, XRP, DOGE)
# Previous default only included 3 assets (BTC, ETH, SOL), leaving XRP and DOGE unhedged
CRYPTO_BASKET_ASSETS = os.environ.get(
    "MERID_HEDGE_CRYPTO_ASSETS", 
    "BTC,ETH,SOL,XRP,DOGE"
).split(",")
# Strip whitespace from each asset
CRYPTO_BASKET_ASSETS = [a.strip().upper() for a in CRYPTO_BASKET_ASSETS if a.strip()]

# Note: MAX_HEDGE_COVERAGE_RATIO and HEDGE_NEUTRAL_THRESHOLD_CENTS are defined
# at module level (lines 22-25) to avoid duplication


def get_basket_alpha_exposure(
    snap: ExposureSnapshot,
    basket_assets: List[str] = None,
) -> Dict[str, int]:
    """Aggregate alpha exposure across a basket of assets.
    
    Task 7: Returns total alpha exposure by side for cross-asset hedge sizing.
    
    Args:
        snap: ExposureSnapshot from build_exposure_snapshot()
        basket_assets: List of asset symbols (defaults to CRYPTO_BASKET)
        
    Returns:
        Dict with keys: "yes_total", "no_total", "net_delta"
    """
    if basket_assets is None:
        basket_assets = CRYPTO_BASKET_ASSETS
    
    yes_total = 0
    no_total = 0
    
    for cell in snap.cells.values():
        if cell.asset in basket_assets:
            yes_total += cell.yes_notional_cents  # Alpha only
            no_total += cell.no_notional_cents  # Alpha only
    
    return {
        "yes_total": yes_total,
        "no_total": no_total,
        "net_delta": yes_total - no_total,
        "assets_included": basket_assets,
    }


def get_cross_asset_hedge_coverage(
    snap: ExposureSnapshot,
    target_asset: str,
    hedge_assets: List[str] = None,
) -> Dict:
    """Calculate cross-asset hedge coverage for a target asset.
    
    Task 7: Used to determine if hedges in other assets (e.g., BTC) 
    provide coverage for exposure in target asset (e.g., SOL).
    
    Args:
        snap: ExposureSnapshot
        target_asset: Asset to check coverage for (e.g., "SOL")
        hedge_assets: Assets that can provide cross-hedge (e.g., ["BTC"])
        
    Returns:
        Dict with coverage metrics
    """
    if hedge_assets is None:
        # Default: BTC provides cross-hedge for crypto basket
        hedge_assets = ["BTC"]
    
    # Get target asset alpha exposure
    target_yes = 0
    target_no = 0
    for cell in snap.cells.values():
        if cell.asset == target_asset:
            target_yes = cell.yes_notional_cents
            target_no = cell.no_notional_cents
            break
    
    # Get cross-asset hedge exposure
    hedge_yes = 0
    hedge_no = 0
    for cell in snap.cells.values():
        if cell.asset in hedge_assets:
            hedge_yes += cell.hedge_yes_notional_cents
            hedge_no += cell.hedge_no_notional_cents
    
    # Calculate coverage ratios
    target_net = target_yes - target_no
    hedge_net = hedge_yes - hedge_no
    
    # Coverage is opposite exposure / target exposure
    # If target is long $100 yes, and hedge is long $60 yes (wrong direction), coverage = 0
    # If target is long $100 yes, and hedge is long $60 no (correct direction), coverage = 60%
    
    coverage_ratio = 0.0
    if target_net != 0 and hedge_net != 0:
        # Check if hedge is opposite direction
        if (target_net > 0 and hedge_net < 0) or (target_net < 0 and hedge_net > 0):
            coverage_ratio = min(abs(hedge_net) / abs(target_net), MAX_HEDGE_COVERAGE_RATIO)
    
    return {
        "target_asset": target_asset,
        "hedge_assets": hedge_assets,
        "target_net_delta": target_net,
        "hedge_net_delta": hedge_net,
        "coverage_ratio": coverage_ratio,
        "coverage_pct": coverage_ratio * 100,
        "is_fully_covered": coverage_ratio >= 1.0,
        "is_partially_covered": 0 < coverage_ratio < 1.0,
    }


def get_basket_hedge_efficiency(
    snap: ExposureSnapshot,
    basket_assets: List[str] = None,
) -> Dict:
    """Measure hedge efficiency across the entire basket.
    
    Task 7: Aggregate metric showing how well the basket is hedged overall.
    
    Returns:
        Dict with basket-wide hedge metrics
    """
    if basket_assets is None:
        basket_assets = CRYPTO_BASKET_ASSETS
    
    total_alpha = 0
    total_hedge = 0
    total_hedged_exposure = 0
    
    for cell in snap.cells.values():
        if cell.asset in basket_assets:
            total_alpha += cell.alpha_net_delta_cents
            total_hedge += cell.hedge_net_delta_cents
            total_hedged_exposure += cell.hedged_exposure_cents
    
    net_exposure = total_alpha + total_hedge  # Hedge is opposite sign
    
    # Efficiency: how much of alpha exposure is offset by hedges
    efficiency = 0.0
    if total_alpha != 0:
        efficiency = 1.0 - (abs(net_exposure) / abs(total_alpha))
        efficiency = max(0.0, min(1.0, efficiency))
    
    return {
        "basket_assets": basket_assets,
        "total_alpha_exposure": total_alpha,
        "total_hedge_exposure": total_hedge,
        "net_exposure": net_exposure,
        "total_hedged_exposure": total_hedged_exposure,
        "hedge_efficiency": efficiency,
        "hedge_efficiency_pct": efficiency * 100,
        "is_neutral": abs(net_exposure) < HEDGE_NEUTRAL_THRESHOLD_CENTS,  # Within $10 of neutral
    }
