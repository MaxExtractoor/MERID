"""Bracket Risk Rules — Per-bracket loss caps and cross-bracket correlation.

Kalshi BTC/ETH hourly brackets are overlapping contracts on the same
underlying hour.  Selling multiple narrow brackets creates correlated
exposure: if price exits the shared region, *all* brackets lose.

This module provides:

1. **Per-bracket loss cap**: max loss per contract as a fraction of session
   equity, so a single outside-range move can't wreck the session.
2. **Cross-bracket correlation grouping**: overlapping brackets on the same
   hour are treated as one combined bet for risk limit purposes.
3. **Consecutive-loser kill-switch**: auto-halt after N consecutive losing
   brackets before the strategy resumes.
4. **Unhedged delta cap**: limit total directional exposure across brackets.
5. **Per-asset-per-hour cap**: hard upper bound on dollar exposure per asset
   within a rolling one-hour window, sized for a small (~$16) bankroll.

Usage::

    br = BracketRiskManager(config)
    ok, reason = br.check_bracket_order(order)
    br.record_bracket_result(bracket_id, pnl_cents)
    br.summary()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.bracket_risk")


# ── Per-asset defaults (cents, sized for ~$16 bankroll) ──────────────────

_DEFAULT_PER_ASSET_HOUR_CAPS_CENTS: Dict[str, float] = {
    "BTC": 230.0,
    "ETH": 180.0,
    "SOL": 90.0,
    "XRP": 90.0,
    "DOGE": 60.0,
}


# ── Configuration ────────────────────────────────────────────────────────

@dataclass
class BracketRiskConfig:
    """Risk configuration for bracket trading."""

    # Per-bracket loss cap: max loss per contract as % of session equity
    max_loss_per_contract_pct: float = 1.0   # 1% of equity per contract

    # Per-bracket absolute loss cap (cents)
    max_loss_per_bracket_cents: float = 5000.0  # $50 max loss per bracket

    # Cross-bracket: max combined contracts on overlapping brackets in same hour
    max_contracts_per_hour: int = 50

    # Cross-bracket: max combined notional on same hour (cents)
    max_notional_per_hour_cents: float = 25000.0  # $250

    # Per-asset-per-hour notional cap (cents).  Keys are asset names (e.g. "BTC").
    # Defaults are sized for a ~$16 bankroll.  Override to scale with account size.
    per_asset_hour_caps_cents: Dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_PER_ASSET_HOUR_CAPS_CENTS)
    )

    # Consecutive loser kill-switch
    max_consecutive_losers: int = 5

    # Unhedged delta cap: max net directional contracts across all brackets
    max_unhedged_delta: int = 100

    # Max brackets open simultaneously
    max_open_brackets: int = 20


DEFAULT_BRACKET_RISK_CONFIG = BracketRiskConfig()


# ── Bracket order ────────────────────────────────────────────────────────

@dataclass
class BracketOrder:
    """A bracket order to be risk-checked."""
    bracket_id: str          # unique bracket identifier
    ticker: str              # market ticker
    underlying: str          # e.g. "BTC", "ETH"
    hour_key: str            # e.g. "2026-02-16T03" — groups correlated brackets
    side: str                # "buy" or "sell"
    contracts: int
    price_cents: int         # 0–99
    max_loss_cents: float    # worst-case loss for this bracket


# ── State ────────────────────────────────────────────────────────────────

@dataclass
class BracketState:
    """Mutable state for bracket risk tracking."""
    # Open brackets by hour_key
    open_by_hour: Dict[str, List[str]] = field(default_factory=dict)
    contracts_by_hour: Dict[str, int] = field(default_factory=dict)
    notional_by_hour: Dict[str, float] = field(default_factory=dict)

    # Per-asset-per-hour notional: asset -> (hour_key -> notional_cents)
    # hour_key format: "YYYY-MM-DDTHH" (UTC)
    asset_hour_notional: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # Per-asset-per-hour market list for top-consumer logging: asset -> (hour_key -> [ticker, ...])
    asset_hour_markets: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)

    # All open bracket IDs
    open_brackets: Set[str] = field(default_factory=set)

    # Net delta (positive = net long, negative = net short)
    net_delta: int = 0

    # Consecutive loser tracking
    consecutive_losers: int = 0
    max_consecutive_losers_seen: int = 0

    # Kill switch
    halted: bool = False
    halt_reason: Optional[str] = None

    # History
    total_brackets: int = 0
    winning_brackets: int = 0
    losing_brackets: int = 0
    total_pnl_cents: float = 0.0


# ── Manager ──────────────────────────────────────────────────────────────

class BracketRiskManager:
    """Risk manager for bracket trading on Kalshi hourlies."""

    def __init__(self, config: Optional[BracketRiskConfig] = None) -> None:
        self._config = config or DEFAULT_BRACKET_RISK_CONFIG
        self._state = BracketState()

    @property
    def config(self) -> BracketRiskConfig:
        return self._config

    @property
    def state(self) -> BracketState:
        return self._state

    @property
    def halted(self) -> bool:
        return self._state.halted

    # ── Per-asset hourly cap helpers ─────────────────────────────────

    def _asset_hour_notional(self, asset: str, hour_key: str) -> float:
        """Return current per-asset notional (cents) for the given hour."""
        return self._state.asset_hour_notional.get(asset, {}).get(hour_key, 0.0)

    def _log_asset_cap_status(self, asset: str, hour_key: str, incoming_notional: float) -> None:
        """Log exposure used vs cap and top-3 consuming markets for the asset."""
        cfg = self._config
        cap = cfg.per_asset_hour_caps_cents.get(asset.upper())
        if cap is None:
            return
        used = self._asset_hour_notional(asset, hour_key)
        top_markets = (
            self._state.asset_hour_markets
            .get(asset, {})
            .get(hour_key, [])
        )[:3]
        logger.info(
            "[bracket-risk] %s/%s exposure: %.0f¢ used + %.0f¢ incoming = %.0f¢ / %.0f¢ cap "
            "(%.0f%%) | top markets: %s",
            asset.upper(), hour_key,
            used, incoming_notional, used + incoming_notional, cap,
            (used + incoming_notional) / cap * 100 if cap > 0 else 0.0,
            top_markets or ["(none)"],
        )

    # ── Pre-trade check ──────────────────────────────────────────────

    def check_bracket_order(
        self,
        order: BracketOrder,
        session_equity_cents: float = 500_000.0,
    ) -> Tuple[bool, str]:
        """Run all bracket risk checks before placing an order.

        Args:
            order: The bracket order to check.
            session_equity_cents: Current session equity in cents.

        Returns:
            (allowed, reason)
        """
        cfg = self._config
        st = self._state

        # 1. Kill switch
        if st.halted:
            return False, f"Bracket halted: {st.halt_reason}"

        # 2. Max open brackets
        if len(st.open_brackets) >= cfg.max_open_brackets:
            return False, f"Max open brackets ({cfg.max_open_brackets}) reached"

        # 3. Per-bracket loss cap (% of equity)
        max_loss_allowed = session_equity_cents * (cfg.max_loss_per_contract_pct / 100.0) * order.contracts
        if order.max_loss_cents > max_loss_allowed:
            return False, (
                f"Bracket loss {order.max_loss_cents:.0f}c exceeds "
                f"{cfg.max_loss_per_contract_pct}% equity cap ({max_loss_allowed:.0f}c)"
            )

        # 4. Per-bracket absolute loss cap
        if order.max_loss_cents > cfg.max_loss_per_bracket_cents:
            return False, (
                f"Bracket loss {order.max_loss_cents:.0f}c exceeds "
                f"absolute cap {cfg.max_loss_per_bracket_cents:.0f}c"
            )

        # 5. Cross-bracket: contracts per hour
        hour_contracts = st.contracts_by_hour.get(order.hour_key, 0) + order.contracts
        if hour_contracts > cfg.max_contracts_per_hour:
            return False, (
                f"Hour {order.hour_key}: {hour_contracts} contracts "
                f"exceeds cap {cfg.max_contracts_per_hour}"
            )

        # 6. Cross-bracket: notional per hour
        notional = order.contracts * order.price_cents
        hour_notional = st.notional_by_hour.get(order.hour_key, 0.0) + notional
        if hour_notional > cfg.max_notional_per_hour_cents:
            return False, (
                f"Hour {order.hour_key}: notional {hour_notional:.0f}c "
                f"exceeds cap {cfg.max_notional_per_hour_cents:.0f}c"
            )

        # 7. Per-asset-per-hour notional cap (hard upper bound, resets each market hour)
        asset_upper = order.underlying.upper()
        if asset_upper in cfg.per_asset_hour_caps_cents:
            asset_cap = cfg.per_asset_hour_caps_cents[asset_upper]
            asset_used = self._asset_hour_notional(asset_upper, order.hour_key)
            if asset_used + notional > asset_cap:
                self._log_asset_cap_status(asset_upper, order.hour_key, notional)
                return False, (
                    f"{asset_upper}/1h notional {asset_used:.0f}¢ + {notional:.0f}¢ "
                    f"would exceed cap {asset_cap:.0f}¢"
                )
            self._log_asset_cap_status(asset_upper, order.hour_key, notional)

        # 8. Unhedged delta cap
        delta_change = order.contracts if order.side == "buy" else -order.contracts
        new_delta = st.net_delta + delta_change
        if abs(new_delta) > cfg.max_unhedged_delta:
            return False, (
                f"Net delta {new_delta} would exceed cap ±{cfg.max_unhedged_delta}"
            )

        return True, "OK"

    # ── Recording ────────────────────────────────────────────────────

    def record_bracket_open(self, order: BracketOrder) -> None:
        """Record a bracket being opened (after order is placed)."""
        st = self._state

        st.open_brackets.add(order.bracket_id)
        st.total_brackets += 1

        # Hour tracking
        if order.hour_key not in st.open_by_hour:
            st.open_by_hour[order.hour_key] = []
        st.open_by_hour[order.hour_key].append(order.bracket_id)

        st.contracts_by_hour[order.hour_key] = (
            st.contracts_by_hour.get(order.hour_key, 0) + order.contracts
        )
        notional = order.contracts * order.price_cents
        st.notional_by_hour[order.hour_key] = (
            st.notional_by_hour.get(order.hour_key, 0.0) + notional
        )

        # Per-asset-per-hour tracking (keyed by order's market hour_key)
        asset_upper = order.underlying.upper()
        if asset_upper not in st.asset_hour_notional:
            st.asset_hour_notional[asset_upper] = {}
        st.asset_hour_notional[asset_upper][order.hour_key] = (
            st.asset_hour_notional[asset_upper].get(order.hour_key, 0.0) + notional
        )
        if asset_upper not in st.asset_hour_markets:
            st.asset_hour_markets[asset_upper] = {}
        if order.hour_key not in st.asset_hour_markets[asset_upper]:
            st.asset_hour_markets[asset_upper][order.hour_key] = []
        st.asset_hour_markets[asset_upper][order.hour_key].append(order.ticker)

        # Delta
        delta_change = order.contracts if order.side == "buy" else -order.contracts
        st.net_delta += delta_change

    def record_bracket_result(
        self,
        bracket_id: str,
        pnl_cents: float,
        hour_key: Optional[str] = None,
    ) -> None:
        """Record a bracket settlement/close result.

        Args:
            bracket_id: The bracket that settled.
            pnl_cents: PnL in cents (positive = win, negative = loss).
            hour_key: Hour key for cleanup (optional).
        """
        st = self._state
        cfg = self._config

        st.open_brackets.discard(bracket_id)
        st.total_pnl_cents += pnl_cents

        if pnl_cents > 0:
            st.winning_brackets += 1
            st.consecutive_losers = 0
        elif pnl_cents < 0:
            st.losing_brackets += 1
            st.consecutive_losers += 1
            if st.consecutive_losers > st.max_consecutive_losers_seen:
                st.max_consecutive_losers_seen = st.consecutive_losers

        # Clean up hour tracking
        if hour_key and hour_key in st.open_by_hour:
            brackets = st.open_by_hour[hour_key]
            if bracket_id in brackets:
                brackets.remove(bracket_id)
            if not brackets:
                del st.open_by_hour[hour_key]
                st.contracts_by_hour.pop(hour_key, None)
                st.notional_by_hour.pop(hour_key, None)

        # Consecutive loser kill-switch
        if cfg.max_consecutive_losers > 0 and st.consecutive_losers >= cfg.max_consecutive_losers:
            st.halted = True
            st.halt_reason = (
                f"Consecutive losing brackets: {st.consecutive_losers} "
                f">= {cfg.max_consecutive_losers}"
            )
            logger.warning(f"[bracket-risk] HALTED: {st.halt_reason}")

    def record_hour_expired(self, hour_key: str) -> None:
        """Clean up state when an hour expires (all brackets in that hour settle)."""
        st = self._state
        if hour_key in st.open_by_hour:
            for bid in st.open_by_hour[hour_key]:
                st.open_brackets.discard(bid)
            del st.open_by_hour[hour_key]
        st.contracts_by_hour.pop(hour_key, None)
        st.notional_by_hour.pop(hour_key, None)

    # ── Controls ─────────────────────────────────────────────────────

    def reset_halt(self) -> None:
        """Reset the kill-switch (operator action after review)."""
        self._state.halted = False
        self._state.halt_reason = None
        self._state.consecutive_losers = 0
        logger.info("[bracket-risk] Halt reset by operator")

    # ── Summary ──────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """JSON-serializable bracket risk status."""
        st = self._state
        total = st.winning_brackets + st.losing_brackets
        win_rate = st.winning_brackets / total * 100 if total > 0 else 0.0

        return {
            "halted": st.halted,
            "halt_reason": st.halt_reason,
            "open_brackets": len(st.open_brackets),
            "total_brackets": st.total_brackets,
            "winning_brackets": st.winning_brackets,
            "losing_brackets": st.losing_brackets,
            "win_rate_pct": round(win_rate, 1),
            "total_pnl_cents": round(st.total_pnl_cents, 2),
            "total_pnl_usd": round(st.total_pnl_cents / 100, 2),
            "consecutive_losers": st.consecutive_losers,
            "max_consecutive_losers_seen": st.max_consecutive_losers_seen,
            "net_delta": st.net_delta,
            "hours_with_exposure": len(st.open_by_hour),
            "contracts_by_hour": dict(st.contracts_by_hour),
            "asset_exposure": self._asset_exposure_summary(),
            "config": {
                "max_loss_per_contract_pct": self._config.max_loss_per_contract_pct,
                "max_loss_per_bracket_cents": self._config.max_loss_per_bracket_cents,
                "max_contracts_per_hour": self._config.max_contracts_per_hour,
                "max_notional_per_hour_cents": self._config.max_notional_per_hour_cents,
                "per_asset_hour_caps_cents": dict(self._config.per_asset_hour_caps_cents),
                "max_consecutive_losers": self._config.max_consecutive_losers,
                "max_unhedged_delta": self._config.max_unhedged_delta,
                "max_open_brackets": self._config.max_open_brackets,
            },
        }

    def _asset_exposure_summary(self) -> Dict[str, Any]:
        """Return per-asset exposure vs cap across all tracked hours."""
        result: Dict[str, Any] = {}
        for asset, cap in self._config.per_asset_hour_caps_cents.items():
            hours_data: Dict[str, Any] = {}
            for hour_key, notional in self._state.asset_hour_notional.get(asset, {}).items():
                top3 = (
                    self._state.asset_hour_markets
                    .get(asset, {})
                    .get(hour_key, [])
                )[:3]
                hours_data[hour_key] = {
                    "used_cents": round(notional, 2),
                    "cap_cents": cap,
                    "utilization_pct": round(notional / cap * 100, 1) if cap > 0 else 0.0,
                    "top_markets": top3,
                }
            result[asset] = {
                "cap_cents": cap,
                "hours": hours_data,
            }
        return result
