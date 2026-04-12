"""Fractional-Kelly Position Sizer — Adaptive sizing for Kalshi crypto contracts.

Computes optimal position size for bounded-loss binary contracts using
fractional Kelly criterion, adjusted for:
- Kalshi fee schedule (tiered by contract count)
- Measured profit factor and expectancy from paper sessions
- Per-cell and per-cluster exposure caps

Design principles from the playbook:
- Start with small fixed fractions (0.25–1%) rather than full Kelly
- Cap total exposure per underlying and per hour
- Only increase size gradually once PF and expectancy are stable
- Strategies with PF closer to 1.0 stay at minimum size

Usage::

    sizer = PositionSizer()
    size = sizer.compute("BTC_HOURLY", edge_pct=3.0, price_cents=55)
    # Returns contract count (integer)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.position_sizer")


@dataclass
class SizerConfig:
    """Configuration for the position sizer."""

    # Kelly fraction (0.0–1.0). 0.25 = quarter-Kelly (conservative default)
    kelly_fraction: float = 0.25

    # Minimum and maximum contracts per trade
    min_contracts: int = 1
    max_contracts: int = 50

    # Bankroll fraction caps
    max_bankroll_pct: float = 2.0     # Never risk more than 2% of bankroll per trade
    min_bankroll_pct: float = 0.25    # Floor: at least 0.25% when sizing is active

    # PF/expectancy gates for size scaling
    pf_min_for_scaling: float = 1.2   # Below this PF, use minimum size
    pf_full_kelly_at: float = 1.8     # At this PF, use full kelly_fraction
    expectancy_min_cents: float = 5.0 # Below this expectancy, use minimum size

    # Per-underlying hourly exposure cap (contracts)
    max_contracts_per_underlying_per_hour: int = 100

    # Minimum sample size before scaling up from minimum
    min_trades_for_scaling: int = 50


DEFAULT_SIZER_CONFIG = SizerConfig()


def kelly_fraction_for_binary(
    win_prob: float,
    win_payout: float,
    loss_amount: float,
) -> float:
    """Compute Kelly fraction for a binary outcome.

    For a binary contract:
    - You pay ``loss_amount`` (your cost) and win ``win_payout`` (100 - cost)
    - Kelly f* = (p * b - q) / b  where b = win_payout / loss_amount

    Args:
        win_prob: Estimated probability of winning (0–1)
        win_payout: Payout on win (e.g. 45 cents if you paid 55)
        loss_amount: Amount lost on loss (e.g. 55 cents, your cost)

    Returns:
        Kelly fraction (can be negative if edge is negative).
    """
    if loss_amount <= 0 or win_payout <= 0:
        return 0.0
    b = win_payout / loss_amount
    q = 1.0 - win_prob
    f = (win_prob * b - q) / b
    return f


def kalshi_fee_cents(price_cents: int, contracts: int) -> int:
    """Compute Kalshi fee for a trade (mirrors backtest fee calc)."""
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0
    payout = 100 - price_cents
    if contracts < 100:
        rate = 0.07
    elif contracts < 1000:
        rate = 0.05
    else:
        rate = 0.03
    per_contract = max(2, math.ceil(payout * rate))
    return per_contract * contracts


def adaptive_kelly_fraction(
    base_fraction: float,
    profit_factor: float = 0.0,
    max_drawdown_pct: float = 0.0,
    local_vol_pct: float = 0.0,
    *,
    pf_caution_threshold: float = 1.2,
    pf_danger_threshold: float = 1.05,
    dd_caution_threshold: float = 15.0,
    dd_danger_threshold: float = 25.0,
    vol_caution_threshold: float = 30.0,
    vol_danger_threshold: float = 50.0,
) -> float:
    """Compute a vol-aware, drawdown-aware adaptive Kelly fraction.

    Shrinks the base Kelly fraction when conditions deteriorate:

    - **PF < caution** (default 1.2): halve the fraction
    - **PF < danger** (default 1.05): quarter the fraction
    - **Drawdown > caution** (default 15%): halve the fraction
    - **Drawdown > danger** (default 25%): quarter the fraction
    - **Local vol > caution** (default 30%): reduce by 30%
    - **Local vol > danger** (default 50%): halve the fraction

    Multipliers stack multiplicatively so multiple bad signals
    compound into very small fractions.

    Args:
        base_fraction: Starting Kelly fraction (e.g. 0.25).
        profit_factor: Measured PF (0 = unknown, skipped).
        max_drawdown_pct: Current drawdown as percentage (0-100).
        local_vol_pct: Recent PnL volatility as percentage (0-100).
        pf_caution_threshold: PF below which fraction is halved.
        pf_danger_threshold: PF below which fraction is quartered.
        dd_caution_threshold: Drawdown % above which fraction is halved.
        dd_danger_threshold: Drawdown % above which fraction is quartered.
        vol_caution_threshold: Vol % above which fraction is reduced 30%.
        vol_danger_threshold: Vol % above which fraction is halved.

    Returns:
        Adjusted Kelly fraction (>= 0).
    """
    frac = base_fraction

    # PF-based shrinkage (only when PF is known)
    if profit_factor > 0:
        if profit_factor < pf_danger_threshold:
            frac *= 0.25
        elif profit_factor < pf_caution_threshold:
            frac *= 0.5

    # Drawdown-based shrinkage
    if max_drawdown_pct > dd_danger_threshold:
        frac *= 0.25
    elif max_drawdown_pct > dd_caution_threshold:
        frac *= 0.5

    # Volatility-based shrinkage
    if local_vol_pct > vol_danger_threshold:
        frac *= 0.5
    elif local_vol_pct > vol_caution_threshold:
        frac *= 0.7

    return max(0.0, frac)


def vol_scaled_fraction(
    base_fraction: float,
    realized_vol: float,
    target_vol: float = 0.02,
    min_scale: float = 0.25,
    max_scale: float = 1.0,
) -> float:
    """Volatility-targeted Kelly fraction scaling.

    Continuously modulates the Kelly fraction using the ratio of
    target volatility to realized volatility. Higher realized vol
    results in a smaller effective fraction, keeping strategy-level
    volatility approximately constant.

    This mirrors "volatility-regulated Kelly" — instead of discrete
    threshold-based shrinkage (like adaptive_kelly_fraction), this
    provides smooth, continuous scaling.

    Args:
        base_fraction: Starting Kelly fraction (e.g. 0.25).
        realized_vol: Realized hourly/daily vol of strategy returns
            (e.g. 0.02 for 2%).
        target_vol: Desired volatility level (e.g. 0.02 for 2%).
        min_scale: Floor for the scaling factor (default 0.25).
        max_scale: Ceiling for the scaling factor (default 1.0).

    Returns:
        Scaled Kelly fraction (>= 0).
    """
    if realized_vol <= 0:
        return 0.0
    scale = target_vol / realized_vol
    scale = max(min_scale, min(scale, max_scale))
    return base_fraction * scale


def atr_risk_fraction(
    account_risk_pct: float,
    atr: float,
    atr_unit: float,
    max_risk_pct: float = 0.02,
) -> float:
    """ATR-based position sizing for BTC hourly contracts.

    Scales risk inversely proportional to current ATR. When ATR is high
    (volatile market), position size shrinks; when ATR is low, size grows
    up to the account risk cap.

    For Kalshi binaries, `atr_unit` represents the BTC price move that
    historically maps to a large loss on the bracket/hourly contract
    (e.g., if a $500 BTC move ≈ full contract loss, atr_unit = 500).

    This complements `vol_scaled_fraction` (return-based vol) by using
    BTC spot candle data (High/Low/Close) instead of strategy returns.

    Args:
        account_risk_pct: Max fraction of equity to risk per trade
            (e.g. 0.01 for 1%).
        atr: Current ATR value in same units as atr_unit.
        atr_unit: Underlying price move corresponding to full contract
            loss (e.g. 500 for $500 BTC move).
        max_risk_pct: Hard cap on risk fraction (default 2%).

    Returns:
        Risk fraction (0 to max_risk_pct).
    """
    if atr <= 0 or atr_unit <= 0:
        return 0.0
    frac = account_risk_pct * atr_unit / atr
    return min(frac, max_risk_pct)


class PositionSizer:
    """Adaptive position sizer for Kalshi binary contracts.

    Combines Kelly criterion with PF/expectancy-based scaling gates
    and exposure caps from the paper session risk framework.
    """

    def __init__(self, config: Optional[SizerConfig] = None) -> None:
        self._config = config or DEFAULT_SIZER_CONFIG
        # Runtime state exposed to the API layer
        self._manual_override_factor: float = 1.0   # operator downsize factor (0-1)
        self._realized_vol: float = 0.02             # rolling realized vol (fraction)
        self._target_vol: float = 0.02               # vol target (fraction)
        self._atr_value: float = 0.0                 # latest ATR reading
        self._atr_fraction: float = 0.0              # ATR-derived risk fraction
        self._kelly_util_pct: float = 0.0            # rolling avg Kelly utilization %

    # ── Runtime properties (read by sizing-metrics API) ──────────────────

    @property
    def kelly_fraction(self) -> float:
        """Base Kelly fraction from config."""
        return self._config.kelly_fraction

    @property
    def effective_fraction(self) -> float:
        """Effective Kelly fraction after manual override."""
        return self._config.kelly_fraction * self._manual_override_factor

    @property
    def vol_scale(self) -> float:
        """Current vol-targeting scale factor (target_vol / realized_vol)."""
        if self._realized_vol <= 0:
            return 1.0
        return min(1.0, max(0.25, self._target_vol / self._realized_vol))

    @property
    def target_vol(self) -> float:
        return self._target_vol

    @property
    def realized_vol(self) -> float:
        return self._realized_vol

    @property
    def atr_value(self) -> float:
        return self._atr_value

    @property
    def atr_fraction(self) -> float:
        return self._atr_fraction

    @property
    def kelly_utilization_pct(self) -> float:
        return self._kelly_util_pct

    # ── Operator controls ────────────────────────────────────────────────

    def apply_manual_override(
        self,
        factor: float,
        asset: Optional[str] = None,  # noqa: ARG002 — reserved for per-asset overrides
    ) -> None:
        """Reduce effective Kelly fraction by ``factor`` (0.1–1.0).

        Args:
            factor: Multiplicative reduction (e.g. 0.5 = halve sizing).
            asset: Reserved for future per-asset overrides (ignored for now).
        """
        self._manual_override_factor = max(0.0, min(1.0, float(factor)))
        logger.info(f"PositionSizer manual override applied: factor={self._manual_override_factor:.3f}")

    def reset_override(self) -> None:
        """Reset manual override back to full sizing."""
        self._manual_override_factor = 1.0

    def update_vol_state(
        self,
        realized_vol: float,
        atr_value: float = 0.0,
        atr_fraction: float = 0.0,
        kelly_util_pct: float = 0.0,
    ) -> None:
        """Update runtime vol/ATR state (called by portfolio risk agent)."""
        self._realized_vol = max(0.0, realized_vol)
        self._atr_value = max(0.0, atr_value)
        self._atr_fraction = max(0.0, atr_fraction)
        self._kelly_util_pct = max(0.0, kelly_util_pct)

    def compute(
        self,
        agent_name: str,
        edge_pct: float,
        price_cents: int,
        bankroll_cents: int = 500_000,
        *,
        profit_factor: float = 0.0,
        expectancy_cents: float = 0.0,
        total_trades: int = 0,
        current_exposure_contracts: int = 0,
        size_factor: float = 1.0,
        max_drawdown_pct: float = 0.0,
        local_vol_pct: float = 0.0,
    ) -> int:
        """Compute position size in contracts.

        Args:
            agent_name: Cell name (e.g. "BTC_HOURLY") for logging
            edge_pct: Estimated edge as percentage (e.g. 3.0 means 3% edge)
            price_cents: Contract price in cents (1–99)
            bankroll_cents: Total session bankroll in cents
            profit_factor: Measured PF from paper session (0 = unknown)
            expectancy_cents: Measured expectancy per trade in cents
            total_trades: Number of trades in paper session (for sample gate)
            current_exposure_contracts: Current open contracts for this underlying
            size_factor: From paper session risk governance (0.0 if halted, 0.5 if downsized)
            max_drawdown_pct: Current drawdown as percentage (0-100) for adaptive Kelly
            local_vol_pct: Recent PnL volatility as percentage (0-100) for adaptive Kelly

        Returns:
            Integer contract count (0 if trade should be skipped).
        """
        cfg = self._config

        # Halted or zero factor → no trade
        if size_factor <= 0:
            return 0

        # Validate price
        if price_cents <= 0 or price_cents >= 100:
            return 0

        # ── Kelly sizing ──────────────────────────────────────────
        win_payout = 100 - price_cents  # cents won on correct prediction
        loss_amount = price_cents       # cents lost on wrong prediction

        # Convert edge to win probability
        # edge_pct = (true_prob - implied_prob) * 100
        implied_prob = price_cents / 100.0
        est_win_prob = implied_prob + (edge_pct / 100.0)
        est_win_prob = max(0.01, min(0.99, est_win_prob))

        raw_kelly = kelly_fraction_for_binary(est_win_prob, win_payout, loss_amount)

        if raw_kelly <= 0:
            # Negative edge → don't trade
            return 0

        # Apply fractional Kelly with adaptive shrinkage
        adapted_fraction = adaptive_kelly_fraction(
            cfg.kelly_fraction,
            profit_factor=profit_factor,
            max_drawdown_pct=max_drawdown_pct,
            local_vol_pct=local_vol_pct,
        )
        f = raw_kelly * adapted_fraction

        # ── PF/expectancy scaling gate ────────────────────────────
        scale = self._pf_scale(profit_factor, expectancy_cents, total_trades)
        if scale <= 0:
            return 0
        f *= scale

        # ── Convert fraction to contracts ─────────────────────────
        # f = fraction of bankroll to risk
        # risk per contract = loss_amount cents
        # Include fee estimate — use the actual contract count for tiered fees
        # FIX-FEE: Previously used kalshi_fee_cents(price_cents, 1) which always
        # applied the lowest tier (<100 contracts) regardless of actual size.
        # Now we estimate contracts first, then compute fees at the correct tier.

        # Initial rough contract estimate (fee-free) for tier lookup
        rough_risk = loss_amount  # per-contract risk without fee
        if rough_risk <= 0:
            return 0
        rough_contracts = max(1, int((f * bankroll_cents) / rough_risk))

        fee_per_contract_cents = kalshi_fee_cents(price_cents, rough_contracts)
        # Per-contract fee = total fee / contracts
        fee_per_contract = fee_per_contract_cents / rough_contracts if rough_contracts > 0 else 0
        risk_per_contract = loss_amount + fee_per_contract

        if risk_per_contract <= 0:
            return 0

        bankroll_risk = f * bankroll_cents
        contracts_from_kelly = int(bankroll_risk / risk_per_contract)

        # ── Apply caps ────────────────────────────────────────────
        # Bankroll percentage cap
        max_from_bankroll = int(
            (cfg.max_bankroll_pct / 100.0) * bankroll_cents / risk_per_contract
        )
        contracts = min(contracts_from_kelly, max_from_bankroll)

        # Absolute contract limits
        contracts = max(cfg.min_contracts, min(contracts, cfg.max_contracts))

        # Per-underlying hourly exposure cap
        remaining_capacity = max(
            0,
            cfg.max_contracts_per_underlying_per_hour - current_exposure_contracts,
        )
        contracts = min(contracts, remaining_capacity)

        # Apply size_factor from risk governance (e.g. 0.5 for downsized)
        # FIX-SIZEFACTOR: Previously max(1, ...) forced a minimum of 1 contract
        # even when size_factor intended to reduce to 0 (e.g. 1 * 0.5 = 0).
        # Now allows zero contracts when risk governance demands full downsize.
        contracts = int(contracts * size_factor)
        if contracts <= 0 and size_factor > 0:
            # If size_factor is positive but rounding eliminated the trade,
            # allow minimum of 1 contract to avoid silently dropping all trades.
            contracts = 1

        # Final bounds
        contracts = max(0, min(contracts, cfg.max_contracts))

        return contracts

    def _pf_scale(
        self,
        profit_factor: float,
        expectancy_cents: float,
        total_trades: int,
    ) -> float:
        """Compute a 0–1 scaling factor based on measured PF and expectancy.

        - Below min sample size → minimum scale
        - Below PF floor → minimum scale
        - Negative expectancy → 0 (don't trade)
        - Linear ramp from pf_min_for_scaling to pf_full_kelly_at
        """
        cfg = self._config

        # Negative expectancy → don't trade at all
        if expectancy_cents < 0 and total_trades >= cfg.min_trades_for_scaling:
            return 0.0

        # Not enough data → use minimum scale
        if total_trades < cfg.min_trades_for_scaling:
            return cfg.min_bankroll_pct / cfg.max_bankroll_pct

        # Below expectancy floor → minimum scale
        if expectancy_cents < cfg.expectancy_min_cents:
            return cfg.min_bankroll_pct / cfg.max_bankroll_pct

        # PF-based linear ramp
        if profit_factor <= 0 or profit_factor < cfg.pf_min_for_scaling:
            return cfg.min_bankroll_pct / cfg.max_bankroll_pct

        if profit_factor >= cfg.pf_full_kelly_at:
            return 1.0

        # Linear interpolation between min and full
        range_pf = cfg.pf_full_kelly_at - cfg.pf_min_for_scaling
        progress = (profit_factor - cfg.pf_min_for_scaling) / range_pf
        min_scale = cfg.min_bankroll_pct / cfg.max_bankroll_pct
        return min_scale + progress * (1.0 - min_scale)

    def explain(
        self,
        agent_name: str,
        edge_pct: float,
        price_cents: int,
        bankroll_cents: int = 500_000,
        *,
        profit_factor: float = 0.0,
        expectancy_cents: float = 0.0,
        total_trades: int = 0,
        current_exposure_contracts: int = 0,
        size_factor: float = 1.0,
        max_drawdown_pct: float = 0.0,
        local_vol_pct: float = 0.0,
    ) -> Dict[str, Any]:
        """Compute size and return a detailed explanation dict."""
        cfg = self._config

        implied_prob = price_cents / 100.0
        est_win_prob = max(0.01, min(0.99, implied_prob + edge_pct / 100.0))
        win_payout = 100 - price_cents
        loss_amount = price_cents

        raw_kelly = kelly_fraction_for_binary(est_win_prob, win_payout, loss_amount)
        adapted_fraction = adaptive_kelly_fraction(
            cfg.kelly_fraction,
            profit_factor=profit_factor,
            max_drawdown_pct=max_drawdown_pct,
            local_vol_pct=local_vol_pct,
        )
        fractional_kelly = raw_kelly * adapted_fraction
        pf_scale = self._pf_scale(profit_factor, expectancy_cents, total_trades)

        contracts = self.compute(
            agent_name, edge_pct, price_cents, bankroll_cents,
            profit_factor=profit_factor,
            expectancy_cents=expectancy_cents,
            total_trades=total_trades,
            current_exposure_contracts=current_exposure_contracts,
            size_factor=size_factor,
            max_drawdown_pct=max_drawdown_pct,
            local_vol_pct=local_vol_pct,
        )

        fee_per_contract = kalshi_fee_cents(price_cents, 1)
        risk_per_contract = loss_amount + fee_per_contract

        return {
            "agent": agent_name,
            "contracts": contracts,
            "edge_pct": edge_pct,
            "price_cents": price_cents,
            "implied_prob": round(implied_prob, 4),
            "est_win_prob": round(est_win_prob, 4),
            "raw_kelly": round(raw_kelly, 6),
            "fractional_kelly": round(fractional_kelly, 6),
            "kelly_fraction_config": cfg.kelly_fraction,
            "adapted_kelly_fraction": round(adapted_fraction, 6),
            "max_drawdown_pct": max_drawdown_pct,
            "local_vol_pct": local_vol_pct,
            "pf_scale": round(pf_scale, 4),
            "profit_factor": profit_factor,
            "expectancy_cents": expectancy_cents,
            "total_trades": total_trades,
            "risk_per_contract_cents": risk_per_contract,
            "fee_per_contract_cents": fee_per_contract,
            "bankroll_cents": bankroll_cents,
            "size_factor": size_factor,
            "current_exposure": current_exposure_contracts,
        }


# ── Kelly utilization tracker ────────────────────────────────────────────

class KellyUtilizationTracker:
    """Tracks actual vs theoretical Kelly fraction per trade.

    Records each trade's theoretical full-Kelly fraction, the adapted
    fraction actually used, and the effective bankroll percentage risked.
    Reports rolling utilization metrics for monitoring and promotion gates.

    Usage::

        tracker = KellyUtilizationTracker()
        tracker.record(raw_kelly=0.12, adapted_fraction=0.03,
                       contracts=5, risk_per_contract_cents=57,
                       bankroll_cents=500_000)
        tracker.summary()
    """

    def __init__(self, window_size: int = 200) -> None:
        self._window_size = window_size
        self._records: list[Dict[str, float]] = []

    def record(
        self,
        raw_kelly: float,
        adapted_fraction: float,
        contracts: int,
        risk_per_contract_cents: float,
        bankroll_cents: float,
    ) -> None:
        """Record one trade's Kelly utilization.

        Args:
            raw_kelly: Full Kelly fraction (before fractional/adaptive).
            adapted_fraction: The Kelly fraction actually used (after
                adaptive shrinkage).
            contracts: Contracts actually sized.
            risk_per_contract_cents: Risk per contract including fees.
            bankroll_cents: Total bankroll at time of trade.
        """
        actual_risked_pct = 0.0
        if bankroll_cents > 0:
            actual_risked_pct = (contracts * risk_per_contract_cents) / bankroll_cents * 100

        theoretical_risk_pct = raw_kelly * 100

        utilization = 0.0
        if raw_kelly > 0:
            utilization = (adapted_fraction / raw_kelly) * 100

        self._records.append({
            "raw_kelly": raw_kelly,
            "adapted_fraction": adapted_fraction,
            "actual_risked_pct": actual_risked_pct,
            "theoretical_risk_pct": theoretical_risk_pct,
            "utilization_pct": utilization,
            "contracts": float(contracts),
        })

        if len(self._records) > self._window_size:
            self._records = self._records[-self._window_size:]

    def summary(self) -> Dict[str, Any]:
        """Rolling summary of Kelly utilization metrics."""
        if not self._records:
            return {
                "trade_count": 0,
                "avg_raw_kelly_pct": 0.0,
                "avg_adapted_fraction_pct": 0.0,
                "avg_actual_risked_pct": 0.0,
                "avg_utilization_pct": 0.0,
                "avg_contracts": 0.0,
            }

        n = len(self._records)
        return {
            "trade_count": n,
            "avg_raw_kelly_pct": round(
                sum(r["raw_kelly"] for r in self._records) / n * 100, 4
            ),
            "avg_adapted_fraction_pct": round(
                sum(r["adapted_fraction"] for r in self._records) / n * 100, 4
            ),
            "avg_actual_risked_pct": round(
                sum(r["actual_risked_pct"] for r in self._records) / n, 4
            ),
            "avg_utilization_pct": round(
                sum(r["utilization_pct"] for r in self._records) / n, 2
            ),
            "avg_contracts": round(
                sum(r["contracts"] for r in self._records) / n, 1
            ),
        }

    @property
    def trade_count(self) -> int:
        return len(self._records)

    def reset(self) -> None:
        self._records.clear()


# ── Singleton ────────────────────────────────────────────────────────────

_sizer: Optional[PositionSizer] = None


def get_position_sizer(config: Optional[SizerConfig] = None) -> PositionSizer:
    """Get or create the singleton PositionSizer."""
    global _sizer
    if _sizer is None:
        _sizer = PositionSizer(config)
    return _sizer
