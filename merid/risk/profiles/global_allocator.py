"""
Global Allocator for Multi-Asset Position Sizing

Replaces per-asset caps with a top-N edge knapsack allocator under venue cap.

Core idea:
- Collect all candidates from all agents in a cycle
- Sort by edge (descending)
- Greedy fill under venue cap ($1.00)
- Only submit orders that fit under the cap

This ensures:
- Best edges get prioritized
- Total exposure ≤ venue cap (shared $1 pool across all assets)
- No artificial per-asset limits
- Concentration on highest expected returns
- 1 contract per asset per window
- Entry prices must fall within [min_price_cents, max_price_cents] (default 10-75c)
- Confidence ≥ 50% (matches agent grid: 0.5 + edge/100), edge ≥ 2.5% (industry standard)
"""

import time
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple

from dataclasses import dataclass, field
from utils.logger import get_logger
from merid.risk.global_slot_allocator import MAX_CONTRACTS_PER_ORDER

logger = get_logger("merid.risk.profiles.global_allocator")


def _to_edge_fraction(edge: float) -> float:
    """Normalize an edge value to a fraction (0.025 = 2.5%).

    The codebase passes edge as either percentage points (e.g. 5.0) or as a
    fraction (e.g. 0.05).  Values whose absolute magnitude is >= 1.0 are
    treated as percentage points and divided by 100; all other values are
    kept as fractions.  This is a defensive bridge while the stack converges
    on a single edge convention.
    """
    if edge is None:
        return 0.0
    return edge / 100.0 if abs(edge) >= 1.0 else edge


def _to_edge_percent(edge: float) -> float:
    """Inverse of _to_edge_fraction: return a value formatted in percent."""
    if edge is None:
        return 0.0
    return edge if abs(edge) >= 1.0 else edge * 100.0


@dataclass
class OrderCandidate:
    """Represents a potential order from an agent."""
    asset: str
    ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    price_cents: int
    count: int
    edge_pct: float
    confidence: float
    model_prob: float
    agent_name: str
    candidate_id: str = ""

    @property
    def notional_usd(self) -> float:
        """Calculate order notional in USD."""
        return (self.price_cents * self.count) / 100.0

    @property
    def edge_score(self) -> float:
        """
        Composite edge score for ranking.
        Combines edge_pct and confidence.
        """
        return _to_edge_fraction(self.edge_pct) * self.confidence


@dataclass
class CanonicalLivePosition:
    """Exchange-confirmed live exposure for a single market/ticker.

    This is the authoritative input for allocation decisions.  It carries the
    asset, full market ticker, side, size, average entry price, and whether the
    position is confirmed by the exchange or by an outstanding (non-terminal)
    open order.  The GlobalAllocator uses only positions whose ticker matches the
    candidate's ticker, preventing stale asset-level positions from blocking new
    entries in a different window.
    """
    asset: str
    ticker: str
    side: str  # "yes" or "no"
    contracts: int
    avg_price_cents: int
    notional_usd: float
    exchange_confirmed_open: bool = True
    pending_order_open: bool = False

    @property
    def is_open(self) -> bool:
        """An exposure is live if it is either filled on exchange or resting on the book."""
        return self.exchange_confirmed_open or self.pending_order_open


@dataclass
class AllocationDecision:
    """Structured allocation outcome for a single candidate.

    Replaces the opaque `allocator_loss` label with explicit constraint reasons
    and lifecycle accounting fields.  A decision is recorded for every input
    candidate; rejected candidates carry a concrete terminal reason and the
    stage where they were eliminated.  Selected candidates have no terminal
    reason and their approved_quantity_fp is set.
    """

    cycle_id: Any = None
    candidate_id: str = ""
    asset: str = ""
    ticker: str = ""
    selected: bool = False
    constraint_reasons: List[str] = field(default_factory=list)
    terminal_reason: Optional[str] = None
    rejection_stage: Optional[str] = None
    requested_quantity_fp: float = 0.0
    approved_quantity_fp: float = 0.0
    expected_value_cents: Optional[float] = None
    stage_results: Dict[str, str] = field(default_factory=dict)


# Allocation evaluation stages, in the order they are applied.
_ALLOCATION_STAGES = (
    "EDGE",
    "CONFIDENCE",
    "PRICE",
    "COUNT",
    "EXISTING_POSITION",
    "PENDING_ORDER",
    "POSITION_CAP",
    "ASSET_CAP",
    "BUDGET",
    "KNAPSACK",
)

