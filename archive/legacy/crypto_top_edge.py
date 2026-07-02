"""Crypto Top Edge Arbiter — Cross-asset, top-edge selection with dynamic floor.

Implements the cross-asset edge ranking and dynamic floor logic as described in:
- Section 1: Change the decision question (collect all candidates, normalize, rank, select top N)
- Section 2: Dynamic edge floor across assets (cross-sectional + rolling distribution)
- Section 3: Integration into existing logs/agents

STRATEGY IDENTITY: Mean-Reversion Scalping
- Entry: Fade price extremes when they re-enter Bollinger Bands (short upper touches, long lower touches)
- Regime: Range-only (ADX < 20), avoid trending markets
- Exit: Target mid-band (SMA) with ATR-based stop loss

This module sits BEFORE the guard/risk engine so BTC, ETH, SOL, XRP, DOGE always
compete for capital on a relative edge basis instead of only absolute cutoffs.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median, mean, stdev
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.crypto_top_edge")

# Supported crypto assets for cross-asset ranking
CRYPTO_ASSETS: Set[str] = {"BTC", "ETH", "SOL", "XRP", "DOGE"}

# Mean-reversion scalping timeframes (15m ONLY for execution)
# 1h/daily/weekly timeframes are used for regime context only, NOT for execution
# This ensures pure 15m mean-reversion without timeframe overlap
MEAN_REVERSION_TIMEFRAMES: Set[str] = {"15m"}

# Configurable parameters (env var overrides)
DEFAULT_GAMMA: float = 0.5  # γ ∈ [0.3, 0.7] for dynamic floor as % of top/median edge (REVERTED from 0.7 to restore trade volume)
DEFAULT_ALPHA: float = 0.0  # α for μ + α·σ floor (0 = use median)
DEFAULT_TOP_N: int = 3  # How many winners to select per cycle (REVERTED from 1 to restore trade volume)
DEFAULT_MIN_EDGE_ABSOLUTE: float = 0.0  # Absolute minimum edge to consider (REVERTED from 0.015 to allow lower-edge trades)
DEFAULT_ROLLING_WINDOW_SIZE: int = 100  # Window for rolling edge history per asset
DEFAULT_MAX_HOLD_MINUTES: int = 240  # Maximum holding time for scalps (4 hours)

# Deduplication settings
DEFAULT_POSITION_DEDUP_ENABLED: bool = True
DEFAULT_IN_CYCLE_DEDUP_ENABLED: bool = True


@dataclass
class CandidateSignal:
    """A candidate signal from a strategy agent for cross-asset ranking."""
    
    # Identification
    signal_id: str  # Unique per cycle
    agent_id: str  # e.g., "BTC_15M", "ETH_1H"
    asset: str  # BTC, ETH, SOL, XRP, DOGE
    timeframe: str  # 15m, 1h, daily, weekly
    ticker: str  # Full Kalshi ticker
    
    # Edge data
    net_edge: float  # Normalized edge (expected PnL per unit risk or Kelly fraction)
    raw_edge: Optional[float] = None  # Original edge before normalization
    confidence: float = 0.0  # Model confidence (0-1)
    
    # Trade details (for downstream execution)
    direction: str = "none"  # "long", "short", or "none"
    suggested_contracts: int = 0
    limit_price_cents: Optional[int] = None
    
    # Source tracking
    archetype: str = "directional"  # directional, contrarian, arb, etc.
    original_signal: Optional[Any] = None  # Reference to original StrategySignal
    
    # Metadata for logging
    phase: Optional[str] = None  # EARLY, MID, LATE, TERMINAL
    correlation_id: Optional[str] = None
    eval_context: Dict[str, Any] = field(default_factory=dict)
    
    # Position tracking for deduplication
    existing_position_contracts: int = 0  # Current position in this market/direction
    existing_position_direction: str = "none"  # "long", "short", or "none"
    position_entry_time: Optional[float] = None  # Epoch seconds when position opened
    
    # Decision result (filled by arbiter)
    is_winner: bool = False
    rejection_reason: Optional[str] = None  # Why this signal was rejected
    rank: int = 0  # 1 = best edge
    selection_method: str = ""  # How selected (e.g., "top_2", "dynamic_floor")
    incremental_contracts: int = 0  # Contracts to add (after position dedup)


@dataclass
class CrossAssetCycleResult:
    """Result of a cross-asset cycle evaluation."""
    
    cycle_timestamp: datetime
    cycle_id: str
    
    # All candidates and winners
    all_candidates: List[CandidateSignal]
    winners: List[CandidateSignal]
    
    # Statistics
    top_edge: float
    median_edge: float
    mean_edge: float
    std_edge: Optional[float]
    dynamic_floor: float
    global_floor: float
    final_floor: float  # max(dynamic_floor, global_floor, 0)
    
    # Summary
    assets_considered: Set[str]
    assets_selected: Set[str]
    total_signals: int
    rejected_by_floor: int
    rejected_by_negative_edge: int
    rejected_by_timeframe: int  # Not in momentum scalping timeframes
    rejected_by_position_dup: int  # Already have position in this market
    rejected_by_cycle_dup: int  # Duplicate within cycle
    deduped_contracts_saved: int  # Contracts not ordered due to position dedup
    
    # Logging context
    gamma_used: float
    alpha_used: float
    top_n_used: int
    timeframe_filter_used: Set[str]  # Which timeframes were considered
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging and API responses."""
        return {
            "cycle_id": self.cycle_id,
            "timestamp": self.cycle_timestamp.isoformat(),
            "stats": {
                "top_edge": round(self.top_edge, 6),
                "median_edge": round(self.median_edge, 6),
                "mean_edge": round(self.mean_edge, 6),
                "std_edge": round(self.std_edge, 6) if self.std_edge else None,
                "dynamic_floor": round(self.dynamic_floor, 6),
                "global_floor": round(self.global_floor, 6),
                "final_floor": round(self.final_floor, 6),
            },
            "selection": {
                "total_candidates": self.total_signals,
                "winners_count": len(self.winners),
                "rejected_by_floor": self.rejected_by_floor,
                "rejected_by_negative_edge": self.rejected_by_negative_edge,
                "rejected_by_timeframe": self.rejected_by_timeframe,
                "rejected_by_position_dup": self.rejected_by_position_dup,
                "rejected_by_cycle_dup": self.rejected_by_cycle_dup,
                "deduped_contracts_saved": self.deduped_contracts_saved,
                "assets_considered": list(self.assets_considered),
                "assets_selected": list(self.assets_selected),
                "timeframes_considered": list(self.timeframe_filter_used),
                "gamma": self.gamma_used,
                "alpha": self.alpha_used,
                "top_n": self.top_n_used,
            },
            "winners": [
                {
                    "rank": w.rank,
                    "asset": w.asset,
                    "timeframe": w.timeframe,
                    "agent_id": w.agent_id,
                    "net_edge": round(w.net_edge, 6),
                    "direction": w.direction,
                    "contracts": w.suggested_contracts,
                    "archetype": w.archetype,
                }
                for w in self.winners
            ],
        }


