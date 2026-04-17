"""Kalshi Agent Grid — YAML config loader and typed data models.

Loads config/kalshi_agent_grid.yaml and exposes strongly-typed dataclasses
that the orchestrator, trading agents, and portfolio risk agent consume.
"""

from __future__ import annotations

import threading
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

import yaml

from utils.logger import get_logger

logger = get_logger("merid.prediction.agent_grid_config")

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "kalshi_agent_grid.yaml"
)


# ── Typed config models ────────────────────────────────────────────────

@dataclass
class VenueConfig:
    """Top-level venue settings.
    
    NOTE: base_url is read from KALSHI_API_BASE_URL env var via invariants module.
    Do not construct URLs manually; always use get_kalshi_base_url() from invariants.
    """
    name: str = "kalshi"
    use_demo: bool = False
    max_notional_per_expiry_usd: Decimal = Decimal("5000")
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


@dataclass
class MarketFilterConfig:
    """Filter used to resolve Kalshi tickers for an agent."""
    category: str = "crypto"
    frequency: Optional[str] = None   # fifteen_min, hourly, daily, weekly, monthly, annual
    tags: List[str] = field(default_factory=list)


@dataclass
class AgentRiskLimits:
    """Per-agent risk limits."""
    max_yes_position: int = 500
    max_no_position: int = 500
    max_orders_per_window: int = 10
    max_notional_usd: Decimal = Decimal("500")
    max_contracts_per_order: int = 50


@dataclass
class EntryWindowConfig:
    """When the agent is allowed to enter relative to contract expiry."""
    minutes_before_expiry: int = 10
    cutoff_minutes_before_expiry: int = 2


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
        """Derive any zero values from settings (bankroll-driven limits)."""
        from merid.settings import settings
        
        bankroll_cents = settings.KALSHI_PORTFOLIO_BANKROLL_CENTS
        
        if self.max_total_notional_usd == 0:
            self.max_total_notional_usd = Decimal(settings.kalshi_portfolio_max_notional_cents) / 100
        if self.max_daily_loss_usd == 0:
            self.max_daily_loss_usd = Decimal(settings.kalshi_portfolio_max_daily_loss_cents) / 100
        if self.max_notional_per_asset_usd == 0:
            self.max_notional_per_asset_usd = Decimal(settings.kalshi_portfolio_max_per_asset_cents) / 100
        if self.max_margin_utilization_pct == 0:
            self.max_margin_utilization_pct = Decimal(str(settings.KALSHI_PORTFOLIO_MAX_MARGIN_UTIL_PCT * 100))
        if self.rebalance_check_interval_seconds == 0:
            self.rebalance_check_interval_seconds = settings.KALSHI_PORTFOLIO_CHECK_INTERVAL_S


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
    return AgentRiskLimits(
        max_yes_position=raw.get("max_yes_position", 500),
        max_no_position=raw.get("max_no_position", 500),
        max_orders_per_window=raw.get("max_orders_per_window", 10),
        max_notional_usd=Decimal(str(raw.get("max_notional_usd", 500))),
        max_contracts_per_order=raw.get("max_contracts_per_order", 50),
    )


_MIN_CUTOFF_MINUTES = 2  # Hard floor: never enter inside 2 min of expiry


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
    return EntryWindowConfig(
        minutes_before_expiry=raw.get("minutes_before_expiry", 10),
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
        from merid.prediction.kalshi_strike_selector import parse_strike_selection_config
        return parse_strike_selection_config(raw)
    except Exception as exc:
        logger.debug("_parse_strike_selection failed: %s", exc)
        return None


def _parse_agent(raw: Dict[str, Any]) -> AgentConfig:
    name = raw["name"]
    # Resolve series_tickers: YAML explicit -> AGENT_SERIES_MAP lookup -> empty list
    series_tickers: List[str] = raw.get("series_tickers", [])
    if not series_tickers:
        try:
            from merid.event_venues.kalshi.market_selector import AGENT_SERIES_MAP
            series_tickers = AGENT_SERIES_MAP.get(name, [])
        except Exception:
            series_tickers = []
    return AgentConfig(
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
        strategy_overrides=_parse_strategy_overrides(raw.get("strategy")),
        bypass_swarm_consensus=bool(raw.get("bypass_swarm_consensus", False)),
        take_profit=_parse_take_profit(raw.get("take_profit"), name),
        strike_selection=_parse_strike_selection(raw.get("strike_selection")),
        series_tickers=series_tickers,
    )


def _default_agent_grid_config() -> AgentGridConfig:
    """Return default config with settings-driven portfolio risk limits."""
    return AgentGridConfig(
        venue=VenueConfig(),
        session=SessionConfig(),
        agents=[],
        portfolio_risk=PortfolioRiskConfig(),  # All zeros = derive from settings
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

    # Venue
    v = raw.get("venue", {})
    venue = VenueConfig(
        name=v.get("name", "kalshi"),
        use_demo=v.get("use_demo", False),
        max_notional_per_expiry_usd=Decimal(str(v.get("max_notional_per_expiry_usd", 5000))),
        max_open_markets_per_asset=v.get("max_open_markets_per_asset", 20),
    )

    # Session
    s = raw.get("session", {})
    session = SessionConfig(
        maintenance_day=s.get("maintenance_day", 3),
        maintenance_start_et=s.get("maintenance_start_et", "03:00"),
        maintenance_end_et=s.get("maintenance_end_et", "05:00"),
    )

    # Agents
    agents = [_parse_agent(a) for a in raw.get("agents", [])]

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
_grid_config_lock = threading.Lock()


def get_agent_grid_config() -> AgentGridConfig:
    """Return the module-level AgentGridConfig singleton.
    
    Thread-safe initialization using locking to prevent race conditions
    during concurrent agent startup.
    """
    global _grid_config
    with _grid_config_lock:
        if _grid_config is None:
            _grid_config = load_agent_grid_config()
    return _grid_config