# Concrete terminal reason codes used in AllocationDecision.constraint_reasons.
REASON_EXPECTED_VALUE_BELOW_MINIMUM = "EXPECTED_VALUE_BELOW_MINIMUM"
REASON_CONFIDENCE_BELOW_MINIMUM = "CONFIDENCE_BELOW_MINIMUM"
REASON_PRICE_OUT_OF_RANGE = "PRICE_OUT_OF_RANGE"
REASON_DUPLICATE_EXPOSURE = "DUPLICATE_EXPOSURE"
REASON_EXISTING_POSITION = "EXISTING_POSITION"
REASON_PENDING_ORDER = "PENDING_ORDER"
REASON_POSITION_CAP = "POSITION_CAP"
REASON_ASSET_CAP = "ASSET_CAP"
REASON_BUDGET_LIMIT = "BUDGET_LIMIT"
REASON_MIN_NOTIONAL = "MIN_NOTIONAL"
REASON_QUANTITY_ROUNDED_TO_ZERO = "QUANTITY_ROUNDED_TO_ZERO"
REASON_KNAPSACK_CAP = "KNAPSACK_CAP"

# Generic terminal reason for candidates that survive all pre-knapsack stages
# and are then eliminated by the knapsack/budget/asset-cap phase.
_ALLOCATION_TERMINAL = "ALLOCATOR_REJECTED"


def _mark_terminal(decision: AllocationDecision, stage: str, reason: str) -> None:
    """Record a terminal rejection without overwriting an earlier one.

    Pre-knapsack failures keep their concrete reason as the terminal reason.
    Knapsack- and cap-phase failures use the generic ``_ALLOCATION_TERMINAL``
    label while the concrete reason is preserved in ``constraint_reasons``.
    """
    if decision.terminal_reason is not None:
        return
    if stage in ("ASSET_CAP", "BUDGET", "KNAPSACK"):
        decision.terminal_reason = _ALLOCATION_TERMINAL
    else:
        decision.terminal_reason = reason
    decision.rejection_stage = stage
    decision.constraint_reasons.append(reason)


