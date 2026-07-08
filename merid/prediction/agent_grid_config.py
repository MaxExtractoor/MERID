"""Kalshi Agent Grid — YAML config loader and typed data models.

DEPRECATED: This config loader is for legacy compatibility only.
The production 15m Kalshi crypto system uses config/profiles/kalshi_crypto_15m_v2.yaml
via the profile resolver (merid/profile_resolver.py).

Loads config/kalshi_agent_grid.yaml and exposes strongly-typed dataclasses
that the orchestrator, trading agents, and portfolio risk agent consume.
"""

from __future__ import annotations

import threading
import os
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

import yaml

from utils.logger import get_logger

logger = get_logger("merid.prediction.agent_grid_config")

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "kalshi_agent_grid.yaml"
)


def _validate_profile_usage(raw_config: Dict[str, Any], config_path: str) -> None:
    """Validate profile usage for 15m crypto agents.
    
    Checks if the kalshi_crypto_15m profile should be active when 15m crypto agents
    are present in the agent grid. Logs warnings if profile is not active but
    should be.
    
    Args:
        raw_config: Parsed YAML config dictionary
        config_path: Path to config file (for logging)
    """
    try:
        from merid.risk.profiles.crypto_15m_profile import is_profile_active
    except ImportError:
        # Profile module not available, skip validation
        return
    
    # Check if 15m crypto agents are present
    raw_agents = raw_config.get("agents", [])
    crypto_15m_agents = []
    for agent in raw_agents:
        name = agent.get("name", "").upper()
        assets = agent.get("assets", [])
        timeframes = agent.get("timeframes", [])
        
        # Check if this is a 15m crypto agent
        if ("BTC" in name or "ETH" in name or "SOL" in name or "XRP" in name or "DOGE" in name):
            if "15M" in name or "15m" in name or ("15m" in timeframes):
                crypto_15m_agents.append(name)
    
    if not crypto_15m_agents:
        return
    
    # Check if profile is active
    if is_profile_active():
        logger.info(
            f"[PROFILE-VALIDATION] Profile kalshi_crypto_15m_v2 is active. "
            f"15m crypto agents will use profile-based risk limits: {crypto_15m_agents}"
        )
    # Removed warning - bankroll-derived risk limits are acceptable for live trading


def apply_profile_to_agent(
    base_config: AgentConfig,
    profile: Any,
    live_bankroll_usd: Optional[float],
) -> AgentConfig:
    """
    Pure function to apply profile overrides to an agent configuration.
    
    This is the single source of truth for profile application, used by both
    the base agent grid and the 15m agent grid to ensure consistency.
    
    Args:
        base_config: Base agent configuration from YAML
        profile: Trading profile object (e.g., Crypto15mProfile)
        live_bankroll_usd: Current live bankroll in USD (None if not available)
        
    Returns:
        AgentConfig with profile overrides applied
    """
    # 1. Determine capital source
    effective_capital = live_bankroll_usd if live_bankroll_usd is not None else getattr(profile, 'capital_usd', 0)
    
    # 2. Handle zero capital case
    if effective_capital is None or effective_capital <= 0:
        # Use conservative default from profile or fallback
        min_capital = getattr(profile, 'min_capital_usd', 1000.0)
        effective_capital = min_capital
        logger.warning(
            "[PROFILE-ADAPTER] Zero or negative capital (%.2f), using min_capital=%.2f",
            live_bankroll_usd or 0, min_capital
        )
    
    # 3. Compute per-trade risk percent (unified across assets)
    risk_pct = getattr(profile, 'per_trade_risk_pct', 0.03)  # CRITICAL FIX: Default 3% to match profile YAML (was 0.02)
    
    # 4. Compute max_notional
    max_notional_usd = effective_capital * risk_pct
    
    # 5. Apply overrides to risk limits
    updated_risk_limits = replace(
        base_config.risk_limits,
        max_notional_usd=Decimal(str(max_notional_usd))
    )
    
    # 6. Apply signal_mode from profile if available
    updated_strategy_overrides = base_config.strategy_overrides.copy()
    if hasattr(profile, 'signal_mode'):
        updated_strategy_overrides['signal_mode'] = profile.signal_mode
        logger.info(
            "[PROFILE-ADAPTER] Applied signal_mode=%s to agent %s from profile",
            profile.signal_mode, base_config.name
        )
    
    # 7. Return updated config
    updated_config = replace(
        base_config,
        risk_limits=updated_risk_limits,
        strategy_overrides=updated_strategy_overrides
    )
    
    # 8. Log for debugging
    logger.info(
        "[PROFILE-ADAPTER] Applied profile to agent %s: bankroll=%.2f risk_pct=%.2f%% max_notional=%.2f signal_mode=%s",
        base_config.name, effective_capital, risk_pct * 100, max_notional_usd,
        updated_strategy_overrides.get('signal_mode', 'not_set')
    )
    
    return updated_config