class RollingEdgeHistory:
    """Rolling window of edge history for global floor calculation."""
    
    def __init__(self, max_size: int = DEFAULT_ROLLING_WINDOW_SIZE):
        self._max_size = max_size
        self._edges: List[float] = []  # All recent edges across all assets
        self._asset_edges: Dict[str, List[float]] = {a: [] for a in CRYPTO_ASSETS}
        self._lock = threading.RLock()
    
    def record(self, asset: str, edge: float, timestamp: Optional[float] = None) -> None:
        """Record an edge observation."""
        import time as _time
        print(f"[LOCK-DEBUG] acquiring _lock in record() at {_time.time()}")
        with self._lock:
            print(f"[LOCK-DEBUG] acquired _lock in record() at {_time.time()}")
            ts = timestamp or time.time()
            self._edges.append((edge, ts))
            self._asset_edges[asset].append((edge, ts))
            
            # Prune old entries
            cutoff = ts - (24 * 3600)  # 24 hour retention
            self._edges = [(e, t) for e, t in self._edges if t > cutoff]
            for a in CRYPTO_ASSETS:
                self._asset_edges[a] = [(e, t) for e, t in self._asset_edges[a] if t > cutoff]
            
            # Cap size
            if len(self._edges) > self._max_size:
                self._edges = self._edges[-self._max_size:]
            for a in CRYPTO_ASSETS:
                if len(self._asset_edges[a]) > self._max_size // len(CRYPTO_ASSETS):
                    self._asset_edges[a] = self._asset_edges[a][-(self._max_size // len(CRYPTO_ASSETS)):]
            print(f"[LOCK-DEBUG] releasing _lock in record() at {_time.time()}")
        print(f"[LOCK-DEBUG] released _lock in record() at {_time.time()}")
    
    def get_stats(self, min_samples: int = 20) -> Optional[Tuple[float, float, float]]:
        """Get (mean, std, p80) of recent edge distribution.
        
        Returns:
            Tuple of (mean, std, 80th percentile) or None if insufficient data
        """
        with self._lock:
            if len(self._edges) < min_samples:
                return None
            
            edges = [e for e, t in self._edges]
            mu = mean(edges)
            sigma = stdev(edges) if len(edges) > 1 else 0.0
            
            # 80th percentile
            sorted_edges = sorted(edges)
            p80_idx = int(len(sorted_edges) * 0.8)
            p80 = sorted_edges[min(p80_idx, len(sorted_edges) - 1)]
            
            return (mu, sigma, p80)
    
    def get_asset_stats(self, asset: str, min_samples: int = 10) -> Optional[Tuple[float, float]]:
        """Get per-asset (mean, std)."""
        with self._lock:
            edges = [e for e, t in self._asset_edges.get(asset, [])]
            if len(edges) < min_samples:
                return None
            return (mean(edges), stdev(edges) if len(edges) > 1 else 0.0)


class CryptoTopEdgeArbiter:
    """Cross-asset arbiter that selects top edges with dynamic floor.
    
    Responsibilities:
    1. Collect candidate signals from all crypto agents per cycle
    2. Filter to momentum scalping timeframes (15m, 1h only)
    3. Compute cross-sectional statistics (top, median, std)
    4. Apply dynamic floor = max(0, γ × top_edge) or (μ + α·σ)
    5. Position-aware deduplication (skip if already positioned)
    6. In-cycle fingerprint deduplication (no duplicate orders)
    7. Select top N winners, pass to risk/exec layer
    8. Log with `consensus_hold_by_reason` when all candidates rejected
    
    Thread-safe. Designed to be called once per cycle before risk gates.
    """
    
    def __init__(
        self,
        gamma: Optional[float] = None,
        alpha: Optional[float] = None,
        top_n: Optional[int] = None,
        min_edge_absolute: Optional[float] = None,
        timeframes: Optional[Set[str]] = None,
        max_hold_minutes: Optional[int] = None,
        position_dedup_enabled: Optional[bool] = None,
        in_cycle_dedup_enabled: Optional[bool] = None,
    ):
        self._gamma = gamma if gamma is not None else float(os.getenv("CRYPTO_TOP_EDGE_GAMMA", str(DEFAULT_GAMMA)))
        self._alpha = alpha if alpha is not None else float(os.getenv("CRYPTO_TOP_EDGE_ALPHA", str(DEFAULT_ALPHA)))
        self._top_n = top_n if top_n is not None else int(os.getenv("CRYPTO_TOP_EDGE_TOP_N", str(DEFAULT_TOP_N)))
        self._min_edge_absolute = min_edge_absolute if min_edge_absolute is not None else float(
            os.getenv("CRYPTO_TOP_EDGE_MIN_EDGE", str(DEFAULT_MIN_EDGE_ABSOLUTE))
        )
        
        # Timeframe filtering for mean-reversion scalping
        self._timeframes = timeframes if timeframes is not None else MEAN_REVERSION_TIMEFRAMES
        
        # Position deduplication settings
        self._max_hold_minutes = max_hold_minutes if max_hold_minutes is not None else int(
            os.getenv("CRYPTO_TOP_EDGE_MAX_HOLD_MIN", str(DEFAULT_MAX_HOLD_MINUTES))
        )
        self._position_dedup_enabled = position_dedup_enabled if position_dedup_enabled is not None else (
            os.getenv("CRYPTO_TOP_EDGE_POSITION_DEDUP", str(DEFAULT_POSITION_DEDUP_ENABLED)).lower() in ("1", "true", "yes", "on")
        )
        self._in_cycle_dedup_enabled = in_cycle_dedup_enabled if in_cycle_dedup_enabled is not None else (
            os.getenv("CRYPTO_TOP_EDGE_CYCLE_DEDUP", str(DEFAULT_IN_CYCLE_DEDUP_ENABLED)).lower() in ("1", "true", "yes", "on")
        )
        
        # Clamp gamma to [0.3, 0.7]
        self._gamma = max(0.3, min(0.7, self._gamma))
        
        # Rolling history for global floor
        self._history = RollingEdgeHistory()
        
        # Current cycle storage (cleared each cycle)
        self._current_candidates: List[CandidateSignal] = []
        self._cycle_lock = threading.RLock()
        
        # PRODUCTION FIX v6 (2026-04-26): Store last cycle winners for arbiter winner checks
        # _current_candidates is cleared at start of run_cycle(), so we need to preserve winners
        self._last_cycle_winners: Dict[str, CandidateSignal] = {}  # ticker -> winner
        self._last_cycle_timestamp: Optional[datetime] = None
        
        # In-cycle deduplication fingerprint set
        self._cycle_fingerprints: Set[str] = set()
        
        # Metrics
        self._cycles_run = 0
        self._total_winners = 0
        self._total_contracts_deduped = 0
        
        logger.info(
            "[CRYPTO_TOP_EDGE] Initialized gamma=%.2f alpha=%.2f top_n=%d min_edge=%.4f "
            "timeframes=%s position_dedup=%s cycle_dedup=%s max_hold_min=%d",
            self._gamma, self._alpha, self._top_n, self._min_edge_absolute,
            sorted(self._timeframes), self._position_dedup_enabled, 
            self._in_cycle_dedup_enabled, self._max_hold_minutes
        )
    
    def submit_candidate(self, candidate: CandidateSignal) -> None:
        """Submit a candidate signal for consideration in the next cycle.
        
        Call this from each strategy agent's PM_SIGNAL emission.
        """
        # Timeframe filtering - only accept momentum scalping timeframes
        if candidate.timeframe not in self._timeframes:
            logger.debug(
                "[CRYPTO_TOP_EDGE] Rejecting candidate %s: timeframe %s not in %s",
                candidate.signal_id, candidate.timeframe, self._timeframes
            )
            return
        
        # DYNAMIC ENTRY WINDOW: Check if candidate is within allowed window (strict mode)
        from merid.prediction.dynamic_entry_window import resolve_entry_window
        
        # Extract minutes_to_expiry from eval_context if available
        minutes_to_expiry = candidate.eval_context.get("minutes_to_expiry")
        edge_pct = candidate.net_edge * 100 if candidate.net_edge else None
        
        if minutes_to_expiry is not None:
            resolution = resolve_entry_window(
                asset=candidate.asset,
                minutes_to_expiry=minutes_to_expiry,
                edge_pct=edge_pct,
                ticker=None  # Candidate context doesn't have specific ticker
            )
            
            if not resolution.allowed:
                candidate.rejection_reason = f"dynamic_window:{resolution.reason.value}"
                logger.info(
                    "[CRYPTO_TOP_EDGE] Rejecting candidate %s: outside dynamic window | "
                    "asset=%s minutes_to_expiry=%.1f reason=%s policy=%s bucket=%s",
                    candidate.signal_id,
                    candidate.asset,
                    minutes_to_expiry,
                    resolution.reason.value,
                    resolution.active_policy_name,
                    resolution.bucket
                )
                return
            else:
                # Tag candidate with policy metadata for downstream tracking
                candidate.eval_context["entry_window_policy_name"] = resolution.active_policy_name
                candidate.eval_context["entry_window_bucket"] = resolution.bucket
                candidate.eval_context["entry_window_decision_reason"] = resolution.reason.value
        
        import time as _time
        print(f"[LOCK-DEBUG] acquiring _cycle_lock in submit_candidate at {_time.time()}")
        with self._cycle_lock:
            print(f"[LOCK-DEBUG] acquired _cycle_lock in submit_candidate at {_time.time()}")
            self._current_candidates.append(candidate)
            print(f"[LOCK-DEBUG] releasing _cycle_lock in submit_candidate at {_time.time()}")
        print(f"[LOCK-DEBUG] released _cycle_lock in submit_candidate at {_time.time()}")
    
    def _get_position_fingerprint(self, candidate: CandidateSignal) -> str:
        """Generate a fingerprint for position deduplication.
        
        Format: ticker:direction:strategy_family
        """
        strategy_family = candidate.archetype if candidate.archetype else "directional"
        return f"{candidate.ticker}:{candidate.direction}:{strategy_family}"
    
    def _apply_position_deduplication(
        self, 
        candidates: List[CandidateSignal]
    ) -> Tuple[List[CandidateSignal], int, int]:
        """Apply position-aware deduplication to candidates.
        
        For each candidate:
        - If no existing position: keep as-is
        - If existing position in same direction at target size: skip (duplicate)
        - If existing position in same direction below target: adjust to incremental size
        - If existing position in opposite direction: treat as fresh (risk layer handles flip)
        
        Args:
            candidates: List of candidate signals
            
        Returns:
            Tuple of (deduped_candidates, rejected_count, contracts_saved)
        """
        if not self._position_dedup_enabled:
            return candidates, 0, 0
        
        result = []
        rejected_count = 0
        contracts_saved = 0
        now = time.time()
        max_hold_seconds = self._max_hold_minutes * 60
        
        for c in candidates:
            # Skip if no position data available
            if c.existing_position_direction == "none" or c.existing_position_contracts == 0:
                result.append(c)
                continue
            
            # Check if position is too old (scalp expired, treat as fresh)
            if c.position_entry_time and (now - c.position_entry_time) > max_hold_seconds:
                logger.debug(
                    "[CRYPTO_TOP_EDGE] Position for %s expired (age=%.0f min > %d min), treating as fresh",
                    c.ticker, (now - c.position_entry_time) / 60, self._max_hold_minutes
                )
                result.append(c)
                continue
            
            # Same direction - check for duplication or partial fill
            if c.existing_position_direction == c.direction:
                if c.existing_position_contracts >= c.suggested_contracts:
                    # Already at or above target size - skip
                    c.rejection_reason = "position_already_at_target_size"
                    c.is_winner = False
                    rejected_count += 1
                    contracts_saved += c.suggested_contracts
                    logger.debug(
                        "[CRYPTO_TOP_EDGE] DEDUP: %s %s already has %d contracts (target=%d)",
                        c.ticker, c.direction, c.existing_position_contracts, c.suggested_contracts
                    )
                else:
                    # Partial position - emit incremental size
                    incremental = c.suggested_contracts - c.existing_position_contracts
                    c.incremental_contracts = incremental
                    c.suggested_contracts = incremental  # Adjust to only what's needed
                    result.append(c)
                    contracts_saved += (c.suggested_contracts - incremental)
                    logger.debug(
                        "[CRYPTO_TOP_EDGE] PARTIAL: %s %s has %d, adding %d incremental (target=%d)",
                        c.ticker, c.direction, c.existing_position_contracts, 
                        incremental, c.suggested_contracts + c.existing_position_contracts
                    )
            else:
                # Opposite direction - let risk layer handle the flip
                result.append(c)
        
        return result, rejected_count, contracts_saved
    
    def _apply_in_cycle_deduplication(
        self, 
        candidates: List[CandidateSignal]
    ) -> Tuple[List[CandidateSignal], int]:
        """Apply in-cycle deduplication to prevent duplicate orders within same cycle.
        
        Deduplicates by (ticker, direction, strategy_family) fingerprint.
        
        Args:
            candidates: List of candidate signals
            
        Returns:
            Tuple of (deduped_candidates, rejected_count)
        """
        if not self._in_cycle_dedup_enabled:
            return candidates, 0
        
        result = []
        rejected_count = 0
        
        # Clear fingerprints at start of each cycle's dedup phase
        self._cycle_fingerprints.clear()
        
        for c in candidates:
            fingerprint = self._get_position_fingerprint(c)
            
            if fingerprint in self._cycle_fingerprints:
                # Duplicate within cycle
                c.rejection_reason = "duplicate_within_cycle"
                c.is_winner = False
                rejected_count += 1
                logger.info(
                    "[CRYPTO_TOP_EDGE] CYCLE_DEDUP: %s %s %s rejected (duplicate within cycle)",
                    c.ticker, c.direction, c.archetype
                )
            else:
                self._cycle_fingerprints.add(fingerprint)
                result.append(c)
        
        return result, rejected_count
    
    def submit_from_strategy_signal(
        self,
        signal: Any,  # StrategySignal
        agent_id: str,
        asset: str,
        timeframe: str,
        ticker: str,
    ) -> None:
        """Convenience method to submit from a StrategySignal."""
        if asset not in CRYPTO_ASSETS:
            return  # Only track crypto assets
        
        # Skip NO_ACTION signals - they don't compete for capital
        if hasattr(signal, 'action') and signal.action.value == 'no_action':
            return
        
        # Extract edge from signal
        net_edge = 0.0
        if hasattr(signal, 'edge') and signal.edge:
            try:
                net_edge = float(signal.edge.net_edge) if hasattr(signal.edge, 'net_edge') else 0.0
            except (TypeError, ValueError):
                net_edge = 0.0
        
        # Extract confidence
        confidence = 0.0
        if hasattr(signal, 'edge') and signal.edge:
            try:
                confidence = float(signal.edge.confidence) if hasattr(signal.edge, 'confidence') else 0.0
            except (TypeError, ValueError):
                confidence = 0.0
        
        # Extract direction from action
        direction = "none"
        if hasattr(signal, 'action'):
            action_val = signal.action.value if hasattr(signal.action, 'value') else str(signal.action)
            if 'buy_yes' in action_val or 'buy' in action_val:
                direction = "long"
            elif 'buy_no' in action_val or 'sell' in action_val:
                direction = "short"
        
        # Get side from signal if available
        side = getattr(signal, 'side', 'none')
        if side == 'yes' or side == 'YES':
            direction = "long"
        elif side == 'no' or side == 'NO':
            direction = "short"
        
        candidate = CandidateSignal(
            signal_id=f"{agent_id}_{int(time.time() * 1000)}",
            agent_id=agent_id,
            asset=asset,
            timeframe=timeframe,
            ticker=ticker,
            net_edge=net_edge,
            confidence=confidence,
            direction=direction,
            suggested_contracts=getattr(signal, 'contracts', 0),
            limit_price_cents=getattr(signal, 'limit_price_cents', None),
            archetype=getattr(signal, 'eval_context', {}).get('archetype', 'directional'),
            original_signal=signal,
            phase=getattr(signal, 'phase', None),
            correlation_id=getattr(signal, 'correlation_id', None),
            eval_context=dict(getattr(signal, 'eval_context', {})),
        )
        
        self.submit_candidate(candidate)
    
    def run_cycle(self, cycle_id: Optional[str] = None) -> CrossAssetCycleResult:
        """Execute the cross-asset selection cycle.
        
        This should be called once per trading cycle, after all agents have
        submitted their candidates and before the risk gate.
        
        The cycle flow:
        1. Collect candidates (already timeframe-filtered at submit time)
        2. Apply position-aware deduplication
        3. Apply in-cycle deduplication
        4. Compute cross-sectional statistics
        5. Apply dynamic floor
        6. Select top N winners
        
        Returns:
            CrossAssetCycleResult with winners and statistics.
        """
        with self._cycle_lock:
            candidates = list(self._current_candidates)
            self._current_candidates = []  # Clear for next cycle
        
        timestamp = datetime.now(timezone.utc)
        cycle_id = cycle_id or f"cte_{int(time.time())}"
        
        self._cycles_run += 1
        
        # Filter to crypto assets only
        crypto_candidates = [c for c in candidates if c.asset in CRYPTO_ASSETS]
        
        # Count timeframe-filtered candidates (those that passed submit filter)
        timeframe_filtered_count = len(crypto_candidates)
        
        if not crypto_candidates:
            # No candidates - return empty result
            return CrossAssetCycleResult(
                cycle_timestamp=timestamp,
                cycle_id=cycle_id,
                all_candidates=[],
                winners=[],
                top_edge=0.0,
                median_edge=0.0,
                mean_edge=0.0,
                std_edge=None,
                dynamic_floor=0.0,
                global_floor=0.0,
                final_floor=0.0,
                assets_considered=set(),
                assets_selected=set(),
                total_signals=0,
                rejected_by_floor=0,
                rejected_by_negative_edge=0,
                rejected_by_timeframe=0,
                rejected_by_position_dup=0,
                rejected_by_cycle_dup=0,
                deduped_contracts_saved=0,
                gamma_used=self._gamma,
                alpha_used=self._alpha,
                top_n_used=self._top_n,
                timeframe_filter_used=set(self._timeframes),
            )
        
        # Step 1: Apply position-aware deduplication
        crypto_candidates, pos_rejected, contracts_saved = self._apply_position_deduplication(
            crypto_candidates
        )
        self._total_contracts_deduped += contracts_saved
        
        # Step 2: Apply in-cycle deduplication
        crypto_candidates, cycle_rejected = self._apply_in_cycle_deduplication(
            crypto_candidates
        )
        
        # Check if all candidates were filtered out by deduplication
        if not crypto_candidates:
            return CrossAssetCycleResult(
                cycle_timestamp=timestamp,
                cycle_id=cycle_id,
                all_candidates=[],
                winners=[],
                top_edge=0.0,
                median_edge=0.0,
                mean_edge=0.0,
                std_edge=None,
                dynamic_floor=0.0,
                global_floor=0.0,
                final_floor=0.0,
                assets_considered=set(c.asset for c in candidates if c.asset in CRYPTO_ASSETS),
                assets_selected=set(),
                total_signals=timeframe_filtered_count,
                rejected_by_floor=0,
                rejected_by_negative_edge=0,
                rejected_by_timeframe=0,
                rejected_by_position_dup=pos_rejected,
                rejected_by_cycle_dup=cycle_rejected,
                deduped_contracts_saved=contracts_saved,
                gamma_used=self._gamma,
                alpha_used=self._alpha,
                top_n_used=self._top_n,
                timeframe_filter_used=set(self._timeframes),
            )
        
        # Record edges in history for future global floor
        for c in crypto_candidates:
            self._history.record(c.asset, c.net_edge)
        
        # Compute cross-sectional statistics
        edges = [c.net_edge for c in crypto_candidates]
        top_edge = max(edges)
        median_edge = median(edges)
        mean_edge = mean(edges)
        std_edge = stdev(edges) if len(edges) > 1 else 0.0
        
        # Compute dynamic floor (cross-sectional)
        # Option A: γ × top_edge
        floor_from_top = max(0.0, self._gamma * top_edge)
        # Option A-alt: γ × median_edge
        floor_from_median = max(0.0, self._gamma * median_edge)
        # Use the more conservative (higher) of the two
        dynamic_floor = max(floor_from_top, floor_from_median)
        
        # Compute global floor from rolling history (if available)
        global_floor = 0.0
        hist_stats = self._history.get_stats(min_samples=20)
        if hist_stats:
            mu, sigma, p80 = hist_stats
            # Use p80 as global floor if alpha is 0, otherwise μ + α·σ
            if self._alpha == 0:
                global_floor = max(0.0, p80)
            else:
                global_floor = max(0.0, mu + self._alpha * sigma)
        
        # FIX (2026-05-11): Cap global_floor at the dynamic_floor from current cycle.
        # When rolling P80 exceeds current cycle's edges (common when edge distribution
        # is narrow/stable), it causes complete lockout (0 qualified winners).
        # The dynamic floor (γ × top_edge) already provides a sensible floor;
        # the global floor should only be a lower safety net, never higher.
        if global_floor > dynamic_floor:
            global_floor = dynamic_floor
        
        # Final floor: max of dynamic, global, and absolute minimum
        final_floor = max(dynamic_floor, global_floor, self._min_edge_absolute)
        
        # Count rejections
        rejected_by_negative = sum(1 for e in edges if e <= 0)
        rejected_by_floor = sum(1 for e in edges if 0 < e < final_floor)
        
        # Select winners
        # Filter: edge > 0 AND edge >= final_floor
        qualified = [c for c in crypto_candidates if c.net_edge > 0 and c.net_edge >= final_floor]
        
        # Sort by edge descending
        qualified.sort(key=lambda x: x.net_edge, reverse=True)
        
        # Take top N
        winners = qualified[:self._top_n]
        
        # Mark winners and assign ranks
        assets_selected = set()
        # PRODUCTION FIX v6 (2026-04-26): Store winners for _is_arbiter_winner checks
        self._last_cycle_winners = {}
        for i, w in enumerate(winners, 1):
            w.is_winner = True
            w.rank = i
            w.selection_method = f"top_{self._top_n}_dynamic_floor"
            assets_selected.add(w.asset)
            self._total_winners += 1
            # Store winner by ticker for later lookup
            self._last_cycle_winners[w.ticker] = w
        
        # BUG-FIX (2026-05-07): Always update timestamp, even if no winners
        # Previous logic only updated timestamp when winners were found, causing
        # stale data warnings when cycles had no eligible candidates
        self._last_cycle_timestamp = datetime.now(timezone.utc)
        
        # Mark rejections on candidates
        for c in crypto_candidates:
            if not c.is_winner:
                if c.net_edge <= 0:
                    c.rejection_reason = "negative_or_zero_edge"
                elif c.net_edge < final_floor:
                    c.rejection_reason = f"below_dynamic_floor_{final_floor:.4f}"
                else:
                    c.rejection_reason = f"not_in_top_{self._top_n}"
        
        # Log the result
        if winners:
            logger.info(
                "[CRYPTO_TOP_EDGE] Cycle=%s TopEdge=%.4f Median=%.4f Floor=%.4f Winners=%d "
                "Assets=%s",
                cycle_id, top_edge, median_edge, final_floor, len(winners),
                ",".join(sorted(assets_selected))
            )
            for w in winners:
                logger.info(
                    "[CRYPTO_TOP_EDGE_WINNER] Rank=%d Asset=%s Ticker=%s Edge=%.4f Agent=%s Dir=%s",
                    w.rank, w.asset, w.ticker, w.net_edge, w.agent_id, w.direction
                )
        else:
            # All candidates rejected - log with consensus_hold_by_reason
            logger.info(
                "[CRYPTO_TOP_EDGE] Cycle=%s TopEdge=%.4f Median=%.4f Floor=%.4f "
                "consensus_hold_by_reason=no_action_by_reason=top_edge_below_dynamic_floor "
                "Qualified=%d RejectedNegative=%d RejectedFloor=%d",
                cycle_id, top_edge, median_edge, final_floor, len(qualified),
                rejected_by_negative, rejected_by_floor
            )
        
        # WINNER ALIGNMENT FIX (2026-05-10): Update GridContext with current cycle winners
        # This provides a centralized winner list for all 15m agents to check
        try:
            from merid.prediction.grid_context import get_grid_context
            grid_ctx = get_grid_context()
            grid_ctx.update_cycle(
                cycle_id=cycle_id,
                top_edge=top_edge,
                median_edge=median_edge,
                floor=final_floor,
                winners=winners,
            )
            logger.debug(
                "[CRYPTO_TOP_EDGE] Updated GridContext with %d winners",
                len(winners)
            )
        except Exception as e:
            logger.warning("[CRYPTO_TOP_EDGE] Failed to update GridContext: %s", e)
        
        return CrossAssetCycleResult(
            cycle_timestamp=timestamp,
            cycle_id=cycle_id,
            all_candidates=crypto_candidates,
            winners=winners,
            top_edge=top_edge,
            median_edge=median_edge,
            mean_edge=mean_edge,
            std_edge=std_edge,
            dynamic_floor=dynamic_floor,
            global_floor=global_floor,
            final_floor=final_floor,
            assets_considered=set(c.asset for c in crypto_candidates),
            assets_selected=assets_selected,
            total_signals=len(crypto_candidates),
            rejected_by_floor=rejected_by_floor,
            rejected_by_negative_edge=rejected_by_negative,
            rejected_by_timeframe=0,  # Already filtered at submit time
            rejected_by_position_dup=pos_rejected,
            rejected_by_cycle_dup=cycle_rejected,
            deduped_contracts_saved=contracts_saved,
            gamma_used=self._gamma,
            alpha_used=self._alpha,
            top_n_used=self._top_n,
            timeframe_filter_used=set(self._timeframes),
        )
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get arbiter metrics for monitoring."""
        return {
            "cycles_run": self._cycles_run,
            "total_winners": self._total_winners,
            "winners_per_cycle": self._total_winners / max(1, self._cycles_run),
            "total_contracts_deduped": self._total_contracts_deduped,
            "config": {
                "gamma": self._gamma,
                "alpha": self._alpha,
                "top_n": self._top_n,
                "min_edge_absolute": self._min_edge_absolute,
                "timeframes": list(self._timeframes),
                "max_hold_minutes": self._max_hold_minutes,
                "position_dedup_enabled": self._position_dedup_enabled,
                "in_cycle_dedup_enabled": self._in_cycle_dedup_enabled,
            },
        }
    
    def is_winner(self, ticker: str, max_age_seconds: float = 30.0) -> bool:
        """Check if a ticker was a winner in the last cycle.
        
        PRODUCTION FIX v6 (2026-04-26): This method allows agents to check
        if their market was selected by the arbiter after the cycle completes.
        The _current_candidates list is cleared at cycle start, so we check
        against _last_cycle_winners which is preserved.
        
        Args:
            ticker: Full Kalshi ticker (e.g., "KXBTC-26APR2717-T87749.99")
            max_age_seconds: Maximum age of the cycle result to consider valid
            
        Returns:
            True if the ticker was a winner in the last cycle (and cycle is fresh)
        """
        with self._cycle_lock:
            if not self._last_cycle_timestamp:
                return False
            
            # Check if cycle result is too old
            age = (datetime.now(timezone.utc) - self._last_cycle_timestamp).total_seconds()
            if age > max_age_seconds:
                return False
            
            # Check if ticker is in winners
            winner = self._last_cycle_winners.get(ticker)
            if winner:
                return winner.is_winner
            return False
    
    def is_number_one_winner(self, ticker: str, max_age_seconds: float = 30.0) -> bool:
        """Check if a ticker was the #1 ranked winner in the last cycle.
        
        PRODUCTION FIX v7 (2026-04-26): Prioritizes the top edge winner over #2 and #3.
        With small bankroll, we only execute #1 to maximize win rate and grow equity.
        As #1 trades profit and bankroll increases, #2 and #3 can be enabled.
        
        Args:
            ticker: Full Kalshi ticker (e.g., "KXBTC-26APR2717-T87749.99")
            max_age_seconds: Maximum age of the cycle result to consider valid
            
        Returns:
            True if the ticker was #1 ranked winner (rank=1) and cycle is fresh
        """
        with self._cycle_lock:
            if not self._last_cycle_timestamp:
                return False
            
            # Check if cycle result is too old
            age = (datetime.now(timezone.utc) - self._last_cycle_timestamp).total_seconds()
            if age > max_age_seconds:
                return False
            
            # Check if ticker is #1 winner
            winner = self._last_cycle_winners.get(ticker)
            if winner and winner.is_winner:
                return winner.rank == 1  # Only #1 ranked
            return False
    
    def get_number_one_winner(self, max_age_seconds: float = 30.0) -> Optional[CandidateSignal]:
        """Get the #1 ranked winner from the last cycle.
        
        PRODUCTION FIX v7 (2026-04-26): Returns the top edge winner for priority execution.
        
        Args:
            max_age_seconds: Maximum age of the cycle result to consider valid
            
        Returns:
            The #1 ranked CandidateSignal, or None if no winner or cycle too old
        """
        with self._cycle_lock:
            if not self._last_cycle_timestamp:
                return None
            
            # Check if cycle result is too old
            age = (datetime.now(timezone.utc) - self._last_cycle_timestamp).total_seconds()
            if age > max_age_seconds:
                return None
            
            # Find #1 winner
            for ticker, winner in self._last_cycle_winners.items():
                if winner.is_winner and winner.rank == 1:
                    return winner
            return None


# Singleton instance
_global_arbiter: Optional[CryptoTopEdgeArbiter] = None
# LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
# Single-threaded FastAPI startup doesn't need lock protection


def get_crypto_top_edge_arbiter(
    gamma: Optional[float] = None,
    alpha: Optional[float] = None,
    top_n: Optional[int] = None,
    min_edge_absolute: Optional[float] = None,
    timeframes: Optional[Set[str]] = None,
    max_hold_minutes: Optional[int] = None,
    position_dedup_enabled: Optional[bool] = None,
    in_cycle_dedup_enabled: Optional[bool] = None,
) -> CryptoTopEdgeArbiter:
    """Get or create the global CryptoTopEdgeArbiter singleton."""
    global _global_arbiter
    if _global_arbiter is None:
        _global_arbiter = CryptoTopEdgeArbiter(
            gamma=gamma,
            alpha=alpha,
            top_n=top_n,
            min_edge_absolute=min_edge_absolute,
            timeframes=timeframes,
            max_hold_minutes=max_hold_minutes,
            position_dedup_enabled=position_dedup_enabled,
            in_cycle_dedup_enabled=in_cycle_dedup_enabled,
        )
    return _global_arbiter


def reset_crypto_top_edge_arbiter() -> None:
    """Reset the singleton (mainly for testing)."""
    global _global_arbiter
    _global_arbiter = None


# Convenience function for one-off cycle runs
def select_top_edges(
    signals: List[CandidateSignal],
    gamma: float = DEFAULT_GAMMA,
    alpha: float = DEFAULT_ALPHA,
    top_n: int = DEFAULT_TOP_N,
    min_edge_absolute: float = DEFAULT_MIN_EDGE_ABSOLUTE,
    timeframes: Optional[Set[str]] = None,
    max_hold_minutes: Optional[int] = None,
    position_dedup_enabled: Optional[bool] = None,
    in_cycle_dedup_enabled: Optional[bool] = None,
) -> CrossAssetCycleResult:
    """One-shot function to select top edges from a list of candidates.
    
    This creates a temporary arbiter, runs the cycle, and returns the result.
    For repeated use, prefer get_crypto_top_edge_arbiter() and submit_candidate().
    """
    arbiter = CryptoTopEdgeArbiter(
        gamma=gamma,
        alpha=alpha,
        top_n=top_n,
        min_edge_absolute=min_edge_absolute,
        timeframes=timeframes,
        max_hold_minutes=max_hold_minutes,
        position_dedup_enabled=position_dedup_enabled,
        in_cycle_dedup_enabled=in_cycle_dedup_enabled,
    )
    
    for sig in signals:
        arbiter.submit_candidate(sig)
    
    return arbiter.run_cycle()