class GlobalAllocator:
    """
    Global allocator for multi-asset position sizing.
    
    Implements top-N edge knapsack under venue cap with shared $1 pool.
    
    CRITICAL RULES:
    - $1 total exposure cap across ALL assets (shared pool, not per-asset)
    - Up to 2 contracts per asset per window (capped by $1 exposure)
    - Entry price must fall within [min_price_cents, max_price_cents] (default 10-75c)
    - Confidence must be ≥ 50% (matches signal generation range: 0.5 + edge)
    - Edge must be ≥ 2.5% (matches profile edge_bands - industry standard)
    - Assets compete for capital (no per-asset budgets)
    """
    
    def __init__(
        self,
        venue_cap_usd: float = 1.00,
        min_edge_pct: float = 0.025,  # 2026-07-14: Changed to 2.5% to match profile edge_bands (industry standard)
                                      # 2026-07-25: CRITICAL - This is stored as FRACTION (0.025 = 2.5%), not percentage
                                      # Display multiplies by 100 for logging, but internal comparison uses fraction
        min_confidence: float = 0.50,  # 2026-07-28: CRITICAL FIX - Lowered from 0.65 to 0.50 to match signal generation range
                                      # Signal generation produces confidence = 0.5 + edge (edge is 0.02-0.08), resulting in 52-58%
        min_price_cents: int = 10,  # CRITICAL 2026-08-14: Restore 10c hard floor (was 1c)
        max_price_cents: int = 75,  # CRITICAL 2026-08-14: Restore 75c hard cap (was 99c)
        max_single_asset_fraction: float = 1.00,  # Max 100% of cap per asset (allows single order to use full venue cap)
        enable_correlation_control: bool = False,
        # 2026-07-14: Per-asset edge thresholds aligned with profile edge_bands (2.5% unified - industry standard)
        # 2026-07-25: CRITICAL - These are stored as FRACTIONS (0.025 = 2.5%), not percentages
        # This ensures global allocator doesn't filter candidates that pass validate_edge()
        per_asset_min_edge_pct: dict = None,
    ):
        self.venue_cap_usd = venue_cap_usd
        self.min_edge_pct = min_edge_pct  # Stored as fraction (0.025 = 2.5%)
        self.min_confidence = min_confidence
        self.min_price_cents = min_price_cents
        self.max_price_cents = max_price_cents
        self.max_single_asset_fraction = max_single_asset_fraction
        self.enable_correlation_control = enable_correlation_control
        
        # Per-asset edge thresholds (aligned with profile edge_bands - single source of truth)
        # CRITICAL FIX 2026-07-14: Updated to use unified 2.5% threshold from profile edge_bands
        # CRITICAL FIX 2026-07-25: All thresholds stored as FRACTIONS (0.025 = 2.5%), not percentages
        # Industry standard for Kalshi: 3% raw edge minimum (Market Math, Beatpoly)
        # Kalshi 7% winner fee turns <2% edge into breakeven/negative EV
        # Edge threshold hierarchy (from profile YAML):
        # 1. edge_bands.*.min_edge_pct - PRIMARY: Used for trade execution (2.5% minimum)
        # 2. Per-asset min_edge_early/mid/late/terminal - IGNORED: Legacy fields, not used
        if per_asset_min_edge_pct is None:
            self.per_asset_min_edge_pct = {
                "BTC": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
                "ETH": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
                "SOL": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
                "XRP": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
                "DOGE": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
            }
        else:
            self.per_asset_min_edge_pct = per_asset_min_edge_pct
        
        # 2026-07-13: Add per-asset position and pending order tracking
        # This prevents multiple contracts per asset (the core issue)
        self._asset_positions: Dict[str, float] = {}  # asset -> current notional
        self._pending_orders: Dict[str, str] = {}  # asset -> order_id (pending submission)
        self._pending_order_timestamps: Dict[str, float] = {}  # asset -> submission timestamp
        self._pending_order_timeout = 30.0  # 30 seconds timeout for pending orders

        # CRITICAL FIX (2026-08-23): Record per-candidate allocation decisions keyed by
        # cycle_id so stale results from previous ticks are never returned.
        self._allocation_decisions: Dict[Any, List[AllocationDecision]] = defaultdict(list)
        
        logger.info(
            "[GLOBAL-ALLOCATOR] Initialized: venue_cap=$%.2f, min_edge=%.3f%% (fraction=%.3f), min_conf=%.0f%%, price_range=[%dc-%dc], max_single=%.1f%%",
            venue_cap_usd, min_edge_pct * 100, min_edge_pct, min_confidence * 100, min_price_cents, max_price_cents, max_single_asset_fraction * 100
        )
        logger.info(
            "[GLOBAL-ALLOCATOR] Per-asset edge thresholds: %s",
            ", ".join(f"{k}={v}%" for k, v in self.per_asset_min_edge_pct.items())
        )

    def _has_live_exposure_for_ticker(
        self,
        candidate: OrderCandidate,
        canonical_live_positions: List[CanonicalLivePosition]
    ) -> bool:
        """Return True if an exchange-confirmed or pending live exposure exists for this exact ticker."""
        return any(
            p.asset == candidate.asset
            and p.ticker == candidate.ticker
            and p.is_open
            for p in canonical_live_positions
        )

    def _current_notional_for_ticker(
        self,
        candidate: OrderCandidate,
        canonical_live_positions: List[CanonicalLivePosition]
    ) -> float:
        """Return the total live notional for this exact candidate ticker."""
        return sum(
            p.notional_usd
            for p in canonical_live_positions
            if p.asset == candidate.asset
            and p.ticker == candidate.ticker
            and p.is_open
        )

    def _has_pending_order_for_ticker(
        self,
        candidate: OrderCandidate
    ) -> bool:
        """Check the order gate for an active pending/resting order on this exact ticker."""
        if candidate.asset not in self._pending_orders:
            return False

        order_id = self._pending_orders[candidate.asset]

        # First, treat any in-memory pending record that is not stale as active.
        # This prevents the same asset from being double-entered while an order is
        # in flight, even if the gate lookup is momentarily unavailable.
        timestamp = self._pending_order_timestamps.get(candidate.asset, 0.0)
        if time.time() - timestamp <= self._pending_order_timeout:
            # Still within the pending timeout window; block the candidate.
            # Cross-validate with the gate in the background to clean terminal states.
            try:
                from merid.event_venues.kalshi.order_gate import get_pre_trade_gate
                order_gate = get_pre_trade_gate()
                if order_gate:
                    order_record = order_gate.lookup(order_id)
                    if order_record and order_record.status in ("filled", "canceled", "rejected", "expired"):
                        # Stale/terminal pending order; clean it up and allow.
                        logger.warning(
                            "[GLOBAL-ALLOCATOR] Clearing terminal pending order %s for %s (status=%s)",
                            order_id, candidate.asset, order_record.status
                        )
                        del self._pending_orders[candidate.asset]
                        del self._pending_order_timestamps[candidate.asset]
                        return False
            except Exception as e:
                logger.warning(
                    "[GLOBAL-ALLOCATOR] Failed to cross-validate pending order %s for %s: %s",
                    order_id, candidate.asset, e
                )
            return True

        # Stale pending order; clear and allow.
        logger.warning(
            "[GLOBAL-ALLOCATOR] Clearing stale pending order %s for %s (>%.0fs old)",
            order_id, candidate.asset, self._pending_order_timeout
        )
        del self._pending_orders[candidate.asset]
        del self._pending_order_timestamps[candidate.asset]
        return False

    def allocate(
        self,
        candidates: List[OrderCandidate],
        current_positions: Optional[Dict[str, float]] = None,
        canonical_live_positions: Optional[List[CanonicalLivePosition]] = None,
        cycle_id: Any = None,
    ) -> List[OrderCandidate]:
        """
        Allocate orders based on edge ranking under venue cap with shared $1 pool.

        CRITICAL: This implements the shared $1 pool model where assets compete for capital.
        No per-asset budgets - total exposure across all assets must be <= $1.00.

        One ``AllocationDecision`` is produced for every input candidate and keyed by
        ``cycle_id``.  Each candidate is evaluated through the fixed stage pipeline;
        the first failing stage records a concrete terminal reason.  Candidates that
        survive all pre-knapsack stages are then passed to the optimal-knapsack stage.

        Args:
            candidates: List of all potential orders from agents
            current_positions: Current position notional per asset (optional, legacy).
                Prefer ``canonical_live_positions`` for authoritative per-ticker exposure.
            canonical_live_positions: Exchange-confirmed live positions keyed by market
                ticker.  When provided, this is used in place of ``current_positions``
                to avoid stale asset-level exposure blocking a different window.
            cycle_id: Optional cycle/tick identifier.  When supplied, previous decisions
                for this cycle are cleared at the start of the call.

        Returns:
            List of chosen orders that fit under venue cap
        """
        # Clear any previous decisions for this cycle so telemetry never reads stale data.
        if cycle_id is not None:
            self._allocation_decisions[cycle_id] = []
        decisions = self._allocation_decisions.get(cycle_id, [])

        if not candidates:
            logger.info("[GLOBAL-ALLOCATOR] No candidates to allocate")
            return []

        current_positions = current_positions or {}
        canonical_live_positions = canonical_live_positions or []

        use_canonical = bool(canonical_live_positions)

        # CRITICAL FIX: Sync internal _asset_positions with authoritative current_positions
        # This ensures lifecycle callbacks don't drift from actual position cache state
        self._asset_positions = current_positions.copy()

        if use_canonical:
            # Overwrite with notional from authoritative canonical live positions (per ticker)
            self._asset_positions = {}
            for p in canonical_live_positions:
                if p.is_open:
                    self._asset_positions[p.asset] = self._asset_positions.get(p.asset, 0.0) + p.notional_usd

        # CRITICAL FIX (2026-07-31): Clear pending orders for assets that already have positions
        # This handles the case where fills occurred but global_allocator wasn't notified
        # (e.g., before the fills_ledger fix was applied)
        for asset in list(self._pending_orders.keys()):
            if asset in current_positions and current_positions[asset] > 0:
                logger.warning(
                    "[GLOBAL-ALLOCATOR] Clearing stale pending order for %s: position exists ($%.2f)",
                    asset, current_positions[asset]
                )
                del self._pending_orders[asset]
                del self._pending_order_timestamps[asset]

        # Build one AllocationDecision per candidate and keep (candidate, decision) pairs
        # for the staged evaluation pipeline.  All decisions are stored by cycle_id.
        working: List[Tuple[OrderCandidate, AllocationDecision]] = []
        for c in candidates:
            d = AllocationDecision(
                cycle_id=cycle_id,
                candidate_id=c.candidate_id or f"oc-{id(c)}",
                asset=c.asset,
                ticker=c.ticker,
                selected=False,
                requested_quantity_fp=float(c.count),
                approved_quantity_fp=0.0,
            )
            decisions.append(d)
            working.append((c, d))

        # STAGE: EDGE
        edge_passed: List[Tuple[OrderCandidate, AllocationDecision]] = []
        for c, d in working:
            asset_min_edge = self.per_asset_min_edge_pct.get(c.asset, self.min_edge_pct)
            candidate_edge_frac = _to_edge_fraction(c.edge_pct)
            asset_min_edge_frac = _to_edge_fraction(asset_min_edge)
            if candidate_edge_frac >= asset_min_edge_frac:
                d.stage_results["EDGE"] = "PASS"
                edge_passed.append((c, d))
            else:
                d.stage_results["EDGE"] = "FAIL"
                _mark_terminal(d, "EDGE", REASON_EXPECTED_VALUE_BELOW_MINIMUM)
                logger.info(
                    "[GLOBAL-ALLOCATOR] SKIP %s: edge=%.3f%% < per_asset_min_edge=%.3f%%",
                    c.asset, _to_edge_percent(c.edge_pct), _to_edge_percent(asset_min_edge)
                )

        # STAGE: CONFIDENCE
        conf_passed: List[Tuple[OrderCandidate, AllocationDecision]] = []
        for c, d in edge_passed:
            if c.confidence >= self.min_confidence:
                d.stage_results["CONFIDENCE"] = "PASS"
                conf_passed.append((c, d))
            else:
                d.stage_results["CONFIDENCE"] = "FAIL"
                _mark_terminal(d, "CONFIDENCE", REASON_CONFIDENCE_BELOW_MINIMUM)
                logger.info(
                    "[GLOBAL-ALLOCATOR] SKIP %s: confidence=%.2f%% < min=%.2f%%",
                    c.asset, c.confidence * 100, self.min_confidence * 100
                )

        # STAGE: PRICE
        price_passed: List[Tuple[OrderCandidate, AllocationDecision]] = []
        for c, d in conf_passed:
            if self.min_price_cents <= c.price_cents <= self.max_price_cents:
                d.stage_results["PRICE"] = "PASS"
                price_passed.append((c, d))
            else:
                d.stage_results["PRICE"] = "FAIL"
                _mark_terminal(d, "PRICE", REASON_PRICE_OUT_OF_RANGE)
                logger.info(
                    "[GLOBAL-ALLOCATOR] SKIP %s: price=%dc outside range [%dc-%dc]",
                    c.asset, c.price_cents, self.min_price_cents, self.max_price_cents
                )

        # STAGE: COUNT
        count_passed: List[Tuple[OrderCandidate, AllocationDecision]] = []
        for c, d in price_passed:
            if c.count <= 0:
                d.stage_results["COUNT"] = "FAIL"
                _mark_terminal(d, "COUNT", REASON_QUANTITY_ROUNDED_TO_ZERO)
                logger.warning(
                    "[GLOBAL-ALLOCATOR] SKIP %s: count=%d invalid / rounded to zero",
                    c.asset, c.count
                )
            elif c.count > MAX_CONTRACTS_PER_ORDER:
                d.stage_results["COUNT"] = "FAIL"
                _mark_terminal(d, "COUNT", REASON_POSITION_CAP)
                logger.warning(
                    "[GLOBAL-ALLOCATOR] SKIP %s: count=%d exceeds max contracts per order=%d",
                    c.asset, c.count, MAX_CONTRACTS_PER_ORDER
                )
            else:
                d.stage_results["COUNT"] = "PASS"
                count_passed.append((c, d))

        # STAGE: EXISTING_POSITION
        existing_passed: List[Tuple[OrderCandidate, AllocationDecision]] = []
        for c, d in count_passed:
            # CRITICAL FIX (2026-08-01): Check for phantom positions in position cache
            # Phantom positions have contracts > 0 but invalid avg_price_cents (None or 0)
            # This can happen when fills ledger shows net_contracts=0 but cache shows contracts > 0
            try:
                from merid.event_venues.kalshi.position_cache import get_position_cache
                cache = get_position_cache()
                phantom_deleted = False
                for market_id, position in list(cache._positions.items()):
                    if (position.contracts > 0 and
                        (position.avg_price_cents is None or position.avg_price_cents == 0) and
                        c.asset in market_id.upper()):
                        if cache.force_delete_phantom_position(market_id):
                            phantom_deleted = True
                            logger.info(
                                "[GLOBAL-ALLOCATOR] Cleaned up phantom position for %s: market=%s contracts=%d avg_price=%s",
                                c.asset, market_id, position.contracts, position.avg_price_cents
                            )
                if phantom_deleted:
                    logger.info(
                        "[GLOBAL-ALLOCATOR] Phantom position cleanup completed for %s",
                        c.asset
                    )
            except Exception as cleanup_err:
                logger.warning(
                    "[GLOBAL-ALLOCATOR] Failed to clean up phantom positions for %s: %s",
                    c.asset, cleanup_err
                )

            if use_canonical:
                if self._has_live_exposure_for_ticker(c, canonical_live_positions):
                    current_notional = self._current_notional_for_ticker(c, canonical_live_positions)
                    d.stage_results["EXISTING_POSITION"] = "FAIL"
                    _mark_terminal(d, "EXISTING_POSITION", REASON_EXISTING_POSITION)
                    logger.info(
                        "[GLOBAL-ALLOCATOR] SKIP %s: exchange-confirmed exposure on same ticker %s ($%.2f)",
                        c.asset, c.ticker, current_notional
                    )
                    continue
            else:
                asset_exposure = current_positions.get(c.asset, 0.0)
                if asset_exposure is None:
                    logger.warning(
                        "[GLOBAL-ALLOCATOR] SKIP %s: asset has corrupted position data (exposure=None), treating as no position",
                        c.asset
                    )
                    d.stage_results["EXISTING_POSITION"] = "PASS"
                    existing_passed.append((c, d))
                    continue

                if c.asset in current_positions and current_positions[c.asset] > 0:
                    d.stage_results["EXISTING_POSITION"] = "FAIL"
                    _mark_terminal(d, "EXISTING_POSITION", REASON_EXISTING_POSITION)
                    logger.info(
                        "[GLOBAL-ALLOCATOR] SKIP %s: asset has existing position ($%.2f)",
                        c.asset, current_positions[c.asset]
                    )
                    continue

            d.stage_results["EXISTING_POSITION"] = "PASS"
            existing_passed.append((c, d))

        # STAGE: PENDING_ORDER
        pending_passed: List[Tuple[OrderCandidate, AllocationDecision]] = []
        for c, d in existing_passed:
            # Check for an active pending/resting order on this exact ticker.
            # CRITICAL FIX (2026-08-12): Use ticker-level match so a pending order for a
            # stale or unrelated window does not block the current candidate.
            if self._has_pending_order_for_ticker(c):
                d.stage_results["PENDING_ORDER"] = "FAIL"
                _mark_terminal(d, "PENDING_ORDER", REASON_PENDING_ORDER)
                logger.info(
                    "[GLOBAL-ALLOCATOR] SKIP %s: active pending/resting order for ticker %s",
                    c.asset, c.ticker
                )
                continue

            d.stage_results["PENDING_ORDER"] = "PASS"
            pending_passed.append((c, d))

        # STAGE: POSITION_CAP
        # Only one candidate per asset is eligible for the knapsack.  Duplicates are not
        # an error; the first candidate in pipeline order keeps the slot.
        position_cap_passed: List[Tuple[OrderCandidate, AllocationDecision]] = []
        asset_seen: set = set()
        for c, d in pending_passed:
            if c.asset in asset_seen:
                d.stage_results["POSITION_CAP"] = "FAIL"
                _mark_terminal(d, "POSITION_CAP", REASON_DUPLICATE_EXPOSURE)
                logger.info(
                    "[GLOBAL-ALLOCATOR] SKIP %s: duplicate candidate for asset %s",
                    c.asset, c.asset
                )
                continue
            asset_seen.add(c.asset)
            d.stage_results["POSITION_CAP"] = "PASS"
            position_cap_passed.append((c, d))

        # STAGES: ASSET_CAP, BUDGET, KNAPSACK
        unique_candidates = [c for c, d in position_cap_passed]
        unique_decisions = {c.candidate_id or f"oc-{id(c)}": d for c, d in position_cap_passed}

        if not unique_candidates:
            logger.info("[GLOBAL-ALLOCATOR] No candidates passed all filters (edge, confidence, price, position)")
            return []

        # Optimal knapsack under $1 cap, preserving original candidate ordering.
        from itertools import combinations

        n = len(unique_candidates)
        best_combination: List[OrderCandidate] = []
        best_total_edge = 0.0
        best_total_notional = float('inf')

        for r in range(1, n + 1):
            for combo in combinations(unique_candidates, r):
                total_notional = sum(c.notional_usd for c in combo)
                if total_notional > self.venue_cap_usd:
                    continue

                combo_valid = True
                for candidate in combo:
                    if use_canonical:
                        asset_current = self._current_notional_for_ticker(candidate, canonical_live_positions)
                    else:
                        asset_current = current_positions.get(candidate.asset, 0.0)
                    asset_with_order = candidate.notional_usd
                    max_asset_notional = self.venue_cap_usd * self.max_single_asset_fraction
                    if (asset_current + asset_with_order) > max_asset_notional:
                        combo_valid = False
                        break

                if not combo_valid:
                    continue

                total_edge = sum(c.edge_score for c in combo)
                if total_edge > best_total_edge or (total_edge == best_total_edge and total_notional < best_total_notional):
                    best_combination = list(combo)
                    best_total_edge = total_edge
                    best_total_notional = total_notional

        chosen = best_combination
        used_notional = best_total_notional if best_total_notional != float('inf') else 0.0

        # Determine knapsack feasibility for each unique candidate for precise telemetry.
        max_asset_notional = self.venue_cap_usd * self.max_single_asset_fraction
        feasible_by_candidate: Dict[str, bool] = {c.candidate_id or f"oc-{id(c)}": False for c in unique_candidates}
        asset_cap_violation: Dict[str, bool] = {c.candidate_id or f"oc-{id(c)}": False for c in unique_candidates}

        for r in range(1, n + 1):
            for combo in combinations(unique_candidates, r):
                total_notional = sum(c.notional_usd for c in combo)
                if total_notional > self.venue_cap_usd:
                    continue

                combo_valid = True
                for candidate in combo:
                    if use_canonical:
                        asset_current = self._current_notional_for_ticker(candidate, canonical_live_positions)
                    else:
                        asset_current = current_positions.get(candidate.asset, 0.0)
                    asset_with_order = candidate.notional_usd
                    if (asset_current + asset_with_order) > max_asset_notional:
                        combo_valid = False
                        break

                if not combo_valid:
                    continue

                for candidate in combo:
                    cid = candidate.candidate_id or f"oc-{id(candidate)}"
                    feasible_by_candidate[cid] = True

        for c in unique_candidates:
            cid = c.candidate_id or f"oc-{id(c)}"
            if use_canonical:
                asset_current = self._current_notional_for_ticker(c, canonical_live_positions)
            else:
                asset_current = current_positions.get(c.asset, 0.0)
            if (asset_current + c.notional_usd) > max_asset_notional:
                asset_cap_violation[cid] = True

        chosen_ids = {c.candidate_id or f"oc-{id(c)}" for c in chosen}
        for c in unique_candidates:
            cid = c.candidate_id or f"oc-{id(c)}"
            d = unique_decisions.get(cid)
            if d is None:
                continue

            if cid in chosen_ids:
                d.stage_results["ASSET_CAP"] = "PASS"
                d.stage_results["BUDGET"] = "PASS"
                d.stage_results["KNAPSACK"] = "SELECTED"
                d.selected = True
                d.approved_quantity_fp = float(c.count)
                logger.info(
                    "[GLOBAL-ALLOCATOR] CHOOSE %s: edge=%.3f%%, conf=%.0f%%, price=%dc, notional=$%.2f",
                    c.asset, _to_edge_percent(c.edge_pct), c.confidence * 100, c.price_cents, c.notional_usd
                )
            else:
                d.stage_results["ASSET_CAP"] = "FAIL" if asset_cap_violation.get(cid, False) else "PASS"
                if asset_cap_violation.get(cid, False):
                    d.stage_results["BUDGET"] = "N/A"
                    d.stage_results["KNAPSACK"] = "N/A"
                    _mark_terminal(d, "ASSET_CAP", REASON_ASSET_CAP)
                elif not feasible_by_candidate.get(cid, False):
                    d.stage_results["ASSET_CAP"] = "PASS"
                    d.stage_results["BUDGET"] = "FAIL"
                    d.stage_results["KNAPSACK"] = "N/A"
                    _mark_terminal(d, "BUDGET", REASON_BUDGET_LIMIT)
                else:
                    d.stage_results["ASSET_CAP"] = "PASS"
                    d.stage_results["BUDGET"] = "PASS"
                    d.stage_results["KNAPSACK"] = "FAIL"
                    _mark_terminal(d, "KNAPSACK", REASON_KNAPSACK_CAP)

        logger.info(
            "[GLOBAL-ALLOCATOR] Allocation complete: %d/%d chosen, total_notional=$%.2f/$%.2f (%.1f%% utilization)",
            len(chosen), len(candidates), used_notional, self.venue_cap_usd,
            (used_notional / self.venue_cap_usd) * 100 if self.venue_cap_usd else 0.0
        )

        return chosen
    
    def get_allocation_summary(
        self,
        chosen: List[OrderCandidate]
    ) -> Dict[str, Any]:
        """
        Get summary of allocation decisions.
        
        Args:
            chosen: List of chosen orders
        
        Returns:
            Summary dict with allocation statistics
        """
        if not chosen:
            return {
                "total_orders": 0,
                "total_notional": 0.0,
                "asset_breakdown": {},
                "avg_edge": 0.0,
                "utilization_pct": 0.0
            }
        
        total_notional = sum(c.notional_usd for c in chosen)
        asset_breakdown = {}
        for c in chosen:
            asset_breakdown[c.asset] = asset_breakdown.get(c.asset, 0.0) + c.notional_usd
        
        avg_edge = sum(_to_edge_percent(c.edge_pct) for c in chosen) / len(chosen)
        
        return {
            "total_orders": len(chosen),
            "total_notional": total_notional,
            "asset_breakdown": asset_breakdown,
            "avg_edge": avg_edge,
            "utilization_pct": (total_notional / self.venue_cap_usd) * 100
        }

    def get_allocation_decisions(
        self,
        cycle_id: Any,
    ) -> List[AllocationDecision]:
        """
        Return the per-candidate allocation decisions recorded for ``cycle_id``.

        Decisions are cleared at the start of each ``allocate()`` call for the
        supplied ``cycle_id`` so stale results from previous ticks are never
        returned.
        """
        return self._allocation_decisions.get(cycle_id, [])

    def record_order_submitted(self, asset: str, order_id: str, notional_usd: float) -> None:
        """
        Record that an order was submitted for an asset.
        
        This should be called after order_router.route_order_async() returns success.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            order_id: Order ID from order router
            notional_usd: Order notional in USD
        """
        self._pending_orders[asset] = order_id
        self._pending_order_timestamps[asset] = time.time()
        logger.info(
            "[GLOBAL-ALLOCATOR] Order submitted: asset=%s order_id=%s notional=$%.2f",
            asset, order_id, notional_usd
        )
    
    def record_order_filled(self, asset: str, order_id: str, fill_notional_usd: float) -> None:
        """
        Record that an order was filled for an asset.
        
        This should be called from position_cache.on_fill or order_router on fill.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            order_id: Order ID
            fill_notional_usd: Fill notional in USD
        """
        # Remove from pending orders
        if asset in self._pending_orders:
            del self._pending_orders[asset]
            del self._pending_order_timestamps[asset]
        
        # Update position
        self._asset_positions[asset] = fill_notional_usd
        
        logger.info(
            "[GLOBAL-ALLOCATOR] Order filled: asset=%s order_id=%s notional=$%.2f position=$%.2f",
            asset, order_id, fill_notional_usd, self._asset_positions[asset]
        )
    
    def record_order_rejected(self, asset: str, order_id: str) -> None:
        """
        Record that an order was rejected for an asset.
        
        This should be called from order_router on rejection.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            order_id: Order ID
        """
        # Remove from pending orders
        if asset in self._pending_orders:
            del self._pending_orders[asset]
            del self._pending_order_timestamps[asset]
        
        logger.warning(
            "[GLOBAL-ALLOCATOR] Order rejected: asset=%s order_id=%s",
            asset, order_id
        )
    
    def record_position_closed(self, asset: str) -> None:
        """
        Record that a position was closed for an asset.
        
        This should be called when a position is fully closed (sell fill).
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
        """
        if asset in self._asset_positions:
            del self._asset_positions[asset]
            logger.info(
                "[GLOBAL-ALLOCATOR] Position closed: asset=%s",
                asset
            )
    
    def get_asset_positions(self) -> Dict[str, float]:
        """Get current asset positions."""
        return self._asset_positions.copy()
    
    def get_pending_orders(self) -> Dict[str, str]:
        """Get current pending orders."""
        return self._pending_orders.copy()
    
    def has_pending_order(self, asset: str) -> bool:
        """
        Check if an asset has a pending order (non-stale).
        
        This is used for pre-submission enforcement to prevent multiple orders
        for the same asset from being submitted before fills occur.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            
        Returns:
            True if asset has a non-stale pending order, False otherwise
        """
        if asset not in self._pending_orders:
            return False
        
        # Check if pending order is stale
        time_since_submit = time.time() - self._pending_order_timestamps.get(asset, 0)
        if time_since_submit >= self._pending_order_timeout:
            # Stale pending order - clear it
            logger.warning(
                "[GLOBAL-ALLOCATOR] Clearing stale pending order for %s: %.1fs old",
                asset, time_since_submit
            )
            del self._pending_orders[asset]
            del self._pending_order_timestamps[asset]
            return False
        
        return True


