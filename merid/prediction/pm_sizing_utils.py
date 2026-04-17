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
    max_contracts: int = 25,
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
    if q < min_contracts:
        return 0
    return max(min_contracts, min(max_contracts, q))


def timeframe_exposure_multiplier(_timeframe: str) -> float:
    """CT ``TraderConfig.series_exposure_multiplier`` — for AgentGrid sizing if needed."""
    _tf = (_timeframe or "").strip().lower()
    m: dict[str, float] = {
        "15m": 0.40,
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
