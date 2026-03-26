"""SizingProtection — Safe Kelly calculation and position limit enforcement.

Implements critical fixes:
- S-001 (HIGH): Division by zero protection in Kelly calculation
- S-002 (HIGH): Position cap override for edge cases

Protects against:
1. Division by zero when loss_amount or win_payout = 0
2. Kelly recommending 1000+ contracts on extremely mispriced markets
3. Bankroll decimation from oversized positions
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.sizing_protection")


@dataclass
class KellyResult:
    """Result of Kelly sizing calculation."""
    contracts: int
    kelly_fraction: float
    edge: float
    price_cents: int
    capped: bool
    cap_reason: Optional[str] = None
    error: Optional[str] = None


class SafeKellyCalculator:
    """Safe Kelly position sizing with edge case protection.

    Prevents:
    1. Division by zero (S-001)
    2. Runaway position sizes (S-002)
    3. Negative position sizes
    4. Non-finite results (NaN, Inf)
    """

    def __init__(
        self,
        *,
        absolute_max_contracts: int = 500,
        max_bankroll_fraction: float = 0.10,
        min_edge_for_sizing: float = 0.01,
        default_kelly_fraction: float = 0.25,
    ):
        """Initialize safe Kelly calculator.

        Args:
            absolute_max_contracts: Hard cap on contracts (default 500)
            max_bankroll_fraction: Max fraction of bankroll per trade (default 10%)
            min_edge_for_sizing: Minimum edge required to trade (default 1%)
            default_kelly_fraction: Fractional Kelly (default 0.25 = quarter Kelly)
        """
        self.absolute_max_contracts = absolute_max_contracts
        self.max_bankroll_fraction = max_bankroll_fraction
        self.min_edge_for_sizing = min_edge_for_sizing
        self.default_kelly_fraction = default_kelly_fraction

        # Stats
        self.total_calculations = 0
        self.total_capped = 0
        self.total_errors = 0

    def calculate_safe_kelly(
        self,
        edge: float,
        price_cents: int,
        bankroll_cents: int,
        *,
        kelly_fraction: Optional[float] = None,
        fee_rate: float = 0.07,
    ) -> KellyResult:
        """Calculate Kelly position size with comprehensive safety checks.

        Args:
            edge: Expected edge (probability advantage, e.g., 0.05 for 5%)
            price_cents: Contract price in cents (0-99)
            bankroll_cents: Total bankroll in cents
            kelly_fraction: Fractional Kelly multiplier (default 0.25)
            fee_rate: Fee rate for this trade (default 0.07 = 7%)

        Returns:
            KellyResult with safe position size
        """
        self.total_calculations += 1

        if kelly_fraction is None:
            kelly_fraction = self.default_kelly_fraction

        # ── Input validation ────────────────────────────────────────────

        # Check for invalid inputs
        if bankroll_cents <= 0:
            self.total_errors += 1
            logger.error(f"Invalid bankroll: {bankroll_cents} cents")
            return KellyResult(
                contracts=0,
                kelly_fraction=0.0,
                edge=edge,
                price_cents=price_cents,
                capped=True,
                cap_reason="Invalid bankroll",
                error="Bankroll must be positive",
            )

        if price_cents <= 0 or price_cents >= 100:
            self.total_errors += 1
            logger.error(f"Invalid price: {price_cents} cents (must be 1-99)")
            return KellyResult(
                contracts=0,
                kelly_fraction=0.0,
                edge=edge,
                price_cents=price_cents,
                capped=True,
                cap_reason="Invalid price",
                error="Price must be in range [1, 99]",
            )

        if edge < self.min_edge_for_sizing:
            # Edge too small to trade
            return KellyResult(
                contracts=0,
                kelly_fraction=0.0,
                edge=edge,
                price_cents=price_cents,
                capped=True,
                cap_reason=f"Edge {edge:.3f} < min {self.min_edge_for_sizing:.3f}",
            )

        # ── Kelly calculation with safety checks ───────────────────────

        # Binary contract Kelly: f* = (p × b - q) / b
        # where p = win_prob, q = 1-p, b = win_payout / loss_amount

        # Calculate win/loss amounts
        loss_amount = price_cents  # Cost per contract
        win_payout = 100 - price_cents  # Payout per winning contract

        # S-001 FIX: Check for division by zero
        if loss_amount == 0 or win_payout == 0:
            self.total_errors += 1
            logger.warning(
                f"Division by zero in Kelly: loss_amount={loss_amount}, win_payout={win_payout}. "
                f"This indicates a degenerate price (0 or 100 cents)."
            )
            return KellyResult(
                contracts=0,
                kelly_fraction=0.0,
                edge=edge,
                price_cents=price_cents,
                capped=True,
                cap_reason="Division by zero (degenerate price)",
                error="Cannot size position at price 0 or 100",
            )

        # Calculate probabilities
        implied_prob = price_cents / 100.0
        model_prob = implied_prob + edge  # Our probability estimate

        # Sanity check model probability
        if model_prob <= 0 or model_prob >= 1:
            self.total_errors += 1
            logger.warning(
                f"Invalid model probability: {model_prob:.3f} (implied={implied_prob:.3f}, edge={edge:.3f})"
            )
            return KellyResult(
                contracts=0,
                kelly_fraction=0.0,
                edge=edge,
                price_cents=price_cents,
                capped=True,
                cap_reason="Invalid model probability",
                error=f"Model probability {model_prob:.3f} outside [0, 1]",
            )

        # Calculate Kelly fraction
        p = model_prob
        q = 1.0 - p
        b = win_payout / loss_amount  # Odds ratio

        # Full Kelly: f* = (p × b - q) / b
        kelly_full = (p * b - q) / b

        # Apply fractional Kelly and fee adjustment
        kelly_after_fraction = kelly_full * kelly_fraction
        kelly_after_fees = kelly_after_fraction * (1.0 - fee_rate)

        # Check for non-finite results
        if not math.isfinite(kelly_after_fees):
            self.total_errors += 1
            logger.error(
                f"Non-finite Kelly result: {kelly_after_fees} "
                f"(p={p:.3f}, b={b:.3f}, kelly_fraction={kelly_fraction:.3f})"
            )
            return KellyResult(
                contracts=0,
                kelly_fraction=0.0,
                edge=edge,
                price_cents=price_cents,
                capped=True,
                cap_reason="Non-finite Kelly result",
                error="Kelly calculation produced NaN or Inf",
            )

        # Clamp Kelly to [0, max_bankroll_fraction]
        kelly_clamped = max(0.0, min(self.max_bankroll_fraction, kelly_after_fees))

        # Calculate contract quantity
        contracts_raw = (kelly_clamped * bankroll_cents) / price_cents
        contracts = int(math.floor(contracts_raw))

        # S-002 FIX: Apply absolute position cap
        capped = False
        cap_reason = None

        if contracts > self.absolute_max_contracts:
            capped = True
            cap_reason = f"Absolute cap: {contracts} → {self.absolute_max_contracts}"
            contracts = self.absolute_max_contracts
            self.total_capped += 1

        # Additional sanity: never exceed 10% of bankroll in notional
        max_contracts_by_bankroll = int((bankroll_cents * self.max_bankroll_fraction) / price_cents)
        if contracts > max_contracts_by_bankroll:
            capped = True
            cap_reason = f"Bankroll limit: {contracts} → {max_contracts_by_bankroll}"
            contracts = max_contracts_by_bankroll
            self.total_capped += 1

        return KellyResult(
            contracts=contracts,
            kelly_fraction=kelly_clamped,
            edge=edge,
            price_cents=price_cents,
            capped=capped,
            cap_reason=cap_reason,
        )


# ── Singleton ────────────────────────────────────────────────────────────────


_safe_kelly: Optional[SafeKellyCalculator] = None


def get_safe_kelly_calculator() -> SafeKellyCalculator:
    """Get singleton SafeKellyCalculator."""
    global _safe_kelly
    if _safe_kelly is None:
        _safe_kelly = SafeKellyCalculator()
    return _safe_kelly
