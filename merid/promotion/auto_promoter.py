"""AutoPromoter — Automated agent promotion from paper to live with operator confirmation.

Implements the promotion pipeline:
  1. Gauntlet results → SLO evaluation
  2. Paper performance → Readiness benchmarks
  3. Operator confirmation → Live mode transition
  4. Failure → Automatic demotion + kill switch

Key safety features:
  - Requires explicit operator confirmation for LIVE transition
  - Automatic demotion on gauntlet failure
  - Per-agent, per-market, per-asset kill switches
  - Integration with ExecutionGuard for fail-closed behavior
"""

import asyncio
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Callable

from utils.logger import get_logger

logger = get_logger("merid.promotion.auto_promoter")


class PromotionState(str, Enum):
    """States in the promotion lifecycle."""
    PENDING = "pending"           # Awaiting gauntlet results
    GAUNTLET_PASS = "gauntlet_pass"  # SLOs satisfied
    PAPER_PROVEN = "paper_proven"    # Paper benchmarks met
    AWAITING_CONFIRMATION = "awaiting_confirmation"  # Needs operator approval
    LIVE = "live"               # Trading live
    DEMOTED = "demoted"         # Failed, back to paper
    KILLED = "killed"           # Critical failure, trading halted


@dataclass
class AgentPromotionStatus:
    """Promotion status for a single agent."""
    agent_id: str
    asset: str
    timeframe: str
    state: PromotionState
    gauntlet_passed: bool = False
    slo_pass_rate: float = 0.0
    paper_trades: int = 0
    paper_win_rate: float = 0.0
    paper_profit_factor: float = 0.0
    ready_for_live: bool = False
    operator_confirmed_at: Optional[datetime] = None
    demotion_reason: Optional[str] = None
    blocked_markets: Set[str] = field(default_factory=set)
    
    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "state": self.state.value,
            "gauntlet_passed": self.gauntlet_passed,
            "slo_pass_rate": round(self.slo_pass_rate, 2),
            "paper_trades": self.paper_trades,
            "paper_win_rate": round(self.paper_win_rate, 2),
            "paper_profit_factor": round(self.paper_profit_factor, 2),
            "ready_for_live": self.ready_for_live,
            "operator_confirmed_at": self.operator_confirmed_at.isoformat() if self.operator_confirmed_at else None,
            "demotion_reason": self.demotion_reason,
            "blocked_markets": list(self.blocked_markets),
        }


