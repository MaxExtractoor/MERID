"""Kalshi Agent Grid — YAML config loader and typed data models.

Loads config/kalshi_agent_grid.yaml and exposes strongly-typed dataclasses
that the orchestrator, trading agents, and portfolio risk agent consume.
"""

from __future__ import annotations

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
DEFAULT_KALSHI_BASE_URL = "https://trading-api.kalshi.com/trade-api/v2"


# ── Typed config models ────────────────────────────────────────────────

@dataclass
class VenueConfig:
    """Top-level venue settings."""
    name: str = "kalshi"
    base_url: str = DEFAULT_KALSHI_BASE_URL
    use_demo: bool = False
    max_notional_per_expiry_usd: Decimal = Decimal("5000")
    max_open_markets_per_asset: int = 20


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
    frequency: Optional[str] = None   # fifteen_min, hourly, daily, weekly
    tags: List[str] = field(default_factory=list)


@dataclass
class AgentRiskLimits:
    """Per-agent risk limits."""
    max_yes_position: int = 3000
    max_no_position: int = 3000
    max_orders_per_window: int = 10
    max_notional_usd: Decimal = Decimal("500")


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
    assets: List[str] = field(default_factory=list)
    timeframes: List[str] = field(default_factory=list)
    market_filter: MarketFilterConfig = field(default_factory=MarketFilterConfig)
    risk_limits: AgentRiskLimits = field(default_factory=AgentRiskLimits)
    entry_window: EntryWindowConfig = field(default_factory=EntryWindowConfig)
    enabled: bool = True
    archetype: str = "directional"  # directional, market_maker, arbitrage

    @property
    def agent_id(self) -> str:
        return f"kalshi-{self.name.lower()}"


@dataclass
class PortfolioRiskConfig:
    """Portfolio-level risk limits across all agents."""
    max_total_notional_usd: Decimal = Decimal("25000")
    max_notional_per_asset_usd: Decimal = Decimal("8000")
    max_open_markets: int = 50
    max_daily_loss_usd: Decimal = Decimal("2000")
    max_margin_utilization_pct: Decimal = Decimal("75")
    rebalance_check_interval_seconds: int = 30


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
        max_yes_position=raw.get("max_yes_position", 3000),
        max_no_position=raw.get("max_no_position", 3000),
        max_orders_per_window=raw.get("max_orders_per_window", 10),
        max_notional_usd=Decimal(str(raw.get("max_notional_usd", 500))),
    )


def _parse_entry_window(raw: Dict[str, Any]) -> EntryWindowConfig:
    return EntryWindowConfig(
        minutes_before_expiry=raw.get("minutes_before_expiry", 10),
        cutoff_minutes_before_expiry=raw.get("cutoff_minutes_before_expiry", 2),
    )


def _parse_agent(raw: Dict[str, Any]) -> AgentConfig:
    return AgentConfig(
        name=raw["name"],
        category=raw.get("category", "crypto"),
        assets=raw.get("assets", []),
        timeframes=raw.get("timeframes", []),
        market_filter=_parse_market_filter(raw.get("market_filter", {})),
        risk_limits=_parse_risk_limits(raw.get("risk_limits", {})),
        entry_window=_parse_entry_window(raw.get("entry_window", {})),
        enabled=raw.get("enabled", True),
        archetype=raw.get("archetype", "directional"),
    )


def _default_agent_grid_config() -> AgentGridConfig:
    return AgentGridConfig(
        venue=VenueConfig(),
        session=SessionConfig(),
        agents=[],
        portfolio_risk=PortfolioRiskConfig(),
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

    if not raw:
        logger.warning(f"Empty config at {config_path}, using defaults")
        return _default_agent_grid_config()

    # Venue
    v = raw.get("venue", {})
    venue = VenueConfig(
        name=v.get("name", "kalshi"),
        base_url=v.get("base_url", DEFAULT_KALSHI_BASE_URL),
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
    portfolio_risk = PortfolioRiskConfig(
        max_total_notional_usd=Decimal(str(pr.get("max_total_notional_usd", 25000))),
        max_notional_per_asset_usd=Decimal(str(pr.get("max_notional_per_asset_usd", 8000))),
        max_open_markets=pr.get("max_open_markets", 50),
        max_daily_loss_usd=Decimal(str(pr.get("max_daily_loss_usd", 2000))),
        max_margin_utilization_pct=Decimal(str(pr.get("max_margin_utilization_pct", 75))),
        rebalance_check_interval_seconds=pr.get("rebalance_check_interval_seconds", 30),
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


def get_agent_grid_config() -> AgentGridConfig:
    """Return the module-level AgentGridConfig singleton."""
    global _grid_config
    if _grid_config is None:
        _grid_config = load_agent_grid_config()
    return _grid_config
