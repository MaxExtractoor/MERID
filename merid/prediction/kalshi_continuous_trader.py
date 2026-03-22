"""KalshiContinuousTrader — Single-path crypto executor with Kelly sizing.

Subscribes to event_bus signals.crypto.* channels and applies:
- Fractional Kelly sizing (swarm size = upper bound)
- Correlation cap (40% total crypto notional)
- Liquidity gate (spread > 8¢ requires higher edge)
- Per-asset mode gating (MERID_ASSET_{ASSET}_MODE)

This is the single execution point for all crypto signals that have
already passed TradingAgent pre-execution gates.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
import math

from core.event_bus import event_stream
from merid.signals.unified_schema import ApprovedSignal
from utils.logger import get_logger


logger = get_logger("merid.prediction.kalshi_continuous_trader")


# ── Configuration constants ────────────────────────────────────────────

KELLY_FRACTION = float(os.getenv("MERID_KELLY_FRACTION", "0.25"))  # 25% fractional Kelly
CORRELATION_CAP_PCT = float(os.getenv("MERID_CORRELATION_CAP_PCT", "40"))  # 40% max crypto notional
LIQUIDITY_GATE_SPREAD_CENTS = float(os.getenv("MERID_LIQUIDITY_GATE_SPREAD_CENTS", "8.0"))  # 8¢ spread threshold
LIQUIDITY_GATE_MIN_EDGE = float(os.getenv("MERID_LIQUIDITY_GATE_MIN_EDGE", "0.08"))  # 8% min edge for wide spreads


@dataclass
class PortfolioState:
    """Current portfolio state for correlation/risk tracking."""
    total_equity_usd: float = 0.0
    crypto_notional_usd: float = 0.0  # Total crypto exposure
    per_asset_notional: Dict[str, float] = None  # Asset -> notional mapping

    def __post_init__(self):
        if self.per_asset_notional is None:
            self.per_asset_notional = {}

    @property
    def crypto_allocation_pct(self) -> float:
        """Current crypto allocation as % of equity."""
        if self.total_equity_usd <= 0:
            return 0.0
        return 100.0 * self.crypto_notional_usd / self.total_equity_usd

    @property
    def available_crypto_capacity_usd(self) -> float:
        """Remaining capacity before hitting correlation cap."""
        max_allowed = self.total_equity_usd * (CORRELATION_CAP_PCT / 100.0)
        return max(0.0, max_allowed - self.crypto_notional_usd)


class KalshiContinuousTrader:
    """
    Continuous trader that subscribes to approved crypto signals.

    Lifecycle:
        trader = KalshiContinuousTrader()
        await trader.start()  # Subscribes to event bus
        await trader.stop()   # Unsubscribes and shuts down
    """

    def __init__(self):
        self.logger = logger
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._queue: Optional[asyncio.Queue] = None

        # Portfolio state tracking
        self._portfolio = PortfolioState()

        # Signal tracking
        self._signals_processed = 0
        self._orders_placed = 0
        self._orders_blocked = 0

        # Per-asset mode overrides (MERID_ASSET_{ASSET}_MODE)
        self._asset_modes: Dict[str, str] = {}
        self._load_asset_modes()

    def _load_asset_modes(self) -> None:
        """Load per-asset mode overrides from environment."""
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            env_var = f"MERID_ASSET_{asset}_MODE"
            mode = os.getenv(env_var, "").lower()
            if mode in ("paper", "live"):
                self._asset_modes[asset] = mode
                self.logger.info(f"Asset mode override: {asset} -> {mode}")

    async def start(self) -> None:
        """Start the continuous trader."""
        if self._running:
            self.logger.warning("KalshiContinuousTrader already running")
            return

        self._running = True

        # Subscribe to all crypto signal channels
        self._queue = await event_stream.subscribe()

        # Start processing loop
        self._task = asyncio.create_task(self._run_loop(), name="kalshi-continuous-trader")

        # Sync initial portfolio state
        await self._sync_portfolio_state()

        self.logger.info(
            f"KalshiContinuousTrader started: kelly={KELLY_FRACTION}, "
            f"correlation_cap={CORRELATION_CAP_PCT}%, "
            f"liquidity_gate={LIQUIDITY_GATE_SPREAD_CENTS}¢"
        )

    async def stop(self) -> None:
        """Stop the continuous trader."""
        self._running = False

        if self._queue:
            await event_stream.unsubscribe(self._queue)
            self._queue = None

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self.logger.info(
            f"KalshiContinuousTrader stopped: "
            f"processed={self._signals_processed}, "
            f"placed={self._orders_placed}, "
            f"blocked={self._orders_blocked}"
        )

    async def _run_loop(self) -> None:
        """Main processing loop — consumes signals from event bus."""
        while self._running:
            try:
                if not self._queue:
                    break

                # Wait for next event with timeout
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                # Filter for crypto signal events
                if event["type"].startswith("signals.crypto."):
                    await self._process_signal(event["payload"])

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error(f"Signal processing error: {exc}", exc_info=True)
                await asyncio.sleep(1.0)  # Brief pause on error

    async def _process_signal(self, payload: Dict[str, Any]) -> None:
        """Process an approved crypto signal."""
        try:
            # Reconstruct signal from event payload
            signal = ApprovedSignal.from_dict(payload)

            self._signals_processed += 1
            self.logger.info(f"Processing signal: {signal.summary()}")

            # 1. Check per-asset mode override
            mode = self._get_asset_mode(signal.asset)
            if mode == "blocked":
                self.logger.info(f"Signal blocked by asset mode: {signal.asset}")
                self._orders_blocked += 1
                await self._record_blocked_signal(signal, "asset_mode_blocked")
                return

            # 2. Sync portfolio state (get fresh equity and exposures)
            await self._sync_portfolio_state()

            # 3. Apply correlation cap
            if not self._check_correlation_cap(signal):
                self.logger.info(
                    f"Signal blocked by correlation cap: "
                    f"current={self._portfolio.crypto_allocation_pct:.1f}%, "
                    f"max={CORRELATION_CAP_PCT}%"
                )
                self._orders_blocked += 1
                await self._record_blocked_signal(signal, "correlation_cap")
                return

            # 4. Apply liquidity gate
            if not self._check_liquidity_gate(signal):
                self.logger.info(
                    f"Signal blocked by liquidity gate: "
                    f"spread={signal.spread_bps/100:.1f}¢, edge={signal.edge:.2%}"
                )
                self._orders_blocked += 1
                await self._record_blocked_signal(signal, "liquidity_gate")
                return

            # 5. Calculate Kelly-optimal position size
            size_usd = self._calculate_kelly_size(signal)
            if size_usd <= 0:
                self.logger.debug(f"Kelly size <= 0, skipping signal")
                return

            # 6. Execute order via route_order_async
            await self._execute_order(signal, size_usd, mode)

        except Exception as exc:
            self.logger.error(f"Signal processing error: {exc}", exc_info=True)

    def _get_asset_mode(self, asset: str) -> str:
        """Get trading mode for a specific asset.

        Returns: "paper", "live", or "blocked"
        """
        # Check for explicit override
        if asset in self._asset_modes:
            return self._asset_modes[asset]

        # Fall back to global venue gate mode
        try:
            from merid.prediction.venue_gate import get_venue_gate
            gate = get_venue_gate()
            if gate.mode.value == "mock":
                return "blocked"
            return gate.mode.value
        except Exception:
            return "paper"  # Safe default

    async def _sync_portfolio_state(self) -> None:
        """Sync current portfolio equity and exposures."""
        try:
            # Get total equity from KalshiRiskManager
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            risk_mgr = get_kalshi_risk()

            if hasattr(risk_mgr, 'state'):
                self._portfolio.total_equity_usd = float(
                    getattr(risk_mgr.state, 'current_equity_usd', 0) or 0
                )

            # Get current crypto notional (sum of all open crypto positions)
            # For now, use a simple estimate from recent fills
            # TODO: Replace with actual position query from Kalshi
            self._portfolio.crypto_notional_usd = 0.0
            self._portfolio.per_asset_notional = {}

        except Exception as exc:
            self.logger.debug(f"Portfolio sync failed (using defaults): {exc}")
            # Use fallback defaults
            if self._portfolio.total_equity_usd == 0:
                try:
                    from merid.settings import settings
                    self._portfolio.total_equity_usd = float(
                        getattr(settings, 'PAPER_STARTING_BALANCE', 1000) or 1000
                    )
                except Exception:
                    self._portfolio.total_equity_usd = 1000.0

    def _check_correlation_cap(self, signal: ApprovedSignal) -> bool:
        """Check if adding this position would violate correlation cap."""
        # Estimate position size (conservative upper bound)
        estimated_notional = signal.contracts_upper_bound * (signal.limit_price_cents / 100.0)

        # Check if we have capacity
        if estimated_notional > self._portfolio.available_crypto_capacity_usd:
            return False

        return True

    def _check_liquidity_gate(self, signal: ApprovedSignal) -> bool:
        """Check liquidity conditions.

        Wide spreads (> 8¢) require higher edge (> 8%) to trade.
        """
        spread_cents = signal.spread_bps / 100.0

        if spread_cents > LIQUIDITY_GATE_SPREAD_CENTS:
            # Wide spread — need higher edge
            if abs(signal.edge) < LIQUIDITY_GATE_MIN_EDGE:
                return False

        return True

    def _calculate_kelly_size(self, signal: ApprovedSignal) -> float:
        """Calculate Kelly-optimal position size in USD.

        Uses fractional Kelly with signal edge and confidence.
        Respects swarm size_band as upper bound.
        """
        # Base Kelly formula: f = edge / odds
        # For binary options: f = (p*b - q) / b
        # where p = model_prob, q = 1-p, b = payoff odds

        p = signal.model_prob
        q = 1.0 - p
        price = signal.limit_price_cents / 100.0

        # Payoff odds for binary option
        if signal.direction == "yes":
            # Buying YES at price p: win (1-price), lose price
            b = (1.0 - price) / price if price > 0 else 0
        else:
            # Buying NO at price (1-p): win price, lose (1-price)
            b = price / (1.0 - price) if price < 1.0 else 0

        if b <= 0:
            return 0.0

        # Kelly fraction
        kelly_f = (p * b - q) / b

        # Adjust by confidence (reduce size for low confidence)
        kelly_f *= signal.confidence

        # Apply fractional Kelly
        kelly_f *= KELLY_FRACTION

        # Ensure non-negative
        kelly_f = max(0.0, kelly_f)

        # Calculate dollar size based on current equity
        base_size_usd = kelly_f * self._portfolio.total_equity_usd

        # Apply swarm size band multiplier
        size_multipliers = {
            "small": 0.25,
            "reduced": 0.5,
            "base": 1.0,
            "large": 1.5,
        }
        multiplier = size_multipliers.get(signal.swarm_size_band, 1.0)
        final_size_usd = base_size_usd * multiplier

        # Cap at swarm upper bound (converted to USD)
        upper_bound_usd = signal.contracts_upper_bound * (signal.limit_price_cents / 100.0)
        final_size_usd = min(final_size_usd, upper_bound_usd)

        # Cap at available correlation capacity
        final_size_usd = min(final_size_usd, self._portfolio.available_crypto_capacity_usd)

        self.logger.debug(
            f"Kelly sizing: base={base_size_usd:.2f}, "
            f"band={signal.swarm_size_band} ({multiplier}x), "
            f"final={final_size_usd:.2f} USD"
        )

        return final_size_usd

    async def _execute_order(
        self,
        signal: ApprovedSignal,
        size_usd: float,
        mode: str,
    ) -> None:
        """Execute order via route_order_async."""
        from merid.event_venues.kalshi.order_router import (
            OrderIntent,
            route_order_async,
            TradingMode,
        )

        # Convert size to contracts
        price = signal.limit_price_cents / 100.0
        contracts = max(1, int(math.ceil(size_usd / price)))

        # Map mode string to TradingMode enum
        mode_map = {
            "paper": TradingMode.PAPER,
            "live": TradingMode.LIVE,
            "mock": TradingMode.MOCK,
        }
        trading_mode = mode_map.get(mode, TradingMode.PAPER)

        # Build order intent
        intent = OrderIntent(
            ticker=signal.ticker,
            side=signal.direction,
            action="buy",  # Always buy for directional signals
            price_cents=signal.limit_price_cents,
            count=contracts,
            mode=trading_mode,
            edge_pct=signal.edge * 100,
            source=f"continuous_trader:{signal.agent_id}",
        )

        self.logger.info(
            f"Executing order: {signal.asset} {signal.tenor} {signal.direction} "
            f"{contracts}x @ {signal.limit_price_cents}¢ ({mode})"
        )

        # Route order
        try:
            result = await route_order_async(intent)

            if result.status.startswith("filled"):
                self._orders_placed += 1
                self.logger.info(f"Order filled: {result.status} - {result.fill}")

                # Update signal with fill details
                await self._record_fill(signal, result, contracts)
            else:
                self._orders_blocked += 1
                self.logger.warning(f"Order rejected: {result.reason}")
                await self._record_blocked_signal(signal, result.reason or "unknown")

        except Exception as exc:
            self._orders_blocked += 1
            self.logger.error(f"Order execution error: {exc}", exc_info=True)
            await self._record_blocked_signal(signal, f"execution_error: {exc}")

    async def _record_fill(
        self,
        signal: ApprovedSignal,
        result: Any,
        contracts: int,
    ) -> None:
        """Record fill in signal store for reflection."""
        try:
            from merid.signals.store import get_signal_store

            store = get_signal_store()

            # Update signal with fill info
            fill_data = result.fill or {}
            signal.executed = True
            signal.order_id = fill_data.get("order_id")
            signal.fill_price_cents = fill_data.get("price_cents", signal.limit_price_cents)
            signal.fill_contracts = contracts
            signal.fill_timestamp = datetime.now(timezone.utc)

            # Store approved signal (will be added to store schema next)
            # For now, just log
            self.logger.info(f"Fill recorded: {signal.summary()}")

        except Exception as exc:
            self.logger.debug(f"Fill recording error (non-fatal): {exc}")

    async def _record_blocked_signal(
        self,
        signal: ApprovedSignal,
        reason: str,
    ) -> None:
        """Record blocked signal for analysis."""
        try:
            # Store blocked signal with reason
            # TODO: Add to signal store schema
            self.logger.info(f"Signal blocked: {reason} - {signal.summary()}")

        except Exception as exc:
            self.logger.debug(f"Blocked signal recording error (non-fatal): {exc}")

    def summary(self) -> Dict[str, Any]:
        """Return summary stats for monitoring."""
        return {
            "running": self._running,
            "signals_processed": self._signals_processed,
            "orders_placed": self._orders_placed,
            "orders_blocked": self._orders_blocked,
            "portfolio": {
                "total_equity_usd": self._portfolio.total_equity_usd,
                "crypto_notional_usd": self._portfolio.crypto_notional_usd,
                "crypto_allocation_pct": self._portfolio.crypto_allocation_pct,
                "available_capacity_usd": self._portfolio.available_crypto_capacity_usd,
            },
            "config": {
                "kelly_fraction": KELLY_FRACTION,
                "correlation_cap_pct": CORRELATION_CAP_PCT,
                "liquidity_gate_spread_cents": LIQUIDITY_GATE_SPREAD_CENTS,
                "liquidity_gate_min_edge": LIQUIDITY_GATE_MIN_EDGE,
            },
            "asset_modes": self._asset_modes,
        }


# ── Singleton ─────────────────────────────────────────────────────────

_trader: Optional[KalshiContinuousTrader] = None


def get_kalshi_continuous_trader() -> KalshiContinuousTrader:
    """Get or create the singleton KalshiContinuousTrader instance."""
    global _trader
    if _trader is None:
        _trader = KalshiContinuousTrader()
    return _trader
