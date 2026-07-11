"""
Edge Computer Abstraction for UnifiedEdgeComputer.

Provides a clean interface for edge computation that can be backed by:
- UnifiedEdgeBackend (full RTI-based edge computation)
- LegacyEdgeBackend (spread-based heuristics)

This allows the rest of the stack to be backend-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class EdgeComputationResult:
    """Result of edge computation."""
    edge_pct: float  # Edge as percentage (0-1)
    confidence: float  # Confidence score (0-1)
    side: str  # "yes" or "no"
    price_cents: int  # Contract price in cents
    implied_prob: float  # Market-implied probability
    model_prob: float  # Model probability
    favored_side: str  # Which side is favored
    metadata: Dict  # Additional metadata for logging


class EdgeComputer:
    """Abstract edge computer for unified edge computation."""

    async def compute(
        self,
        asset: str,
        market_id: str,
        state: Optional[object],
        spot_price: Optional[float],
        minutes_to_expiry: Optional[float],
        config: object,
    ) -> Optional[EdgeComputationResult]:
        """Compute edge for a market.

        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            market_id: Kalshi market ID
            state: Market state (orderbook, spread, etc.)
            spot_price: Spot price in USD
            minutes_to_expiry: Time to expiry in minutes
            config: Agent configuration

        Returns:
            EdgeComputationResult or None if edge check fails
        """
        raise NotImplementedError


class LegacyEdgeBackend(EdgeComputer):
    """Legacy spread-based edge computation backend.

    Uses simple spread heuristics and effective edge thresholds.
    This is the original edge computation method before unified edge.
    """

    async def compute(
        self,
        asset: str,
        market_id: str,
        state: Optional[object],
        spot_price: Optional[float],
        minutes_to_expiry: Optional[float],
        config: object,
    ) -> Optional[EdgeComputationResult]:
        """Compute edge using legacy spread-based heuristics."""
        try:
            from merid.risk.helpers import get_effective_edge_threshold

            # Create a simple profile config object with min_edge_pct
            class _ProfileConfig:
                min_edge_pct = 0.01  # 1% base edge (reduced for calibration)

            profile_config = _ProfileConfig()

            # Use existing spread-based edge computation
            spread_edge = get_effective_edge_threshold(state, profile_config)
            if state and hasattr(state, "spread_cents") and state.spread_cents:
                spread_pct = state.spread_cents / 100.0
                logger.debug(
                    "[LEGACY-EDGE] %s dynamic edge: spread=%d cents (%.2f%%), edge=%.2f%%",
                    config.name if hasattr(config, "name") else "unknown",
                    state.spread_cents,
                    spread_pct,
                    spread_edge,
                )

            edge_pct = spread_edge
            confidence = 0.70  # 70% confidence (above 60% threshold)

            # Spread guard check
            spread_cents = int(state.spread_cents) if state and hasattr(state, "spread_cents") else 0

            # Simple spread guard (max 75 cents spread)
            max_spread_cents = 75  # 2026-07-11: Canonical spread filter (75c) - aligned with historical requirement
            if spread_cents > max_spread_cents:
                logger.info(
                    "[LEGACY-EDGE] %s asset=%s ticker=%s spread=%d cents > %d cents - blocking entry",
                    config.name if hasattr(config, "name") else "unknown",
                    asset,
                    market_id,
                    spread_cents,
                    max_spread_cents,
                )
                return None

            # Determine price_cents from market state
            if state and hasattr(state, "mid_cents") and state.mid_cents:
                price_cents = state.mid_cents
            elif hasattr(state, "best_bid_cents") and hasattr(state, "best_ask_cents"):
                best_bid = getattr(state, "best_bid_cents", 0)
                best_ask = getattr(state, "best_ask_cents", 0)
                if best_bid > 0 and best_ask > 0:
                    price_cents = (best_bid + best_ask) // 2
                else:
                    price_cents = 25  # 2026-07-09: Fixed to 25c (midpoint of 10-50c sweet spot)
            else:
                price_cents = 25  # 2026-07-09: Fixed to 25c (midpoint of 10-50c sweet spot)

            # CRITICAL: Check minimum contract price floor (blocks deep OTM longshots)
            # This guardrail prevents trading ultra-low priced contracts that are statistically losing
            min_price_cents = 20  # Default fallback (20 cents / $0.20)
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile
                profile_adapter = get_active_profile()
                if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_min_contract_price_cents'):
                    min_price_cents = profile_adapter.profile.guardrails_min_contract_price_cents
            except Exception as e:
                logger.debug("[LEGACY-EDGE] Failed to load min_contract_price_cents from profile: %s, using default 20c", e)

            if price_cents < min_price_cents:
                logger.info(
                    "[LEGACY-EDGE] %s asset=%s ticker=%s price=%d cents < %d cents threshold (deep OTM longshot rejected)",
                    config.name if hasattr(config, "name") else "unknown",
                    asset,
                    market_id,
                    price_cents,
                    min_price_cents,
                )
                return None

            # Compute dual-sided edge to determine best side
            implied_prob = price_cents / 100.0
            implied_prob_no = 1.0 - implied_prob

            # Model can favor either side - edge_pct is magnitude of mispricing
            model_prob_yes = implied_prob + edge_pct
            model_prob_no = implied_prob_no + edge_pct

            # Calculate raw edges for both sides
            edge_yes = abs(model_prob_yes - implied_prob)
            edge_no = abs(model_prob_no - implied_prob_no)

            # Select best side with deterministic tie-breaking
            edge_diff = edge_yes - edge_no
            if abs(edge_diff) < 1e-6:  # Edges are effectively equal
                # Tie-break by depth
                depth_yes = getattr(state, "min_depth_yes", 0) if state else 0
                depth_no = getattr(state, "min_depth_no", 0) if state else 0
                if depth_yes >= depth_no:
                    side = "yes"
                    best_edge = edge_yes
                    model_prob = model_prob_yes
                    favored_side = "yes"
                else:
                    side = "no"
                    best_edge = edge_no
                    model_prob = model_prob_no
                    favored_side = "no"
                    price_cents = 100 - price_cents
                    implied_prob = price_cents / 100.0
            elif edge_yes > edge_no:
                side = "yes"
                best_edge = edge_yes
                model_prob = model_prob_yes
                favored_side = "yes"
            else:
                side = "no"
                best_edge = edge_no
                model_prob = model_prob_no
                favored_side = "no"
                price_cents = 100 - price_cents
                implied_prob = price_cents / 100.0

            logger.info(
                "[LEGACY-EDGE] %s asset=%s ticker=%s implied_yes=%.3f implied_no=%.3f edge_yes=%.3f edge_no=%.3f chosen_side=%s best_edge=%.3f",
                config.name if hasattr(config, "name") else "unknown",
                asset,
                market_id,
                implied_prob,
                implied_prob_no,
                edge_yes,
                edge_no,
                side,
                best_edge,
            )

            return EdgeComputationResult(
                edge_pct=best_edge,
                confidence=confidence,
                side=side,
                price_cents=price_cents,
                implied_prob=implied_prob,
                model_prob=model_prob,
                favored_side=favored_side,
                metadata={
                    "backend": "legacy",
                    "spread_cents": spread_cents,
                    "edge_pct": edge_pct,
                },
            )

        except Exception as e:
            logger.error("[LEGACY-EDGE] Failed to compute edge: %s", e, exc_info=True)
            return None


class UnifiedEdgeBackend(EdgeComputer):
    """Unified edge computation backend using RTI spot reference.

    Uses UnifiedEdgeComputer with spot reference, orderbook, fees, and calibration.
    This is the new RTI-based edge computation method.
    """

    def __init__(self, calibration: Optional[object] = None):
        from merid.prediction.unified_edge import UnifiedEdgeComputer

        self._computer = UnifiedEdgeComputer(calibration=calibration)

    async def compute(
        self,
        asset: str,
        market_id: str,
        state: Optional[object],
        spot_price: Optional[float],
        minutes_to_expiry: Optional[float],
        config: object,
    ) -> Optional[EdgeComputationResult]:
        """Compute edge using unified edge computer."""
        logger.info(
            "[UNIFIED-EDGE-CALL] asset=%s ticker=%s spot_price=%s minutes_to_expiry=%s",
            asset, market_id, spot_price, minutes_to_expiry
        )
        
        try:
            from merid.prediction.unified_edge import SpotReference, OrderBookSnapshot, ContractState
            from datetime import datetime, timezone

            # Early exit if spot price is None or invalid
            if spot_price is None or spot_price <= 0:
                logger.warning(
                    "[UNIFIED-EDGE-EXIT] asset=%s ticker=%s reason=invalid_spot_price spot_price=%s",
                    asset, market_id, spot_price
                )
                return None

            # Build spot reference (should be provided by caller via SpotProvider)
            # For now, use the spot_price parameter
            spot_ref = SpotReference(
                asset=asset,
                price_usd=spot_price or 0,
                timestamp=datetime.now(timezone.utc),
                source="unified_spot",
                is_rti_proxy=False,
            )

            # Build order book snapshot
            orderbook = None
            if state:
                best_bid = getattr(state, "best_bid_cents", 0)
                best_ask = getattr(state, "best_ask_cents", 0)
                best_bid_size = getattr(state, "top_of_book_size", 0)
                best_ask_size = getattr(state, "top_of_book_size", 0)
                spread_cents = getattr(state, "spread_cents", 0)

                if best_bid > 0 and best_ask > 0:
                    orderbook = OrderBookSnapshot(
                        best_bid=best_bid,
                        best_ask=best_ask,
                        best_bid_size=best_bid_size,
                        best_ask_size=best_ask_size,
                        spread_cents=spread_cents,
                        timestamp=datetime.now(timezone.utc),
                    )

            # Build contract state
            # CRITICAL: Use window_strike_price from market state for 15m markets
            # This is the dual-source captured strike (Kalshi's floor_strike at window start)
            if state and hasattr(state, 'window_strike_price'):
                window_strike = getattr(state, 'window_strike_price', None)
                if window_strike is not None and window_strike > 0:
                    strike_price = window_strike
                    logger.debug(
                        "[EDGE-COMPUTER] asset=%s ticker=%s using window_strike_price=%.2f (dual-source capture)",
                        asset, market_id, strike_price
                    )
                else:
                    strike_price = spot_price if spot_price else 0
            else:
                strike_price = spot_price if spot_price else 0
            
            mid_price_cents = getattr(state, "mid_cents", 50) if state else 50

            contract_state = ContractState(
                market_id=market_id,
                asset=asset,
                side="yes",  # Will be determined by edge computation
                strike_price=strike_price,
                mid_price_cents=mid_price_cents,
                time_to_expiry_seconds=(minutes_to_expiry or 0) * 60,
                orderbook=orderbook,
            )

            # Compute edge using unified edge computer
            edge_result = self._computer.compute_edge(
                contract_state=contract_state,
                spot_ref=spot_ref,
                calibration=None,  # Use default calibration
            )

            # Check edge
            edge_check = self._computer.check_edge(
                edge_result=edge_result,
                min_edge_cents=1,  # 1 cent minimum
                max_spread_pct=0.60,  # 60% max spread
            )

            if not edge_check.passes:
                logger.warning(
                    "[UNIFIED-EDGE-EXIT] asset=%s ticker=%s reason=edge_check_failed edge_check=%s",
                    asset,
                    market_id,
                    edge_check.reason,
                )
                return None

            # Determine side from edge result
            # Unified edge computes edge for a specific side
            side = contract_state.side
            favored_side = side

            return EdgeComputationResult(
                edge_pct=edge_result.edge,
                confidence=edge_result.confidence,
                side=side,
                price_cents=mid_price_cents,
                implied_prob=edge_result.market_implied_prob,
                model_prob=edge_result.model_win_prob,
                favored_side=favored_side,
                metadata={
                    "backend": "unified",
                    "edge_risk_adjusted": edge_result.edge_risk_adjusted,
                    "edge_slippage_adjusted": edge_result.edge_slippage_adjusted,
                    "edge_fee_adjusted": edge_result.edge_fee_adjusted,
                    "raw_edge_cents": edge_result.raw_edge_cents,
                    "spread_cost_cents": edge_result.spread_cost_cents,
                    "fee_cost_cents": edge_result.fee_cost_cents,
                    "net_edge_cents": edge_result.net_edge_cents,
                },
            )

        except Exception as e:
            logger.error("[UNIFIED-EDGE] Failed to compute edge: %s", e, exc_info=True)
            return None


def get_edge_computer(backend_type: str = "legacy", calibration: Optional[object] = None) -> EdgeComputer:
    """Factory function to get edge computer instance.

    Args:
        backend_type: "legacy" (spread-based) or "unified" (RTI-based)
        calibration: Calibration data for unified edge

    Returns:
        EdgeComputer instance
    """
    if backend_type == "legacy":
        return LegacyEdgeBackend()
    elif backend_type == "unified":
        return UnifiedEdgeBackend(calibration=calibration)
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")
