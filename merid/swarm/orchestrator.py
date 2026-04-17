# merid/swarm/orchestrator.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.swarm.orchestrator")


# Kalshi 15m guardrail constants
MIN_EDGE_BPS = 10.0
MAX_F_USED = 0.35
MAX_SIZE_CONTRACTS = 100

# Symbol-specific limits (can be loaded from config)
SYMBOL_LIMITS = {
    "BTC": {"max_f_used": 0.35, "max_size_contracts": 100},
    "ETH": {"max_f_used": 0.30, "max_size_contracts": 150},
    "SOL": {"max_f_used": 0.25, "max_size_contracts": 200},
    "XRP": {"max_f_used": 0.25, "max_size_contracts": 250},
}


class SwarmOrchestrator:
    """
    Swarm orchestrator for Kalshi 15m crypto agents.
    
    Phase 1: Kalshi-specific intent validation with guardrails.
    Later, add actual coordination/overrides based on lane state.
    """

    def __init__(self, enabled: bool = False, kalshi_agents: Optional[List[str]] = None) -> None:
        self.enabled = enabled
        self.kalshi_agents = set(kalshi_agents or [])

    def register_kalshi_agents(self, agent_ids: List[str]) -> None:
        self.kalshi_agents.update(agent_ids)
        logger.info("SwarmOrchestrator: registered Kalshi agents: %s", sorted(self.kalshi_agents))

    async def review_intent(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inspect a Kalshi trade intent before execution.

        Expected intent keys for Kalshi 15m crypto:
          - venue: "kalshi"
          - lane_id: "BTC_15M" | "ETH_15M" | "SOL_15M" | "XRP_15M"
          - symbol: "BTC" | "ETH" | "SOL" | "XRP"
          - market_id: Kalshi market identifier
          - series_ticker: e.g. "KXBTC15M"
          - timeframe: "15m"
          - direction: "YES" | "NO" | "FLAT"
          - p_true: float
          - p_implied: float
          - edge_bps: float
          - kelly_fraction_full: float
          - kelly_fraction_rck: float
          - kelly_fraction_used: float
          - size_contracts: int
          - agent_id: str
        """
        agent_id = intent.get("agent_id")
        venue = intent.get("venue")
        lane_id = intent.get("lane_id")
        symbol = intent.get("symbol")

        # Validate required fields
        if not all([agent_id, venue, lane_id, symbol]):
            logger.warning("SwarmOrchestrator: missing required fields in intent: %s", intent)
            return {"approved": False, "reason": "missing_required_fields", "intent": intent}

        # Check if this is a Kalshi 15m crypto lane
        is_kalshi_15m = (
            venue == "kalshi" and
            lane_id.endswith("_15M") and
            symbol in SYMBOL_LIMITS and
            agent_id in self.kalshi_agents
        )

        if not is_kalshi_15m:
            # Not in the Kalshi 15m crypto lane; pass through.
            return {"approved": True, "reason": "not_in_kalshi_15m_lane", "intent": intent}

        if not self.enabled:
            logger.debug("SwarmOrchestrator (disabled) saw Kalshi 15m intent: %s", intent)
            return {"approved": True, "reason": "swarm_disabled", "intent": intent}

        # Extract key fields with defaults
        edge_bps = float(intent.get("edge_bps", 0.0) or 0.0)
        f_used = float(intent.get("kelly_fraction_used", 0.0) or 0.0)
        size_contracts = int(intent.get("size_contracts", 0) or 0)

        # Get symbol-specific limits
        symbol_limits = SYMBOL_LIMITS.get(symbol, {"max_f_used": MAX_F_USED, "max_size_contracts": MAX_SIZE_CONTRACTS})
        max_f_used = symbol_limits["max_f_used"]
        max_size_contracts = symbol_limits["max_size_contracts"]

        # Apply guardrails
        if edge_bps < MIN_EDGE_BPS:
            logger.info(
                "SwarmOrchestrator: rejecting intent - edge too small (%.1f < %.1f bps) for %s from %s",
                edge_bps, MIN_EDGE_BPS, lane_id, agent_id
            )
            return {
                "approved": False, 
                "reason": "edge_too_small", 
                "details": f"edge_bps={edge_bps:.1f}, min_edge_bps={MIN_EDGE_BPS}",
                "intent": intent
            }

        if f_used > max_f_used:
            logger.info(
                "SwarmOrchestrator: rejecting intent - Kelly fraction exceeds cap (%.3f > %.3f) for %s from %s",
                f_used, max_f_used, lane_id, agent_id
            )
            return {
                "approved": False, 
                "reason": "kelly_fraction_exceeds_cap", 
                "details": f"kelly_fraction_used={f_used:.3f}, max_f_used={max_f_used:.3f}",
                "intent": intent
            }

        if size_contracts > max_size_contracts:
            logger.info(
                "SwarmOrchestrator: rejecting intent - position limit exceeded (%d > %d) for %s from %s",
                size_contracts, max_size_contracts, lane_id, agent_id
            )
            return {
                "approved": False, 
                "reason": "position_limit_exceeded", 
                "details": f"size_contracts={size_contracts}, max_size_contracts={max_size_contracts}",
                "intent": intent
            }

        # Intent passes all guardrails
        logger.info(
            "SwarmOrchestrator: approved Kalshi 15m intent from %s | %s %s @ %.1f bps edge, %.3f Kelly, %d contracts",
            agent_id, symbol, intent.get("direction", "UNKNOWN"), edge_bps, f_used, size_contracts
        )
        return {
            "approved": True,
            "reason": "guardrails_passed",
            "details": f"edge_bps={edge_bps:.1f}, kelly_fraction_used={f_used:.3f}, size_contracts={size_contracts}",
            "intent": intent,
        }

    async def review_portfolio_risk(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate a portfolio risk snapshot (not a trade intent).

        Called by PortfolioRiskAgent to get a swarm-level risk advisory.
        Returns {approved, risk_score, message}.
        """
        total_notional = float(snapshot.get("total_notional", 0))
        daily_pnl = float(snapshot.get("daily_pnl", 0))
        drawdown_pct = float(snapshot.get("drawdown_pct", 0))
        margin_util = float(snapshot.get("margin_util", 0))
        breaches = snapshot.get("breaches", [])

        risk_score = 0.0
        reasons: List[str] = []

        if drawdown_pct > 8.0:
            risk_score += 0.4
            reasons.append(f"drawdown {drawdown_pct:.1f}%")
        if margin_util > 70.0:
            risk_score += 0.3
            reasons.append(f"margin_util {margin_util:.1f}%")
        if daily_pnl < -500:
            risk_score += 0.2
            reasons.append(f"daily_pnl ${daily_pnl:.0f}")
        if breaches:
            risk_score += 0.1 * len(breaches)
            reasons.append(f"{len(breaches)} breaches")

        approved = risk_score < 0.8
        msg = "; ".join(reasons) if reasons else "portfolio healthy"

        if not approved:
            logger.warning("SwarmOrchestrator: portfolio risk FLAGGED (score=%.2f): %s", risk_score, msg)
        else:
            logger.debug("SwarmOrchestrator: portfolio risk OK (score=%.2f)", risk_score)

        return {
            "approved": approved,
            "risk_score": round(min(risk_score, 1.0), 3),
            "message": msg,
        }

    async def propose_overrides(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Propose per-lane overrides based on lane state.

        Expected state keys:
          - lanes: { lane_id: { symbol, recent_dd, recent_win_rate, recent_edge_bps, cooldown_until, ... } }
        """
        if not self.enabled:
            logger.debug("SwarmOrchestrator.propose_overrides (disabled) called.")
            return {"overrides": {}, "reason": "swarm_disabled"}

        lanes = state.get("lanes", {})
        overrides = {}
        
        for lane_id, lane_state in lanes.items():
            symbol = lane_state.get("symbol")
            recent_dd = lane_state.get("recent_dd", 0.0)
            recent_win_rate = lane_state.get("recent_win_rate", 0.5)
            cooldown_until = lane_state.get("cooldown_until", 0.0)
            
            # Check for drawdown breach
            target_dd = 0.10 if symbol == "BTC" else 0.08 if symbol == "ETH" else 0.05
            if recent_dd > target_dd:
                overrides[lane_id] = {
                    "suspend_trading": True,
                    "reason": f"drawdown_breach: {recent_dd:.2%} > {target_dd:.2%}"
                }
                logger.warning("SwarmOrchestrator: proposing trading suspension for %s due to drawdown breach", lane_id)
                continue
            
            # Check for cooldown period
            import time
            if cooldown_until > time.time():
                overrides[lane_id] = {
                    "suspend_trading": True,
                    "reason": f"cooldown_active: until {cooldown_until}"
                }
                logger.info("SwarmOrchestrator: proposing trading suspension for %s due to cooldown", lane_id)
                continue
            
            # Check for low win rate
            if recent_win_rate < 0.3:  # Less than 30% win rate
                overrides[lane_id] = {
                    "reduce_size": 0.5,  # Reduce position size by 50%
                    "reason": f"low_win_rate: {recent_win_rate:.2%}"
                }
                logger.info("SwarmOrchestrator: proposing size reduction for %s due to low win rate", lane_id)
        
        if overrides:
            logger.info("SwarmOrchestrator: proposing %d lane overrides", len(overrides))
        else:
            logger.debug("SwarmOrchestrator: no overrides proposed")
        
        return {
            "overrides": overrides,
            "reason": "lane_state_analysis",
            "analyzed_lanes": len(lanes),
            "override_count": len(overrides)
        }


_global_orchestrator: Optional[SwarmOrchestrator] = None


def get_swarm_orchestrator() -> SwarmOrchestrator:
    global _global_orchestrator
    if _global_orchestrator is None:
        _global_orchestrator = SwarmOrchestrator()
    return _global_orchestrator
