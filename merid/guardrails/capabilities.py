"""
§2 — Per-Agent Capability Maps & Scope Isolation

Each agent has a static capability set:
- Which tools it can call
- Which symbols/venues it can access
- Max notional per trade
- Which config keys it can read/write
- Which scope it operates in (research / paper / live)

Enforcement happens at the tool router, not in prompts.
Agents in one scope cannot see credentials or configs from a higher-privilege scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger
import threading

logger = get_logger("merid.guardrails.capabilities")


# ── Config-Based Max Notional Computation ─────────────────────────────────────

def _compute_kalshi_max_notional_from_config() -> float:
    """Compute max_notional from sizing policy configuration, not live balance.
    
    CRITICAL: max_notional must be derived from config sizing policy, not from
    live account balance. This ensures behavior is identical regardless of
    whether the account has $100 or $100,000.
    
    Policy:
    - max_notional = PER_TRADE_MAX_NOTIONAL_USD × MAX_CONCURRENT_TRADES
    - For Kalshi PM: uses canonical envelope for kalshi_crypto_15m_v2 profile
    - Live balance is used only for guardrail checks, not for defining the cap
    - If max_notional > available_cash_usd, log warning but keep config cap
    
    Returns:
        float: max_notional in USD
    """
    # Use canonical risk envelope for kalshi_crypto_15m_v2 profile
    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
    envelope = get_kalshi_crypto_15m_risk_envelope()
    
    per_trade_max_notional = envelope.max_single_order_notional_usd
    max_concurrent_trades = envelope.max_concurrent_trades
    max_notional = per_trade_max_notional * max_concurrent_trades
    
    # P1-5: Cross-check assert to ensure envelope computation is correct
    expected_max_notional = per_trade_max_notional * max_concurrent_trades
    if abs(max_notional - expected_max_notional) > 0.01:  # 1 cent tolerance
        logger.error(
            f"[KALSHI_CAPABILITY] CRITICAL: Computed max_notional ${max_notional:.2f} "
            f"does not match expected ${expected_max_notional:.2f} "
            f"(per_trade=${per_trade_max_notional:.2f} × concurrent={max_concurrent_trades})"
        )
        raise AssertionError(f"Capability max_notional mismatch: computed ${max_notional:.2f} vs expected ${expected_max_notional:.2f}")
    
    logger.info(
        "[KALSHI_CAPABILITY] Derived max_notional from canonical envelope: $%.2f "
        "(per_trade_cap=$%.2f × max_concurrent=%d)",
        max_notional,
        per_trade_max_notional,
        max_concurrent_trades
    )
    
    # Optional guardrail: check if config cap exceeds available cash
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        available_cash_usd = get_equity_for_risk_calc_sync()
        if max_notional > available_cash_usd:
            logger.warning(
                f"[KALSHI_CAPABILITY] Config cap ${max_notional:.2f} exceeds available cash ${available_cash_usd:.2f} - "
                f"using config cap anyway (policy: config sizing, not balance-based)"
            )
    except ImportError:
        pass
    
    return max_notional


@dataclass
class AgentCapabilityMap:
    """
    Static capability declaration for one agent.

    The GuardedToolRouter checks this before every tool call.
    """
    agent_id: str
    # Tools this agent is allowed to invoke
    allowed_tools: Set[str] = field(default_factory=set)
    # Venues this agent can interact with
    allowed_venues: Set[str] = field(default_factory=lambda: {"*"})
    # Maximum notional per single trade (USD)
    # CRITICAL: max_notional_usd should be derived from live bankroll, not hardcoded
    # Default 0 means "derive from live bankroll" for agent capabilities
    max_notional_usd: float = 0.0  # 0 = derive from live bankroll (was 10_000.0 hardcoded)
    # Maximum orders per minute
    max_orders_per_minute: int = 10
    # Config keys this agent can read
    readable_config_keys: Set[str] = field(default_factory=set)
    # Config keys this agent can write (very restricted)
    writable_config_keys: Set[str] = field(default_factory=set)
    # Scope ceiling — agent cannot operate above this level
    max_scope: str = "paper"  # "research" < "paper" < "live"

    _SCOPE_ORDER = {"research": 0, "paper": 1, "live": 2}

    def can_use_tool(self, tool_name: str) -> bool:
        return "*" in self.allowed_tools or tool_name in self.allowed_tools

    def can_access_symbol(self, symbol: str) -> bool:
        return "*" in self.allowed_symbols or symbol in self.allowed_symbols

    def can_access_venue(self, venue: str) -> bool:
        return "*" in self.allowed_venues or venue in self.allowed_venues

    def can_operate_in_scope(self, scope: str) -> bool:
        return self._SCOPE_ORDER.get(scope, 0) <= self._SCOPE_ORDER.get(self.max_scope, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "allowed_tools": sorted(self.allowed_tools),
            "allowed_symbols": sorted(self.allowed_symbols),
            "allowed_venues": sorted(self.allowed_venues),
            "max_notional_usd": self.max_notional_usd,
            "max_orders_per_minute": self.max_orders_per_minute,
            "max_scope": self.max_scope,
        }


# ── Default capability profiles ──────────────────────────────────────

def _research_profile(agent_id: str) -> AgentCapabilityMap:
    """Read-only research agent — can observe markets but never trade."""
    return AgentCapabilityMap(
        agent_id=agent_id,
        allowed_tools={
            "get_order_book", "get_ticker", "get_price_history",
            "get_news_feed", "get_sentiment", "get_position_state",
            "get_portfolio_summary", "get_config_flag",
        },
        max_notional_usd=0.0,
        max_orders_per_minute=0,
        max_scope="research",
    )


def _trading_profile(agent_id: str) -> AgentCapabilityMap:
    """Paper/live trading agent — can observe and place orders within limits."""
    return AgentCapabilityMap(
        agent_id=agent_id,
        allowed_tools={
            "get_order_book", "get_ticker", "get_price_history",
            "get_position_state", "get_portfolio_summary",
            "place_order", "cancel_order", "get_open_orders",
            "get_config_flag",
        },
        max_notional_usd=10_000.0,
        max_orders_per_minute=10,
        max_scope="paper",
    )


def _risk_profile(agent_id: str) -> AgentCapabilityMap:
    """Risk agent — can observe everything and trigger halts but not trade."""
    return AgentCapabilityMap(
        agent_id=agent_id,
        allowed_tools={
            "get_order_book", "get_ticker", "get_position_state",
            "get_portfolio_summary", "get_risk_metrics",
            "get_config_flag", "trigger_halt", "get_open_orders",
        },
        max_notional_usd=0.0,
        max_orders_per_minute=0,
        readable_config_keys={"*"},
        max_scope="live",
    )


def _kalshi_pm_profile(agent_id: str) -> AgentCapabilityMap:
    """Live-capable Kalshi prediction-market agents (AgentGrid crypto lanes).
    
    CRITICAL: max_notional_usd is derived from config sizing policy, NOT live balance.
    Uses KalshiRiskConfig.max_single_order_notional_usd × max_concurrent_trades (3).
    Behavior is identical regardless of account balance ($100 or $100,000).
    
    P2-7: Scope is set to "live" by default, but downgraded to "paper" if paper session is active.
    """
    # Derive max_notional from config sizing policy
    max_notional = _compute_kalshi_max_notional_from_config()
    
    # P2-7: Check if paper session is active and downgrade scope to "paper"
    # Bypass paper session gating when in live mode
    import os
    scope = "live"
    trading_mode = os.getenv("MERID_TRADING_MODE", "").lower()
    if trading_mode != "live":
        try:
            from merid.prediction.paper_session import get_paper_session
            ps = get_paper_session()
            if ps and ps._session_id:
                scope = "paper"
                logger.info(
                    f"[KALSHI_CAPABILITY] Paper session active ({ps._session_id}), "
                    f"downgrading {agent_id} scope to 'paper'"
                )
        except Exception as e:
            logger.debug(f"[KALSHI_CAPABILITY] Paper session check failed: {e}")
    else:
        logger.info(
            f"[KALSHI_CAPABILITY] MERID_TRADING_MODE=live - bypassing paper session gating, "
            f"{agent_id} scope set to 'live'"
        )
    
    return AgentCapabilityMap(
        agent_id=agent_id,
        allowed_tools={
            "get_order_book",
            "get_ticker",
            "get_price_history",
            "get_position_state",
            "get_portfolio_summary",
            "place_order",
            "cancel_order",
            "get_open_orders",
            "get_config_flag",
            "kalshi_place_order",
            "kalshi_list_markets",
            "kalshi_get_market_state",
            "kalshi_cancel_order",
            "kalshi_get_positions",
            "kalshi_get_balance",
        },
        max_notional_usd=max_notional,
        max_orders_per_minute=30,
        max_scope=scope,
    )


def _governance_profile(agent_id: str) -> AgentCapabilityMap:
    """Governance agent — can read configs and approve/deny proposals."""
    return AgentCapabilityMap(
        agent_id=agent_id,
        allowed_tools={
            "get_config_flag", "get_portfolio_summary",
            "get_risk_metrics", "approve_proposal", "deny_proposal",
        },
        max_notional_usd=0.0,
        max_orders_per_minute=0,
        readable_config_keys={"*"},
        writable_config_keys=set(),
        max_scope="live",
    )


PROFILE_FACTORIES = {
    "research": _research_profile,
    "trading": _trading_profile,
    "risk": _risk_profile,
    "governance": _governance_profile,
    "kalshi_pm": _kalshi_pm_profile,
}


# ── Capability Store ─────────────────────────────────────────────────

class CapabilityStore:
    """
    Central store of per-agent capability maps.

    Agents are registered at startup; the GuardedToolRouter queries this
    store before every tool invocation.
    """

    def __init__(self) -> None:
        self._maps: Dict[str, AgentCapabilityMap] = {}

    def register(self, cap_map: AgentCapabilityMap) -> None:
        self._maps[cap_map.agent_id] = cap_map
        # CRITICAL: Log exact max_notional without rounding to match canonical envelope
        logger.info(
            "Capability map registered: %s (tools=%d, max_scope=%s, max_notional=$%.2f)",
            cap_map.agent_id, len(cap_map.allowed_tools), cap_map.max_scope, cap_map.max_notional_usd,
        )

    def register_from_profile(self, agent_id: str, profile: str) -> AgentCapabilityMap:
        """Register using a named profile (research, trading, risk, governance)."""
        factory = PROFILE_FACTORIES.get(profile, _research_profile)
        cap_map = factory(agent_id)
        self.register(cap_map)
        return cap_map

    def get(self, agent_id: str) -> Optional[AgentCapabilityMap]:
        return self._maps.get(agent_id)

    def get_or_default(self, agent_id: str) -> AgentCapabilityMap:
        """Return capability map, defaulting to research (most restrictive)."""
        return self._maps.get(agent_id, _research_profile(agent_id))

    def list_agents(self) -> List[str]:
        return list(self._maps.keys())

    def get_stats(self) -> Dict[str, Any]:
        by_scope: Dict[str, int] = {}
        for m in self._maps.values():
            by_scope[m.max_scope] = by_scope.get(m.max_scope, 0) + 1
        return {
            "total_agents": len(self._maps),
            "by_max_scope": by_scope,
        }


# ── Singleton ────────────────────────────────────────────────────────

_capability_store: Optional[CapabilityStore] = None
_capability_store_lock = threading.Lock()


def get_capability_store() -> CapabilityStore:
    global _capability_store
    if _capability_store is None:
        with _capability_store_lock:
            if _capability_store is None:
                _capability_store = CapabilityStore()
    return _capability_store