# Singleton instance for lifecycle callbacks
_global_allocator_instance: Optional[GlobalAllocator] = None

def get_global_allocator() -> Optional[GlobalAllocator]:
    """Get the singleton GlobalAllocator instance for lifecycle callbacks."""
    return _global_allocator_instance

def set_global_allocator(allocator: GlobalAllocator) -> None:
    """Set the singleton GlobalAllocator instance."""
    global _global_allocator_instance
    _global_allocator_instance = allocator


def create_global_allocator_from_envelope(envelope: Any) -> GlobalAllocator:
    """
    Create GlobalAllocator from risk envelope configuration.
    
    CRITICAL: Uses shared $1 pool model with per-asset edge thresholds aligned with risk_parameters.py.
    
    Args:
        envelope: Risk envelope instance
    
    Returns:
        Configured GlobalAllocator with shared $1 pool parameters and per-asset edge thresholds
    """
    venue_cap = envelope.max_total_notional_usd if hasattr(envelope, 'max_total_notional_usd') else 1.00
    
    # CRITICAL: Use the shared $1 pool parameters (no per-asset rescaling)
    min_edge_pct = 0.025  # 2026-07-14: Changed from 0.5% to 2.5% to match profile edge_bands (industry standard)
                       # 2026-07-25: CRITICAL - Stored as FRACTION (0.025 = 2.5%), not percentage
    min_confidence = 0.50  # 2026-07-28: CRITICAL FIX - Lowered from 0.65 to 0.50 to match signal generation range
                          # Signal generation produces confidence = 0.5 + edge (edge is 0.02-0.08), resulting in 52-58%
                          # Previous 65% threshold was blocking all candidates despite valid edge
    min_price_cents = 10  # 2026-07-12: Lower bound (10c) maintained for low-profit trap prevention
    max_price_cents = 75  # 2026-07-12: Expanded to 75c - YES prices consistently 60-97c in current market conditions
    max_single_asset_fraction = 1.00  # 100% - allows single asset to use full venue cap (shared pool)
    
    # 2026-07-14: Per-asset edge thresholds aligned with profile edge_bands (2.5% unified)
    # 2026-07-25: CRITICAL - All thresholds stored as FRACTIONS (0.025 = 2.5%), not percentages
    # CRITICAL FIX: Updated to use unified 2.5% threshold from profile edge_bands (industry standard)
    # Industry standard for Kalshi: 3% raw edge minimum (Market Math, Beatpoly)
    # Kalshi 7% winner fee turns <2% edge into breakeven/negative EV
    per_asset_min_edge_pct = {
        "BTC": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
        "ETH": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
        "SOL": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
        "XRP": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
        "DOGE": 0.025,  # Unified edge_bands threshold (2.5% = 0.025 fraction - industry standard)
    }
    
    # Optional: read allocator knobs from envelope if available
    if hasattr(envelope, 'allocator_config'):
        config = envelope.allocator_config
        min_edge_pct = config.get('min_edge_pct', 0.05)
        min_confidence = config.get('min_confidence', 0.65)
        min_price_cents = config.get('min_price_cents', 10)
        max_price_cents = config.get('max_price_cents', 75)  # 2026-07-12: Default 75c to match current market conditions
        max_single_asset_fraction = config.get('max_single_asset_fraction', 1.00)
        # Allow envelope to override per-asset thresholds if provided
        if 'per_asset_min_edge_pct' in config:
            per_asset_min_edge_pct = config['per_asset_min_edge_pct']
    
    return GlobalAllocator(
        venue_cap_usd=venue_cap,
        min_edge_pct=min_edge_pct,
        min_confidence=min_confidence,
        min_price_cents=min_price_cents,
        max_price_cents=max_price_cents,
        max_single_asset_fraction=max_single_asset_fraction,
        per_asset_min_edge_pct=per_asset_min_edge_pct
    )