# ── Typed config models ────────────────────────────────────────────────

@dataclass
class VenueConfig:
    """Top-level venue settings.
    
    NOTE: base_url is read from KALSHI_API_BASE_URL env var via invariants module.
    Do not construct URLs manually; always use get_kalshi_base_url() from invariants.
    """
    name: str = "kalshi"
    use_demo: bool = False
    # DEPRECATED for kalshi_crypto_15m_v2 profile: Use config/profiles/kalshi_crypto_15m.yaml instead
    # This setting is still used by other profiles (sports, paper, generic prediction)
    max_notional_per_expiry_usd: Decimal = Decimal("0")  # 0 = derive from bankroll (was $5000)
    max_open_markets_per_asset: int = 20

    @property
    def base_url(self) -> str:
        """Get Kalshi API base URL from invariants (single source of truth)."""
        from merid.event_venues.kalshi.invariants import get_kalshi_base_url
        return get_kalshi_base_url()

    @property
    def ws_url(self) -> str:
        """Get Kalshi WebSocket URL from invariants (single source of truth)."""
        from merid.event_venues.kalshi.invariants import get_kalshi_ws_url
        return get_kalshi_ws_url()


@dataclass
class SessionConfig:
    """Kalshi session / maintenance window."""
    maintenance_day: int = 3          # 0=Mon … 6=Sun → 3=Thu
    maintenance_start_et: str = "03:00"
    maintenance_end_et: str = "05:00"


def get_session_config() -> SessionConfig:
    """Get the SessionConfig from the loaded agent grid configuration.
    
    Returns:
        SessionConfig with maintenance window settings
        
    Raises:
        RuntimeError: If agent grid config is not loaded
    """
    config = get_agent_grid_config()
    return config.session


@dataclass
class MarketFilterConfig:
    """Filter used to resolve Kalshi tickers for an agent."""
    category: str = "crypto"
    frequency: Optional[str] = None   # fifteen_min, hourly, daily, weekly, monthly, annual
    tags: List[str] = field(default_factory=list)


@dataclass
class PriceBand:
    """Price band for price-aware contract limits."""
    price_range_min: int  # Minimum price in cents
    price_range_max: int  # Maximum price in cents
    max_contracts: int   # Maximum contracts allowed in this price band


