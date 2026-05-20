"""Shared PM sizing helpers for AgentGrid (no ContinuousTrader process).

``KalshiContinuousTrader`` delegates contract counts to ``BankrollManager.calculate_order_size``.
AgentGrid agents should keep using ``KalshiStrategy`` + ``merid.formulas`` for sizing; this
module exists so optional CT-aligned knobs (Kelly fraction, risk-per-trade caps) can be
imported without starting CT or duplicating formulas in agent code.
"""

from __future__ import annotations

from merid.formulas import PositionSizingInputs, quarter_kelly_size


def quarter_kelly_contracts(
    *,
    bankroll_cents: int,
    edge: float,
    price_cents: int,
    fractional_kelly: float = 0.25,
    max_contracts: int = 50,  # Increased to 50 for 15m scalper mode (was 25)
    min_contracts: int = 1,
) -> int:
    """Map bankroll + edge to an integer contract count (``merid.formulas.quarter_kelly_size``)."""
    inp = PositionSizingInputs(
        bankroll_cents=bankroll_cents,
        edge=edge,
        price_cents=price_cents,
        fractional_kelly=fractional_kelly,
    )
    q, _, _warn = quarter_kelly_size(inp)
    # 24/7-SCALPER-FIX: Ensure at least min_contracts when edge is positive
    # Prevents Kelly returning 0 for small bankrolls with positive edge
    if edge > 0 and q < min_contracts:
        return min_contracts
    if q < min_contracts:
        return 0
    return max(min_contracts, min(max_contracts, q))


def timeframe_exposure_multiplier(_timeframe: str) -> float:
    """CT ``TraderConfig.series_exposure_multiplier`` — for AgentGrid sizing if needed."""
    _tf = (_timeframe or "").strip().lower()
    m: dict[str, float] = {
        "15m": 0.80,      # Increased from 0.40 for meaningful 15m scalping (Issue #3 fix)
        "1h": 0.70,
        "hourly": 0.70,
        "daily": 1.00,
        "d1": 1.00,
        "weekly": 1.00,
        "monthly": 0.80,
        "annual": 0.60,
    }
    return m.get(_tf, 1.0)


def clip_contracts_by_timeframe(contracts: int, timeframe: str) -> int:
    """Scale integer contracts down for shorter timeframes (CT exposure curve)."""
    if contracts <= 0:
        return 0
    mult = timeframe_exposure_multiplier(timeframe)
    return max(1, int(round(contracts * mult))) if mult < 1.0 else contracts


def hedge_adjusted_contracts(
    contracts: int,
    asset: str,
    timeframe: str,
    side: str,  # "yes" or "no" - the side we're sizing for
    hedge_coverage_ratio: float = 0.0,
) -> int:
    """Adjust position size based on existing hedge coverage (Task 6).
    
    If we already have hedge coverage for an asset, reduce the alpha position
    size to avoid over-hedging. This prevents the scenario where we take a
    large alpha position, hedge 50% of it, then keep sizing up the alpha.
    
    Args:
        contracts: Raw contract count from Kelly sizing
        asset: Asset symbol (e.g., "BTC")
        timeframe: Timeframe string (e.g., "15m")
        side: "yes" or "no" - the side of the position being sized
        hedge_coverage_ratio: Ratio of exposure already covered by hedges (0.0-1.0)
        
    Returns:
        Adjusted contract count
    """
    if contracts <= 0:
        return 0
    
    if hedge_coverage_ratio <= 0:
        return contracts  # No hedge coverage, no adjustment needed
    
    # Reduce size proportionally to hedge coverage
    # If we're 50% hedged, only add 50% of the intended position
    adjustment = 1.0 - min(hedge_coverage_ratio, 1.0)
    adjusted = int(round(contracts * adjustment))
    
    # Log the adjustment for visibility
    if adjusted < contracts:
        logging.getLogger(__name__).debug(
            "[HEDGE-ADJUSTED-SIZE] %s-%s/%s: %d -> %d (coverage=%.1f%%)",
            asset, timeframe, side, contracts, adjusted, hedge_coverage_ratio * 100
        )
    
    return max(0, adjusted)


def get_hedge_coverage_ratio(
    asset: str,
    timeframe: str,
    side: str,  # "yes" or "no"
) -> float:
    """Get the ratio of exposure already covered by hedges for this asset/side.
    
    Task 6: Helper to query current hedge coverage from exposure snapshot.
    
    Args:
        asset: Asset symbol
        timeframe: Timeframe string
        side: "yes" or "no" - the side of the position being sized
        
    Returns:
        Coverage ratio (0.0-1.0). 0.5 means 50% of intended exposure is hedged.
    """
    try:
        from merid.hedging.exposure import build_exposure_snapshot
        
        snap = build_exposure_snapshot()
        cell = snap.get_cell(asset, timeframe)
        
        if side == "yes":
            alpha_exposure = cell.yes_notional_cents
            hedge_exposure = cell.hedge_yes_notional_cents
        else:
            alpha_exposure = cell.no_notional_cents
            hedge_exposure = cell.hedge_no_notional_cents
        
        if alpha_exposure <= 0:
            return 0.0  # No alpha exposure, no coverage needed
        
        # Coverage ratio = hedge notional / alpha notional
        # If we have $100 alpha and $60 hedge, coverage = 0.6 (60%)
        coverage = min(hedge_exposure / alpha_exposure, 2.0)  # Cap at 200%
        
        return coverage
    except Exception as exc:
        logging.getLogger(__name__).debug(
            "[HEDGE-COVERAGE] Failed to get coverage for %s-%s: %s",
            asset, timeframe, exc
        )
        return 0.0