class AutoPromoter:
    """Automated promotion controller for MERID agents.
    
    Safety-first design:
    - All transitions logged with full context
    - Operator confirmation required for live
    - Automatic demotion on any failure
    - Kill switch integration for critical issues
    """
    
    def __init__(self):
        self._statuses: Dict[str, AgentPromotionStatus] = {}
        self._lock = threading.RLock()  # Reentrant lock to prevent deadlock in _save_states
        self._callbacks: List[Callable[[str, PromotionState, PromotionState], None]] = []
        
        # Promotion criteria
        self._min_slo_pass_rate = 0.95
        self._min_paper_trades = 50
        self._min_paper_win_rate = 0.48
        self._min_profit_factor = 1.1
        
        # State persistence
        self._state_file = Path("data/promotion_states.json")
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        
        # BUG-FIX (2026-05-12): Defer state load to avoid blocking startup
        # Load states lazily on first access instead of during __init__
        self._states_loaded = False
    
    def _load_states(self):
        """Load persisted promotion states (lazy-loaded on first access)."""
        if self._states_loaded:
            return
        
        if self._state_file.exists():
            try:
                with open(self._state_file) as f:
                    data = json.load(f)
                for agent_id, status_dict in data.items():
                    status = AgentPromotionStatus(
                        agent_id=status_dict["agent_id"],
                        asset=status_dict["asset"],
                        timeframe=status_dict["timeframe"],
                        state=PromotionState(status_dict["state"]),
                        gauntlet_passed=status_dict.get("gauntlet_passed", False),
                        slo_pass_rate=status_dict.get("slo_pass_rate", 0.0),
                        paper_trades=status_dict.get("paper_trades", 0),
                        paper_win_rate=status_dict.get("paper_win_rate", 0.0),
                        paper_profit_factor=status_dict.get("paper_profit_factor", 0.0),
                        blocked_markets=set(status_dict.get("blocked_markets", [])),
                    )
                    self._statuses[agent_id] = status
                logger.info(f"Loaded {len(self._statuses)} promotion states")
            except Exception as e:
                logger.error(f"Failed to load promotion states: {e}")
    
    def _save_states(self):
        """Persist promotion states."""
        with self._lock:
            data = {aid: s.to_dict() for aid, s in self._statuses.items()}
        try:
            with open(self._state_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save promotion states: {e}")
    
    def register_callback(self, callback: Callable[[str, PromotionState, PromotionState], None]):
        """Register callback for state transitions."""
        self._callbacks.append(callback)
    
    def _notify_transition(self, agent_id: str, old: PromotionState, new: PromotionState):
        """Notify all callbacks of state transition."""
        for cb in self._callbacks:
            try:
                cb(agent_id, old, new)
            except Exception as e:
                logger.warning(f"Promotion callback error: {e}")
    
    def get_status(self, agent_id: str) -> Optional[AgentPromotionStatus]:
        """Get promotion status for an agent (triggers lazy load if needed)."""
        self._load_states()  # Lazy load on first access
        with self._lock:
            return self._statuses.get(agent_id)
    
    def initialize_agent(
        self,
        agent_id: str,
        asset: str,
        timeframe: str,
        *,
        persist: bool = True,
        log: bool = True,
    ) -> AgentPromotionStatus:
        """Initialize a new agent in the promotion system.

        For bulk registration (e.g. agent grid), pass ``persist=False`` for each call
        then :meth:`persist_states` once to avoid dozens of disk writes.
        """
        with self._lock:
            if agent_id not in self._statuses:
                status = AgentPromotionStatus(
                    agent_id=agent_id,
                    asset=asset,
                    timeframe=timeframe,
                    state=PromotionState.PENDING,
                )
                self._statuses[agent_id] = status
                if log:
                    logger.info(f"Initialized promotion tracking for {agent_id}")
                if persist:
                    self._save_states()
            return self._statuses[agent_id]

    def persist_states(self) -> None:
        """Write promotion state to disk (after batch ``initialize_agent(..., persist=False)``)."""
        self._save_states()
    
    def record_gauntlet_result(self, agent_id: str, passed: bool, slo_pass_rate: float, failed_slos: List[str]):
        """Record gauntlet results and update promotion state.
        
        If gauntlet fails, automatically demotes to paper and triggers kill switch recommendation.
        """
        with self._lock:
            status = self._statuses.get(agent_id)
            if not status:
                logger.warning(f"Unknown agent {agent_id} - cannot record gauntlet")
                return
            
            old_state = status.state
            status.gauntlet_passed = passed
            status.slo_pass_rate = slo_pass_rate
            
            if not passed:
                status.state = PromotionState.DEMOTED
                status.demotion_reason = f"Gauntlet failed: {', '.join(failed_slos)}"
                status.ready_for_live = False
                # Fail-closed: a LIVE agent that fails gauntlet must not keep trading
                # until markets are reviewed (same sentinel as kill_agent).
                if old_state == PromotionState.LIVE:
                    status.blocked_markets = status.blocked_markets | {"ALL"}
                logger.warning(
                    f"Agent {agent_id} demoted: gauntlet failed",
                    extra={"failed_slos": failed_slos, "pass_rate": slo_pass_rate}
                )
                # Trigger kill switch recommendation for this agent
                self._recommend_agent_kill_switch(agent_id, "gauntlet_failure")
            else:
                if slo_pass_rate >= self._min_slo_pass_rate:
                    status.state = PromotionState.GAUNTLET_PASS
                    logger.info(f"Agent {agent_id} passed gauntlet with {slo_pass_rate:.1%} SLO rate")
                else:
                    status.state = PromotionState.PENDING
                    logger.info(f"Agent {agent_id} gauntlet passed but SLO rate {slo_pass_rate:.1%} below threshold")
            
            self._save_states()
        
        self._notify_transition(agent_id, old_state, status.state)
    
    def record_paper_performance(self, agent_id: str, trades: int, win_rate: float, profit_factor: float):
        """Record paper trading performance.
        
        If benchmarks are met and gauntlet passed, moves to awaiting confirmation.
        """
        with self._lock:
            status = self._statuses.get(agent_id)
            if not status:
                return
            
            old_state = status.state
            status.paper_trades = trades
            status.paper_win_rate = win_rate
            status.paper_profit_factor = profit_factor
            
            # Check if ready for live
            benchmarks_met = (
                trades >= self._min_paper_trades and
                win_rate >= self._min_paper_win_rate and
                profit_factor >= self._min_profit_factor
            )
            
            if benchmarks_met and status.gauntlet_passed:
                status.ready_for_live = True
                if status.state == PromotionState.GAUNTLET_PASS:
                    status.state = PromotionState.AWAITING_CONFIRMATION
                    logger.info(
                        f"Agent {agent_id} ready for live - awaiting operator confirmation",
                        extra={"trades": trades, "win_rate": win_rate, "pf": profit_factor}
                    )
            
            self._save_states()
        
        if status.state != old_state:
            self._notify_transition(agent_id, old_state, status.state)
    
    def confirm_live_trading(self, agent_id: str, operator_id: str) -> bool:
        """Operator confirmation for live trading.
        
        CRITICAL SAFETY: This is the only path to LIVE state.
        Requires explicit human confirmation.
        
        Returns True if successfully promoted.
        """
        with self._lock:
            status = self._statuses.get(agent_id)
            if not status:
                logger.error(f"Cannot confirm live: unknown agent {agent_id}")
                return False
            
            if status.state != PromotionState.AWAITING_CONFIRMATION:
                logger.error(
                    f"Cannot confirm live: agent {agent_id} in state {status.state.value}",
                    extra={"required_state": PromotionState.AWAITING_CONFIRMATION.value}
                )
                return False
            
            if not status.ready_for_live:
                logger.error(f"Cannot confirm live: agent {agent_id} not ready")
                return False
            
            old_state = status.state
            status.state = PromotionState.LIVE
            status.operator_confirmed_at = datetime.now(timezone.utc)
            
            self._save_states()
            
            logger.critical(
                f"Agent {agent_id} PROMOTED TO LIVE by operator {operator_id}",
                extra={
                    "operator": operator_id,
                    "asset": status.asset,
                    "timeframe": status.timeframe,
                    "paper_trades": status.paper_trades,
                    "win_rate": status.paper_win_rate,
                }
            )
        
        self._notify_transition(agent_id, old_state, status.state)
        return True
    
    def demote_to_paper(self, agent_id: str, reason: str, operator_id: Optional[str] = None):
        """Demote an agent back to paper mode.
        
        Used for:
        - Gauntlet failures
        - Live trading underperformance
        - Operator decision
        - Safety violations
        """
        with self._lock:
            status = self._statuses.get(agent_id)
            if not status:
                return
            
            old_state = status.state
            status.state = PromotionState.DEMOTED
            status.demotion_reason = reason
            status.ready_for_live = False
            
            self._save_states()
            
            logger.warning(
                f"Agent {agent_id} DEMOTED to paper: {reason}",
                extra={"operator": operator_id, "previous_state": old_state.value}
            )
        
        self._notify_transition(agent_id, old_state, status.state)
    
    def kill_agent(self, agent_id: str, reason: str, operator_id: Optional[str] = None):
        """Halt all trading for an agent.
        
        This is the nuclear option - the agent cannot trade until manually reset.
        """
        with self._lock:
            status = self._statuses.get(agent_id)
            if not status:
                return
            
            old_state = status.state
            status.state = PromotionState.KILLED
            status.demotion_reason = reason
            status.ready_for_live = False
            
            # Block all markets for this agent
            status.blocked_markets = status.blocked_markets | {"ALL"}
            
            self._save_states()
            
            logger.critical(
                f"Agent {agent_id} KILLED: {reason}",
                extra={"operator": operator_id, "previous_state": old_state.value}
            )
        
        self._notify_transition(agent_id, old_state, status.state)
    
    def block_market(self, agent_id: str, market: str, reason: str):
        """Block a specific market for an agent."""
        with self._lock:
            status = self._statuses.get(agent_id)
            if status:
                status.blocked_markets.add(market)
                self._save_states()
                logger.warning(f"Market {market} blocked for {agent_id}: {reason}")
    
    def unblock_market(self, agent_id: str, market: str, operator_id: str):
        """Unblock a market for an agent (requires operator)."""
        with self._lock:
            status = self._statuses.get(agent_id)
            if status and market in status.blocked_markets:
                status.blocked_markets.discard(market)
                self._save_states()
                logger.info(f"Market {market} unblocked for {agent_id} by {operator_id}")
    
    def _recommend_agent_kill_switch(self, agent_id: str, reason: str):
        """Recommend kill switch activation for an agent.
        
        This integrates with the global RiskController to suggest safety action.
        """
        try:
            from merid.risk.kill_switches import risk_controller, KillSwitchReason
            # Log the recommendation - operator must confirm
            logger.critical(
                f"KILL SWITCH RECOMMENDED for agent {agent_id}: {reason}",
                extra={"action_required": "Review and confirm kill switch activation"}
            )
        except ImportError:
            logger.warning(f"Cannot recommend kill switch - kill_switches module unavailable")
    
    def list_promotable_agents(self) -> List[AgentPromotionStatus]:
        """List all agents awaiting operator confirmation for live."""
        with self._lock:
            return [
                s for s in self._statuses.values()
                if s.state == PromotionState.AWAITING_CONFIRMATION
            ]
    
    def get_all_statuses(self) -> Dict[str, AgentPromotionStatus]:
        """Get all promotion statuses."""
        with self._lock:
            return dict(self._statuses)


# Singleton instance
_auto_promoter: Optional[AutoPromoter] = None
_auto_promoter_lock = threading.Lock()


def get_auto_promoter() -> AutoPromoter:
    """Get the singleton AutoPromoter instance."""
    global _auto_promoter
    if _auto_promoter is None:
        with _auto_promoter_lock:
            if _auto_promoter is None:
                _auto_promoter = AutoPromoter()
    return _auto_promoter