@dataclass
class AgentRiskLimits:
    """Per-agent risk limits.
    
    NOTE: Price-aware sizing via price_bands replaces blunt max_yes_position/max_no_position.
    When price_bands is non-empty, max_yes_position and max_no_position are ignored.
    
    DEPRECATED for kalshi_crypto_15m_v2 profile: Use config/profiles/kalshi_crypto_15m.yaml instead
    These settings are still used by other profiles (sports, paper, generic prediction)
    """
    max_yes_position: int = 0  # 0 = derive from bankroll % (was 500)
    max_no_position: int = 0   # 0 = derive from bankroll % (was 500)
    max_orders_per_window: int = 0  # 0 = auto-compute from bankroll
    max_notional_usd: Decimal = Decimal("0")  # 0 = derive from bankroll (was $500)
    # CRITICAL FIX: 0 = derive from bankroll (was 50 - dangerous for micro bankrolls)
    max_contracts_per_order: int = 0  # 0 = derive: min(25, 1% of bankroll / price)
    # Price-aware sizing: replace blunt caps with graduated limits by contract price
    price_bands: List[PriceBand] = field(default_factory=list)

    def get_effective_max_orders(self, bankroll_cents: int, top_n_edges: int = 3) -> int:
        """Compute dynamic max_orders based on bankroll and available edges.

        Formula: min(floor(bankroll_usd / 100), 3, top_n_edges_count)
        REVERTED (2026-05-08): default top_n_edges=3 (was 1) to restore profitable trades.

        This ensures:
        - Small bankroll ($14) → 1 order (top edge only)
        - Medium bankroll ($100-300) → 1-3 orders
        - Large bankroll ($300+) → 3 orders max (capped by Top3 selector)
        - Never exceeds available edges with sufficient signal
        """
        # If explicitly set (non-zero), use that value
        if self.max_orders_per_window > 0:
            return self.max_orders_per_window

        # Compute from bankroll: 1 order per $100 of bankroll
        bankroll_usd = bankroll_cents / 100.0
        bankroll_derived = max(1, int(bankroll_usd // 100))

        # Cap at 3 (Top3 selector limit) and available edges
        effective = min(bankroll_derived, 3, top_n_edges)

        return effective

    def get_max_contracts_for_price(self, price_cents: int) -> int:
        """Get maximum contracts allowed for a given contract price using price bands.

        Args:
            price_cents: Contract price in cents

        Returns:
            Maximum contracts allowed, or 0 if no price bands configured (use legacy max_yes_position)
        """
        if not self.price_bands:
            # No price bands configured, use legacy blunt caps
            return max(self.max_yes_position, self.max_no_position)

        # Find matching price band
        for band in self.price_bands:
            if band.price_range_min <= price_cents <= band.price_range_max:
                return band.max_contracts

        # No matching band found, use conservative default of 1
        logger.warning(
            f"No price band found for price {price_cents}¢, using conservative default of 1 contract"
        )
        return 1


@dataclass
class EntryWindowConfig:
    """When the agent is allowed to enter relative to contract expiry.

    LEGACY DEFAULTS - For non-crypto, non-15m agents only.

    For Kalshi 15m crypto agents (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M):
      - Entry window values: Use config/profiles/kalshi_crypto_15m.yaml (SINGLE SOURCE OF TRUTH)
      - Profile values are applied via profile overrides in agent_grid_config.py
      - These hardcoded defaults are NOT used by 15m crypto agents

    PRODUCTION FIX v8 (2026-04-30): Increased defaults from 10/2 to 60/5 minutes.
    Previous narrow window (10/2) caused ENTRY-WINDOW-SUSPECT warnings for macro/tech agents.
    60/5 provides reasonable entry windows for all timeframes from 15m to daily.

    AUDIT-12 FIX (2026-05-11): Tightened 15m entry window via env var support.
    Use MERID_PM_ENTRY_WINDOW_15M_MINUTES and MERID_PM_ENTRY_WINDOW_15M_CUTOFF
    to configure tighter windows for choppy crypto 15m markets.
    """
    minutes_before_expiry: int = 60  # Was 10 - too narrow for macro/tech agents
    cutoff_minutes_before_expiry: int = 5  # Was 2 - too tight for higher timeframe agents
    
    @classmethod
    def for_timeframe(cls, timeframe: str) -> "EntryWindowConfig":
        """Get entry window config with timeframe-specific overrides from env vars.
        
        Args:
            timeframe: Timeframe (e.g., "15m", "1h", "daily")
            
        Returns:
            EntryWindowConfig with timeframe-specific overrides applied
        """
        import os
        
        # Default config
        config = cls()
        
        # Apply timeframe-specific overrides from env vars
        if timeframe == "15m":
            # AUDIT-12: Tighter window for 15m crypto markets (choppy, fast-moving)
            minutes = os.getenv("MERID_PM_ENTRY_WINDOW_15M_MINUTES")
            cutoff = os.getenv("MERID_PM_ENTRY_WINDOW_15M_CUTOFF")
            if minutes:
                config.minutes_before_expiry = int(minutes)
            if cutoff:
                config.cutoff_minutes_before_expiry = int(cutoff)
        
        return config


@dataclass
class AgentConfig:
    """Configuration for a single Kalshi trading agent."""
    name: str
    category: str = "crypto"  # crypto, economics, financials, etc.
    # Market category filtering - controls which markets this agent should process.
    # "crypto" = only crypto markets (KXBTC, KXETH, KXSOL, KXXRP, KXDOGE)
    # "macro" = only macro markets (KXFED, KXFEDDECISION, etc.)
    # "both" = both crypto and macro markets (not recommended - use separate agents)
    market_category: str = "crypto"
    assets: List[str] = field(default_factory=list)
    timeframes: List[str] = field(default_factory=list)
    market_filter: MarketFilterConfig = field(default_factory=MarketFilterConfig)
    risk_limits: AgentRiskLimits = field(default_factory=AgentRiskLimits)
    entry_window: EntryWindowConfig = field(default_factory=EntryWindowConfig)
    enabled: bool = True
    archetype: str = "directional"  # directional, market_maker, arbitrage
    # Risk profile for this agent - used by KalshiRiskEngine for per-agent risk configuration
    risk_profile: str = "default"  # default, conservative, aggressive
    # When True with ``archetype: market_maker``, KalshiTradingAgent hard-blocks QUOTE
    # if PM spot is missing/stale (``MERID_CRYPTO_MM_PM_SPOT_HARD_GATE`` can still disable globally).
    # Set explicitly on each MM agent — default False so new agents opt in consciously.
    pm_spot_hard_gate: bool = False
    use_filter_pipeline: bool = False
    filter_max_candidates_per_asset: int = 10
    filter_max_candidates_global: int = 20
    # Optional overrides for ``merid.prediction.strategy.StrategyConfig`` (see YAML ``strategy:``)
    strategy_overrides: Dict[str, Any] = field(default_factory=dict)
    # When True, skip swarm consensus direction / solo timer (strategy + risk still apply).
    # Also see env ``MERID_PM_BYPASS_SWARM_CONSENSUS_AGENTS=name1,name2``.
    bypass_swarm_consensus: bool = False
    # When True, agent is signal-only (provides context/consensus but never executes trades).
    # Used by SPORTS_DIRECTIONAL and other context agents.
    signalonly: bool = False
    # Take-profit configuration — None means use the preset from get_tp_config_for_agent().
    # Populated from YAML ``take_profit:`` block if present.
    take_profit: Optional[Any] = None  # TakeProfitConfig (typed in take_profit.py)
    # Strike selection configuration — None means use global defaults.
    # Populated from YAML ``strike_selection:`` block if present.
    strike_selection: Optional[Any] = None  # StrikeSelectionConfig (typed in kalshi_strike_selector.py)
    # Kalshi series tickers this agent subscribes to (e.g., ["KXBTC15M", "KXBTC"]).
    # Auto-resolved from AGENT_SERIES_MAP if not explicitly set in YAML.
    series_tickers: List[str] = field(default_factory=list)

    @property
    def agent_id(self) -> str:
        return f"kalshi-{self.name.lower()}"


@dataclass
class PortfolioRiskConfig:
    """Portfolio-level risk limits across all agents.
    
    NOTE: These defaults now pull from merid.settings rather than hardcoded values.
    Set KALSHI_PORTFOLIO_BANKROLL_CENTS and percentage env vars to configure.
    """
    # These are now computed from settings in __post_init__ if not explicitly provided
    max_total_notional_usd: Decimal = Decimal("0")  # 0 = derive from settings
    max_notional_per_asset_usd: Decimal = Decimal("0")  # 0 = derive from settings
    max_open_markets: int = 50
    max_daily_loss_usd: Decimal = Decimal("0")  # 0 = derive from settings
    max_margin_utilization_pct: Decimal = Decimal("0")  # 0 = derive from settings
    rebalance_check_interval_seconds: int = 0  # 0 = derive from settings

    def __post_init__(self):
        """Derive any zero values from core.settings (SINGLE SOURCE OF TRUTH - bankroll-driven limits)."""
        from core.settings import (
            MAX_TOTAL_RISK_PCT, 
            DAILY_LOSS_CAP_PCT, 
            MAX_CYCLE_RISK_PCT
        )
        from merid.settings import settings
        
        # Use live bankroll from bankroll_service_v2 (single source of truth)
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            bankroll_usd = get_equity_for_risk_calc_sync()
            if bankroll_usd is None or bankroll_usd <= 0:
                # Fail closed - no bankroll available
                bankroll_cents = 0
            else:
                bankroll_cents = int(bankroll_usd * 100)
        except Exception as e:
            # CRITICAL FIX: Log error before failing closed
            logger.error(
                "[AGENT-GRID-CONFIG] Failed to load bankroll from bankroll_service_v2: %s - failing closed",
                e
            )
            bankroll_cents = 0
        
        # Use unified core.settings values instead of deprecated merid.settings
        if self.max_total_notional_usd == 0:
            self.max_total_notional_usd = Decimal(bankroll_cents * MAX_TOTAL_RISK_PCT) / 100
        if self.max_daily_loss_usd == 0:
            self.max_daily_loss_usd = Decimal(bankroll_cents * DAILY_LOSS_CAP_PCT) / 100
        if self.max_notional_per_asset_usd == 0:
            self.max_notional_per_asset_usd = Decimal(bankroll_cents * MAX_CYCLE_RISK_PCT) / 100
        if self.max_margin_utilization_pct == 0:
            self.max_margin_utilization_pct = Decimal("75")  # 75% default
        if self.rebalance_check_interval_seconds == 0:
            self.rebalance_check_interval_seconds = 30  # 30s default


@dataclass
class AgentGridConfig:
    """Complete agent grid configuration."""
    venue: VenueConfig
    session: SessionConfig
    agents: List[AgentConfig]
    portfolio_risk: PortfolioRiskConfig

    def get_agent(self, name: str) -> Optional[AgentConfig]:
        """Look up an agent by name (case-insensitive)."""
        name_lower = name.lower()
        for a in self.agents:
            if a.name.lower() == name_lower:
                return a
        return None

    def agents_for_asset(self, asset: str) -> List[AgentConfig]:
        """Return all agents that trade a given asset."""
        asset_upper = asset.upper()
        return [a for a in self.agents if asset_upper in a.assets]

    @property
    def all_assets(self) -> List[str]:
        """Unique list of assets across all agents."""
        seen: set = set()
        result: List[str] = []
        for a in self.agents:
            for asset in a.assets:
                if asset not in seen:
                    seen.add(asset)
                    result.append(asset)
        return result

    def summary(self) -> Dict[str, Any]:
        return {
            "venue": self.venue.name,
            "use_demo": self.venue.use_demo,
            "agent_count": len(self.agents),
            "agents": [a.name for a in self.agents],
            "assets": self.all_assets,
            "portfolio_max_notional": str(self.portfolio_risk.max_total_notional_usd),
        }


# ── YAML loader ────────────────────────────────────────────────────────

def _parse_market_filter(raw: Dict[str, Any]) -> MarketFilterConfig:
    return MarketFilterConfig(
        category=raw.get("category", "crypto"),
        frequency=raw.get("frequency"),
        tags=raw.get("tags", []),
    )


def _parse_risk_limits(raw: Dict[str, Any]) -> AgentRiskLimits:
    # Parse price_bands if present
    price_bands_raw = raw.get("price_bands", [])
    price_bands = []
    for band_raw in price_bands_raw:
        price_range = band_raw.get("price_range", [0, 99])
        if isinstance(price_range, list) and len(price_range) == 2:
            price_bands.append(PriceBand(
                price_range_min=int(price_range[0]),
                price_range_max=int(price_range[1]),
                max_contracts=int(band_raw.get("max_contracts", 1))
            ))
    
    return AgentRiskLimits(
        max_yes_position=raw.get("max_yes_position", 0),  # 0 = derive from bankroll
        max_no_position=raw.get("max_no_position", 0),   # 0 = derive from bankroll
        max_orders_per_window=raw.get("max_orders_per_window", 0),  # 0 = auto-compute
        max_notional_usd=Decimal(str(raw.get("max_notional_usd", 0))),  # 0 = derive from bankroll
        max_contracts_per_order=raw.get("max_contracts_per_order", 1),  # CRITICAL FIX (2026-07-08): Default 1 to enforce 3% risk limit
        price_bands=price_bands,
    )


# 15m scalper: configurable cutoff (OPTIMIZED 2026-05-10: was 2 min, now 3 min)
_MIN_CUTOFF_MINUTES = int(os.getenv("SCALPER15M_MIN_CUTOFF_MINUTES", "3"))  # 3 min default for 15m


def _parse_strategy_overrides(block: Any) -> Dict[str, Any]:
    """Map YAML ``strategy:`` into typed values for ``StrategyConfig`` fields."""
    if not isinstance(block, dict):
        return {}
    from dataclasses import fields
    from decimal import Decimal
    import typing as _t

    from merid.prediction.strategy import StrategyConfig

    hints = _t.get_type_hints(StrategyConfig)
    out: Dict[str, Any] = {}
    allowed = {f.name for f in fields(StrategyConfig)}
    for key, val in block.items():
        if key not in allowed or val is None:
            continue
        spec = hints.get(key)
        if spec is int:
            out[key] = int(val)
        elif spec is Decimal:
            out[key] = val if isinstance(val, Decimal) else Decimal(str(val))
        elif spec is float:
            out[key] = float(val)
        else:
            out[key] = val
    return out


def _parse_entry_window(raw: Dict[str, Any]) -> EntryWindowConfig:
    cutoff = raw.get("cutoff_minutes_before_expiry", _MIN_CUTOFF_MINUTES)
    if cutoff < _MIN_CUTOFF_MINUTES:
        logger.warning(
            "cutoff_minutes_before_expiry=%s is below minimum %s — clamping to %s",
            cutoff, _MIN_CUTOFF_MINUTES, _MIN_CUTOFF_MINUTES,
        )
        cutoff = _MIN_CUTOFF_MINUTES
    # 15m scalper: longer entry window (30 min vs 10 min)
    is_scalper = os.getenv("STRATEGY_MODE", "").upper() == "MOMENTUM_SCALPER"
    default_minutes = 30 if is_scalper else 10
    return EntryWindowConfig(
        minutes_before_expiry=raw.get("minutes_before_expiry", default_minutes),
        cutoff_minutes_before_expiry=cutoff,
    )


def _parse_take_profit(raw: Optional[Dict[str, Any]], agent_name: str) -> Any:
    """Parse the optional ``take_profit:`` YAML block into a TakeProfitConfig.

    Falls back to the per-agent preset table if the block is absent.
    """
    try:
        from merid.event_venues.kalshi.take_profit import (
            get_tp_config_for_agent,
            tp_config_from_yaml,
        )
        base = get_tp_config_for_agent(agent_name)
        if raw:
            return tp_config_from_yaml(raw, base=base)
        return base
    except Exception as exc:
        logger.debug("_parse_take_profit failed for %s: %s", agent_name, exc)
        return None


def _parse_strike_selection(raw: Optional[Dict[str, Any]]) -> Optional[Any]:
    """Parse the optional ``strike_selection:`` YAML block.

    Returns a StrikeSelectionConfig or None if the block is absent.
    """
    if not raw:
        return None
    try:
        # LEGACY REMOVAL: kalshi_strike_selector moved to archive/legacy/ during 15m stack cleanup
        # return parse_strike_selection_config(raw)
        return None
    except Exception as exc:
        logger.debug("_parse_strike_selection failed: %s", exc)
        return None


def _parse_agent(raw: Dict[str, Any]) -> AgentConfig:
    name = raw["name"]
    # Resolve series_tickers: YAML explicit -> AGENT_SERIES_MAP lookup -> empty list
    series_tickers: List[str] = raw.get("series_tickers", [])
    logger.debug("[PARSE-AGENT] %s: YAML series_tickers=%s", name, series_tickers)
    if not series_tickers:
        try:
            from merid.event_venues.kalshi.market_selector import AGENT_SERIES_MAP
            series_tickers = AGENT_SERIES_MAP.get(name, [])
            logger.debug("[PARSE-AGENT] %s: AGENT_SERIES_MAP series_tickers=%s", name, series_tickers)
        except Exception as exc:
            logger.warning("[PARSE-AGENT] %s: AGENT_SERIES_MAP lookup failed: %s", name, exc)
            series_tickers = []
    logger.info("[PARSE-AGENT] %s: final series_tickers=%s", name, series_tickers)
    agent = AgentConfig(
        name=name,
        category=raw.get("category", "crypto"),
        assets=raw.get("assets", []),
        timeframes=raw.get("timeframes", []),
        market_filter=_parse_market_filter(raw.get("market_filter", {})),
        risk_limits=_parse_risk_limits(raw.get("risk_limits", {})),
        entry_window=_parse_entry_window(raw.get("entry_window", {})),
        enabled=raw.get("enabled", True),
        archetype=raw.get("archetype", "directional"),
        risk_profile=raw.get("risk_profile", "default"),
        pm_spot_hard_gate=bool(raw.get("pm_spot_hard_gate", False)),
        use_filter_pipeline=raw.get("use_filter_pipeline", False),
        filter_max_candidates_per_asset=raw.get("filter_max_candidates_per_asset", 10),
        filter_max_candidates_global=raw.get("filter_max_candidates_global", 20),
        strategy_overrides=_parse_strategy_overrides(raw.get("strategy_overrides")),
        bypass_swarm_consensus=bool(raw.get("bypass_swarm_consensus", False)),
        signalonly=bool(raw.get("signalonly", False)),
        take_profit=_parse_take_profit(raw.get("take_profit"), name),
        strike_selection=_parse_strike_selection(raw.get("strike_selection")),
        series_tickers=series_tickers,
    )

    # SAFETY: Log warning if bypass_swarm_consensus is set (it's now ignored)
    if agent.bypass_swarm_consensus:
        logger.warning(
            "[SECURITY] Agent %s has bypass_swarm_consensus=true in YAML - THIS IS IGNORED. "
            "All orders must flow through main execution gate.",
            name
        )

    # REMOVED: Legacy profile application code (lines 615-673)
    # Profile application is now handled exclusively by the 15m agent grid using
    # the apply_profile_to_agent() pure function in agent_grid_config.py
    # This prevents double-application and cross-contamination between legacy and new codepaths

    return agent


def _default_agent_grid_config() -> AgentGridConfig:
    """Return default config with settings-driven portfolio risk limits."""
    return AgentGridConfig(
        venue=VenueConfig(),
        session=SessionConfig(),
        agents=[],
        portfolio_risk=PortfolioRiskConfig(),  # All zeros = derive from settings
    )


# ── Known archetypes / categories for schema validation ───────────────
_KNOWN_ARCHETYPES = {
    "directional", "market_maker", "arbitrage", "momentum", "mean_reversion",
    "contrarian", "regime_switch", "vol_breakout",
}
_KNOWN_CATEGORIES = {
    "crypto", "economics", "financials", "politics", "weather", "macro",
    "climate", "sports", "tech", "all",
}
_REQUIRED_AGENT_KEYS = {"name"}


def _validate_agent_configs(raw_agents: list) -> List[str]:
    """Validate raw YAML agent dicts before parsing.

    Returns a list of error strings.  Empty list = clean.
    Fail-fast: the caller should abort loading on errors.
    """
    errors: List[str] = []
    if not isinstance(raw_agents, list):
        errors.append("'agents' key must be a YAML list")
        return errors

    for idx, entry in enumerate(raw_agents):
        prefix = f"agents[{idx}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: expected dict, got {type(entry).__name__}")
            continue

        # Required keys
        for key in _REQUIRED_AGENT_KEYS:
            if key not in entry:
                errors.append(f"{prefix}: missing required key '{key}'")

        name = entry.get("name", f"<unnamed-{idx}>")
        prefix = f"agents[{idx}] ({name})"

        # Archetype check
        arch = entry.get("archetype", "directional")
        if arch not in _KNOWN_ARCHETYPES:
            errors.append(f"{prefix}: unknown archetype '{arch}' (known: {sorted(_KNOWN_ARCHETYPES)})")

        # Category check
        cat = entry.get("category", "crypto")
        if cat not in _KNOWN_CATEGORIES:
            errors.append(f"{prefix}: unknown category '{cat}' (known: {sorted(_KNOWN_CATEGORIES)})")

        # Assets must be a list
        assets = entry.get("assets", [])
        if not isinstance(assets, list):
            errors.append(f"{prefix}: 'assets' must be a list, got {type(assets).__name__}")

        # Timeframes must be a list
        tf = entry.get("timeframes", [])
        if not isinstance(tf, list):
            errors.append(f"{prefix}: 'timeframes' must be a list, got {type(tf).__name__}")

        # risk_limits must be a dict
        rl = entry.get("risk_limits", {})
        if not isinstance(rl, dict):
            errors.append(f"{prefix}: 'risk_limits' must be a dict, got {type(rl).__name__}")

    return errors


def _preflight_grid_check(agents: List[AgentConfig]) -> None:
    """Run sanity checks on the parsed agent grid.

    Logs warnings for:
    - Duplicate agent names
    - Agents with no assets or no timeframes (orphans)
    - Category/archetype distribution imbalance
    """
    if not agents:
        logger.warning("[GRID-PREFLIGHT] No agents defined in grid config")
        return

    # Duplicate name detection
    seen_names: Dict[str, int] = {}
    for a in agents:
        seen_names[a.name] = seen_names.get(a.name, 0) + 1
    dupes = {n: c for n, c in seen_names.items() if c > 1}
    if dupes:
        logger.error("[GRID-PREFLIGHT] Duplicate agent names: %s", dupes)

    # Orphan detection
    for a in agents:
        # Skip asset/timeframe warnings for signal-only agents (context-only providers)
        if a.signalonly:
            continue
        if a.enabled and not a.assets:
            logger.warning("[GRID-PREFLIGHT] Agent %s is enabled but has no assets", a.name)
        if a.enabled and not a.timeframes:
            logger.warning("[GRID-PREFLIGHT] Agent %s is enabled but has no timeframes", a.name)

    # Archetype / category matrix
    arch_counts: Dict[str, int] = {}
    cat_counts: Dict[str, int] = {}
    enabled_count = 0
    for a in agents:
        if a.enabled:
            enabled_count += 1
            arch_counts[a.archetype] = arch_counts.get(a.archetype, 0) + 1
            cat_counts[a.category] = cat_counts.get(a.category, 0) + 1

    logger.info(
        "[GRID-PREFLIGHT] %d agents (%d enabled) | archetypes=%s | categories=%s",
        len(agents), enabled_count, dict(arch_counts), dict(cat_counts),
    )


def load_agent_grid_config(path: Optional[str] = None) -> AgentGridConfig:
    """Load and parse the Kalshi agent grid YAML config.

    Args:
        path: Override path to YAML file.  Defaults to config/kalshi_agent_grid.yaml.

    Returns:
        Fully typed AgentGridConfig.
    """
    config_path = path or os.environ.get("KALSHI_GRID_CONFIG", _DEFAULT_CONFIG_PATH)
    config_path = os.path.abspath(config_path)

    if not os.path.isfile(config_path):
        logger.warning(f"Config not found at {config_path}, using defaults")
        return _default_agent_grid_config()

    with open(config_path, "rb") as f:
        raw_bytes = f.read()

    raw_text: Optional[str] = None
    used_encoding: Optional[str] = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            raw_text = raw_bytes.decode(encoding)
            used_encoding = encoding
            break
        except UnicodeDecodeError:
            continue

    if raw_text is None:
        logger.error(
            "Unable to decode %s with supported encodings; using utf-8 replacement",
            config_path,
        )
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        used_encoding = "utf-8-replace"

    if used_encoding not in ("utf-8", "utf-8-sig"):
        logger.warning("Loaded Kalshi grid config using %s: %s", used_encoding, config_path)

    try:
        raw = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        logger.exception("Failed to parse Kalshi grid config %s: %s", config_path, exc)
        return _default_agent_grid_config()

    if raw is None:
        logger.warning(f"Empty config at {config_path}, using defaults")
        return _default_agent_grid_config()

    # Profile validation for 15m crypto agents
    _validate_profile_usage(raw, config_path)

    # Venue
    v = raw.get("venue", {})
    venue = VenueConfig(
        name=v.get("name", "kalshi"),
        use_demo=v.get("use_demo", False),
        max_notional_per_expiry_usd=Decimal(str(v.get("max_notional_per_expiry_usd", 0))),  # 0 = derive from bankroll
        max_open_markets_per_asset=v.get("max_open_markets_per_asset", 20),
    )

    # Session
    s = raw.get("session", {})
    session = SessionConfig(
        maintenance_day=s.get("maintenance_day", 3),
        maintenance_start_et=s.get("maintenance_start_et", "03:00"),
        maintenance_end_et=s.get("maintenance_end_et", "05:00"),
    )

    # Log effective maintenance window
    logger.info(
        "[MAINTENANCE] day=%d start_et=%s end_et=%s source=SessionConfig",
        session.maintenance_day, session.maintenance_start_et, session.maintenance_end_et
    )

    # Agents — validate raw YAML before parsing
    raw_agents = raw.get("agents", [])
    logger.info("[GRID-LOAD] Found %d raw agents in YAML", len(raw_agents))
    validation_errors = _validate_agent_configs(raw_agents)
    if validation_errors:
        for err in validation_errors:
            logger.error("[GRID-VALIDATE] %s", err)
        logger.error(
            "[GRID-VALIDATE] %d error(s) in %s — falling back to defaults",
            len(validation_errors), config_path,
        )
        return _default_agent_grid_config()

    logger.info("[GRID-LOAD] Parsing %d agents from YAML", len(raw_agents))
    agents = [_parse_agent(a) for a in raw_agents]
    logger.info("[GRID-LOAD] Parsed %d agents successfully", len(agents))

    # Pre-flight sanity checks (logs warnings, does not abort)
    _preflight_grid_check(agents)

    # Portfolio risk
    pr = raw.get("portfolio_risk", {})
    # Derive from settings if not specified in YAML (bankroll-driven defaults)
    from merid.settings import settings
    portfolio_risk = PortfolioRiskConfig(
        max_total_notional_usd=Decimal(str(pr.get("max_total_notional_usd", 0))),  # 0 triggers settings-derived
        max_notional_per_asset_usd=Decimal(str(pr.get("max_notional_per_asset_usd", 0))),
        max_open_markets=pr.get("max_open_markets", 50),
        max_daily_loss_usd=Decimal(str(pr.get("max_daily_loss_usd", 0))),
        max_margin_utilization_pct=Decimal(str(pr.get("max_margin_utilization_pct", 0))),
        rebalance_check_interval_seconds=pr.get("rebalance_check_interval_seconds", 0),
    )

    config = AgentGridConfig(
        venue=venue,
        session=session,
        agents=agents,
        portfolio_risk=portfolio_risk,
    )

    logger.info(
        f"Loaded Kalshi agent grid: {len(agents)} agents, "
        f"assets={config.all_assets}, demo={venue.use_demo}"
    )
    return config


# ── Singleton ──────────────────────────────────────────────────────────

_grid_config: Optional[AgentGridConfig] = None
_grid_config_lock = None


def get_agent_grid_config() -> AgentGridConfig:
    """Return the module-level AgentGridConfig singleton.
    
    Thread-safe initialization using locking to prevent race conditions
    during concurrent agent startup.
    """
    global _grid_config
    if _grid_config is None:
        if _grid_config_lock is not None:
            with _grid_config_lock:
                if _grid_config is None:
                    _grid_config = load_agent_grid_config()
        else:
            # Lock disabled - direct initialization (startup workaround)
            _grid_config = load_agent_grid_config()
    return _grid_config
