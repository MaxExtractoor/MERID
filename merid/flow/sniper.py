"""MEV-aware sniper execution engine for the flow domain.

Handles:
  - Pre-trade simulation (price impact, slippage, liquidity checks)
  - Route selection (standard vs MEV-protected vs private tx)
  - Constraint enforcement (slippage, gas, impact, liquidity)
  - Fill tracking and MEV incident detection
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from merid.flow.models import (
    Chain,
    MevRiskTolerance,
    PlanStatus,
    RouteType,
    SniperFill,
    SniperOrder,
    Token,
    estimate_price_impact,
    _now,
    _uid,
)


# ── Route configuration ──────────────────────────────────────────────

@dataclass
class RouteConfig:
    """Configuration for a DEX/MEV route."""
    chain: str
    route_type: str
    dex_router: str
    mev_relay: str = ""
    priority_fee_multiplier: float = 1.0
    is_healthy: bool = True
    avg_latency_ms: float = 200.0
    failure_rate: float = 0.0


# Default routes per chain
DEFAULT_ROUTES: Dict[str, List[RouteConfig]] = {
    Chain.SOLANA.value: [
        RouteConfig(
            chain="solana", route_type=RouteType.MEV_PROTECTED.value,
            dex_router="jupiter", mev_relay="jito",
            priority_fee_multiplier=1.5, avg_latency_ms=150,
        ),
        RouteConfig(
            chain="solana", route_type=RouteType.STANDARD.value,
            dex_router="jupiter", avg_latency_ms=100,
        ),
        RouteConfig(
            chain="solana", route_type=RouteType.STANDARD.value,
            dex_router="raydium", avg_latency_ms=120,
        ),
    ],
    Chain.ETHEREUM.value: [
        RouteConfig(
            chain="ethereum", route_type=RouteType.PRIVATE_TX.value,
            dex_router="1inch", mev_relay="flashbots",
            priority_fee_multiplier=2.0, avg_latency_ms=2000,
        ),
        RouteConfig(
            chain="ethereum", route_type=RouteType.MEV_PROTECTED.value,
            dex_router="uniswap_v3", mev_relay="mev_blocker",
            priority_fee_multiplier=1.3, avg_latency_ms=1500,
        ),
        RouteConfig(
            chain="ethereum", route_type=RouteType.STANDARD.value,
            dex_router="uniswap_v3", avg_latency_ms=800,
        ),
    ],
    Chain.BASE.value: [
        RouteConfig(
            chain="base", route_type=RouteType.STANDARD.value,
            dex_router="uniswap_v3", avg_latency_ms=300,
        ),
        RouteConfig(
            chain="base", route_type=RouteType.STANDARD.value,
            dex_router="aerodrome", avg_latency_ms=350,
        ),
    ],
    Chain.ARBITRUM.value: [
        RouteConfig(
            chain="arbitrum", route_type=RouteType.STANDARD.value,
            dex_router="uniswap_v3", avg_latency_ms=250,
        ),
        RouteConfig(
            chain="arbitrum", route_type=RouteType.STANDARD.value,
            dex_router="camelot", avg_latency_ms=280,
        ),
    ],
}


# ── Simulation result ─────────────────────────────────────────────────

@dataclass
class SimulationResult:
    """Result of a pre-trade simulation."""
    passed: bool = False
    reason: str = ""
    estimated_price_impact: float = 0.0
    estimated_output_tokens: float = 0.0
    estimated_gas_usd: float = 0.0
    recommended_route: Optional[RouteConfig] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


# ── SniperExecutor ────────────────────────────────────────────────────

class SniperExecutor:
    """MEV-aware sniper execution engine.

    Lifecycle:
      1. simulate(order) → SimulationResult (check constraints)
      2. execute(order) → SniperFill (submit via route, track fill)
    """

    def __init__(self):
        self._routes = dict(DEFAULT_ROUTES)
        self._is_live = os.environ.get("MERID_FLOW_LIVE", "").lower() in ("1", "true", "yes")

    @property
    def is_live(self) -> bool:
        return self._is_live

    def get_routes(self, chain: str) -> List[RouteConfig]:
        return self._routes.get(chain, [])

    def select_route(
        self, chain: str, mev_tolerance: str, size_usd: float,
    ) -> Optional[RouteConfig]:
        """Select best route based on chain, MEV tolerance, and order size.

        - LOW tolerance → prefer MEV-protected / private tx
        - MEDIUM → prefer MEV-protected, fall back to standard
        - HIGH → use standard (fastest, cheapest)
        """
        routes = [r for r in self.get_routes(chain) if r.is_healthy]
        if not routes:
            return None

        if mev_tolerance == MevRiskTolerance.LOW.value:
            # Prefer private tx > mev_protected > standard
            for rt in (RouteType.PRIVATE_TX.value, RouteType.MEV_PROTECTED.value, RouteType.STANDARD.value):
                match = [r for r in routes if r.route_type == rt]
                if match:
                    return match[0]
        elif mev_tolerance == MevRiskTolerance.MEDIUM.value:
            # Prefer mev_protected > standard
            for rt in (RouteType.MEV_PROTECTED.value, RouteType.STANDARD.value):
                match = [r for r in routes if r.route_type == rt]
                if match:
                    return match[0]
        else:
            # HIGH — fastest/cheapest standard route
            standard = [r for r in routes if r.route_type == RouteType.STANDARD.value]
            if standard:
                return min(standard, key=lambda r: r.avg_latency_ms)

        return routes[0]

    def simulate(self, order: SniperOrder, token: Token) -> SimulationResult:
        """Pre-trade simulation: check all constraints before execution.

        Checks:
          1. Liquidity >= min_liquidity_usd
          2. Price impact <= max_price_impact
          3. Route available and healthy
          4. Gas estimate <= max_gas_usd
        """
        warnings: List[str] = []

        # 1. Liquidity check
        pool_liq = token.best_liquidity_usd
        if pool_liq < order.min_liquidity_usd:
            return SimulationResult(
                passed=False,
                reason=f"Insufficient liquidity: ${pool_liq:,.0f} < ${order.min_liquidity_usd:,.0f}",
            )

        # 2. Price impact
        impact = estimate_price_impact(order.size_usd, pool_liq)
        if impact > order.max_price_impact:
            return SimulationResult(
                passed=False,
                reason=f"Price impact too high: {impact:.2%} > {order.max_price_impact:.2%}",
                estimated_price_impact=impact,
            )
        if impact > order.max_price_impact * 0.7:
            warnings.append(f"Price impact {impact:.2%} approaching limit {order.max_price_impact:.2%}")

        # 3. Route selection
        route = self.select_route(order.chain, order.mev_risk_tolerance, order.size_usd)
        if route is None:
            return SimulationResult(
                passed=False,
                reason=f"No healthy route available for chain={order.chain}",
            )

        # 4. Gas estimate (simplified)
        base_gas = {"solana": 0.01, "ethereum": 5.0, "base": 0.05, "arbitrum": 0.10}.get(order.chain, 1.0)
        est_gas = base_gas * route.priority_fee_multiplier
        if est_gas > order.max_gas_usd:
            return SimulationResult(
                passed=False,
                reason=f"Estimated gas ${est_gas:.2f} > max ${order.max_gas_usd:.2f}",
                estimated_gas_usd=est_gas,
            )

        # Estimate output
        price = token.current_price_usd
        if price > 0:
            est_output = (order.size_usd / price) * (1 - impact)
        else:
            est_output = 0.0

        return SimulationResult(
            passed=True,
            estimated_price_impact=impact,
            estimated_output_tokens=est_output,
            estimated_gas_usd=est_gas,
            recommended_route=route,
            warnings=warnings,
        )

    def execute(self, order: SniperOrder, token: Token) -> SniperFill:
        """Execute a sniper order after simulation passes.

        In non-live mode, produces a simulated fill.
        In live mode, would submit via the selected route (placeholder).
        """
        # Always simulate first
        sim = self.simulate(order, token)
        if not sim.passed:
            return SniperFill(
                order_id=order.id, plan_id=order.plan_id,
                token_id=order.token_id, token_symbol=order.token_symbol,
                chain=order.chain, direction=order.direction,
                success=False, error=sim.reason,
            )

        if self._is_live:
            return self._execute_live(order, token, sim)
        return self._execute_simulated(order, token, sim)

    def _execute_simulated(
        self, order: SniperOrder, token: Token, sim: SimulationResult,
    ) -> SniperFill:
        """Produce a simulated fill for paper trading."""
        import random
        rng = random.Random()

        route = sim.recommended_route
        price = token.current_price_usd
        # Add small random slippage
        actual_slip_bps = int(sim.estimated_price_impact * 10000 * rng.uniform(0.8, 1.3))
        fill_price = price * (1 + actual_slip_bps / 10000) if order.direction == "buy" else price * (1 - actual_slip_bps / 10000)

        filled_tokens = order.size_usd / max(fill_price, 1e-12)

        # Random MEV detection (rare in sim)
        mev_detected = rng.random() < 0.05
        mev_loss = rng.uniform(0.5, 5.0) if mev_detected else 0.0

        return SniperFill(
            order_id=order.id, plan_id=order.plan_id,
            token_id=order.token_id, token_symbol=order.token_symbol,
            chain=order.chain, direction=order.direction,
            filled_size_usd=order.size_usd,
            filled_tokens=filled_tokens,
            fill_price_usd=fill_price,
            expected_price_usd=price,
            actual_slippage_bps=actual_slip_bps,
            actual_price_impact=sim.estimated_price_impact,
            gas_used_usd=sim.estimated_gas_usd * rng.uniform(0.9, 1.1),
            latency_ms=route.avg_latency_ms * rng.uniform(0.7, 1.5) if route else 500,
            route_type_used=route.route_type if route else RouteType.STANDARD.value,
            mev_detected=mev_detected,
            mev_loss_usd=mev_loss,
            tx_hash=f"sim-{_uid()}",
            success=True,
        )

    def _execute_live(
        self, order: SniperOrder, token: Token, sim: SimulationResult,
    ) -> SniperFill:
        """Placeholder for live execution — would submit real transactions."""
        # In production: use Jupiter/1inch SDK, sign via signing service, submit to RPC/relay
        return self._execute_simulated(order, token, sim)

    def check_route_health(self, chain: str) -> Dict[str, Any]:
        """Return health status of all routes for a chain."""
        routes = self.get_routes(chain)
        return {
            "chain": chain,
            "routes": [
                {
                    "dex_router": r.dex_router,
                    "route_type": r.route_type,
                    "mev_relay": r.mev_relay,
                    "is_healthy": r.is_healthy,
                    "avg_latency_ms": r.avg_latency_ms,
                    "failure_rate": r.failure_rate,
                }
                for r in routes
            ],
            "has_mev_protection": any(
                r.route_type in (RouteType.MEV_PROTECTED.value, RouteType.PRIVATE_TX.value)
                for r in routes
            ),
            "healthy_count": sum(1 for r in routes if r.is_healthy),
            "total_count": len(routes),
        }


# ── Singleton ─────────────────────────────────────────────────────────

_sniper: Optional[SniperExecutor] = None


def get_sniper_executor() -> SniperExecutor:
    global _sniper
    if _sniper is None:
        _sniper = SniperExecutor()
    return _sniper
