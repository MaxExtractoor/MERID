"""Paper Trading Configuration Matrix — single source of truth.

Every domain, instrument set, venue, limit, and agent mapping lives here.
merid.loop reads this at startup and auto-wires everything.

To enable a new domain in paper mode:
  1. Add a DomainConfig entry to DOMAIN_CONFIGS.
  2. The loop will auto-initialize feeds, agents, and reconciliation.

To promote a domain to live:
  1. Change mode from "paper" to "live".
  2. Reconciliation must be clean (no critical discrepancies).
  3. The execution gate in merid.loop enforces this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import threading


class DomainMode(str, Enum):
    SIM = "sim"
    PAPER = "paper"
    LIVE = "live"


# ── Per-Instrument Configuration ─────────────────────────────────────

@dataclass
class InstrumentConfig:
    """Per-instrument configuration with asset-class-specific overrides."""
    id: str                            # e.g. "BTC/USD", "BTC260220C00036000", "NFL_GAME_1234"
    domain: str                        # crypto, equity, prediction, betting, macro
    enabled: bool = True

    # Venue routing
    venues: List[str] = field(default_factory=list)

    # Size constraints
    min_size: float = 0.0
    max_size: float = 0.0              # 0 = no limit (use domain default)
    tick_size: float = 0.01
    quote_currency: str = "USD"

    # Leverage
    max_leverage: float = 1.0

    # Options-specific
    underlying: str = ""
    expiry: str = ""                   # ISO date
    strike: float = 0.0
    option_type: str = ""              # call, put
    contract_multiplier: float = 1.0

    # Prediction/betting-specific
    max_stake_usd: float = 0.0
    settlement_source: str = ""        # kalshi, odds_api, manual
    odds_format: str = ""              # decimal, american

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id, "domain": self.domain, "enabled": self.enabled,
            "venues": self.venues, "min_size": self.min_size,
            "max_size": self.max_size, "tick_size": self.tick_size,
            "max_leverage": self.max_leverage,
        }
        if self.underlying:
            d.update({"underlying": self.underlying, "expiry": self.expiry,
                      "strike": self.strike, "option_type": self.option_type,
                      "contract_multiplier": self.contract_multiplier})
        if self.max_stake_usd:
            d.update({"max_stake_usd": self.max_stake_usd,
                      "settlement_source": self.settlement_source})
        return d


# ── Global Risk Limits ───────────────────────────────────────────────

@dataclass
class GlobalRiskLimits:
    """Portfolio-level risk limits that override per-domain settings."""
    max_portfolio_drawdown_pct: float = 0.10   # 10% max drawdown
    max_portfolio_var_usd: float = 5_000.0     # Value at Risk limit
    max_total_notional_usd: float = 50_000.0
    kill_switch: bool = False                  # Global emergency stop
    max_correlated_exposure_pct: float = 0.30  # Max 30% in correlated assets
    max_single_venue_pct: float = 0.50         # Max 50% at any one venue

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_portfolio_drawdown_pct": self.max_portfolio_drawdown_pct,
            "max_portfolio_var_usd": self.max_portfolio_var_usd,
            "max_total_notional_usd": self.max_total_notional_usd,
            "kill_switch": self.kill_switch,
            "max_correlated_exposure_pct": self.max_correlated_exposure_pct,
            "max_single_venue_pct": self.max_single_venue_pct,
        }


# ── Reconciliation Configuration ─────────────────────────────────────

@dataclass
class ReconciliationConfig:
    """Thresholds and behavior for position reconciliation."""
    warning_qty_delta: float = 0.01    # Qty delta > this = warning
    critical_qty_delta: float = 1.0    # Qty delta > this = critical
    warning_price_pct: float = 5.0     # Entry price delta > this % = warning
    phantom_position_severity: str = "critical"  # Position on one side only
    block_execution_on_critical: bool = True
    persist_report: bool = True
    report_path: str = "data/reconciliation_report.json"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "warning_qty_delta": self.warning_qty_delta,
            "critical_qty_delta": self.critical_qty_delta,
            "warning_price_pct": self.warning_price_pct,
            "phantom_position_severity": self.phantom_position_severity,
            "block_execution_on_critical": self.block_execution_on_critical,
        }


# ── Matching Engine Configuration ────────────────────────────────────

@dataclass
class MatchingEngineConfig:
    """Config for internal orderbook simulation per domain."""
    enabled: bool = False
    engine_type: str = "clob"          # clob (continuous limit orderbook), amm
    instruments: List[str] = field(default_factory=list)
    max_book_depth: int = 100
    tick_size: float = 0.01

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "engine_type": self.engine_type,
            "instruments": self.instruments,
            "max_book_depth": self.max_book_depth,
        }


# ── Domain Configuration ─────────────────────────────────────────────

@dataclass
class DomainConfig:
    """Configuration for a single trading domain."""
    name: str
    mode: DomainMode = DomainMode.PAPER
    enabled: bool = True

    # Instruments
    symbols: List[str] = field(default_factory=list)

    # Venues allowed for this domain
    venues: List[str] = field(default_factory=list)

    # Risk limits
    max_notional_usd: float = 10_000.0
    max_daily_loss_usd: float = 500.0
    max_positions: int = 20
    max_single_order_usd: float = 1_000.0
    max_leverage: float = 1.0
    allocation_pct: float = 0.10       # % of total capital

    # Agent categories to activate for this domain
    agent_categories: List[str] = field(default_factory=list)

    # Reconciliation venue (if any — used to compare paper vs real)
    reconciliation_venue: Optional[str] = None

    # Feed configuration
    feed_type: str = "price"           # price, odds, kalshi, macro
    feed_refresh_seconds: float = 5.0

    # Paper engine implementation
    engine_type: str = "paper_trading"  # paper_trading, prediction_paper, betting_paper

    # Matching engine (internal orderbook simulation)
    matching_engine: Optional[MatchingEngineConfig] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "name": self.name,
            "mode": self.mode.value,
            "enabled": self.enabled,
            "symbols": self.symbols,
            "venues": self.venues,
            "max_notional_usd": self.max_notional_usd,
            "max_daily_loss_usd": self.max_daily_loss_usd,
            "max_positions": self.max_positions,
            "max_single_order_usd": self.max_single_order_usd,
            "max_leverage": self.max_leverage,
            "allocation_pct": self.allocation_pct,
            "agent_categories": self.agent_categories,
            "reconciliation_venue": self.reconciliation_venue,
            "feed_type": self.feed_type,
            "feed_refresh_seconds": self.feed_refresh_seconds,
            "engine_type": self.engine_type,
        }
        if self.matching_engine:
            d["matching_engine"] = self.matching_engine.to_dict()
        return d


# ── Domain Configurations ────────────────────────────────────────────

DOMAIN_CONFIGS: Dict[str, DomainConfig] = {

    # ── Prediction Markets (Kalshi) ───────────────────────────────────
    "prediction": DomainConfig(
        name="prediction",
        mode=DomainMode.PAPER,
        enabled=True,
        symbols=[],                    # Dynamic — populated from Kalshi market fetch
        venues=["kalshi"],
        max_notional_usd=5_000.0,
        max_daily_loss_usd=250.0,
        max_positions=20,
        max_single_order_usd=500.0,
        max_leverage=1.0,
        allocation_pct=0.10,
        agent_categories=["research", "strategy", "coordination"],
        reconciliation_venue="kalshi",     # Enable Kalshi reconciliation
        feed_type="kalshi",
        feed_refresh_seconds=60.0,
        engine_type="prediction_paper",
        matching_engine=MatchingEngineConfig(
            enabled=True,
            engine_type="clob",
            instruments=[],            # Populated dynamically from Kalshi
            max_book_depth=50,
            tick_size=0.01,
        ),
    ),
}


# ── Instrument Registry ──────────────────────────────────────────────

INSTRUMENT_REGISTRY: Dict[str, InstrumentConfig] = {
    # Kalshi prediction market instruments are dynamic —
    # populated at runtime via register_instrument() from the market fetch.
}


def register_instrument(instrument: InstrumentConfig) -> None:
    """Register a new instrument at runtime (e.g. from Kalshi/OddsAPI fetch)."""
    INSTRUMENT_REGISTRY[instrument.id] = instrument


def get_instrument(instrument_id: str) -> Optional[InstrumentConfig]:
    """Look up an instrument by ID. Returns None if not registered."""
    return INSTRUMENT_REGISTRY.get(instrument_id)


def instruments_for_domain(domain: str) -> List[InstrumentConfig]:
    """Return all registered instruments for a domain."""
    return [i for i in INSTRUMENT_REGISTRY.values() if i.domain == domain and i.enabled]


# ── Global Settings ────────────────────────────────────────────────────

@dataclass
class GlobalPaperConfig:
    """Top-level paper trading configuration."""
    total_capital_usd: float = 50_000.0
    max_portfolio_notional_usd: float = 50_000.0

    # Cadence (seconds)
    tick_interval: float = 5.0
    agent_cycle_interval: float = 60.0
    consensus_interval: float = 15.0
    arb_scan_interval: float = 10.0
    cqi_interval: float = 300.0
    reconciliation_interval: float = 120.0

    # Feature flags
    enable_execution: bool = False     # Paper fills only unless explicitly enabled
    enable_reconciliation: bool = True
    enable_notifications: bool = True
    enable_arb_execution: bool = False

    # Global risk limits
    risk_limits: GlobalRiskLimits = field(default_factory=GlobalRiskLimits)

    # Reconciliation configuration
    reconciliation: ReconciliationConfig = field(default_factory=ReconciliationConfig)

    # Domains — loaded from DOMAIN_CONFIGS
    domains: Dict[str, DomainConfig] = field(default_factory=lambda: dict(DOMAIN_CONFIGS))

    # Instrument registry
    instruments: Dict[str, InstrumentConfig] = field(
        default_factory=lambda: dict(INSTRUMENT_REGISTRY)
    )

    def active_domains(self) -> List[DomainConfig]:
        """Return only enabled domains."""
        return [d for d in self.domains.values() if d.enabled]

    def active_domain_names(self) -> List[str]:
        return [d.name for d in self.active_domains()]

    def all_symbols(self) -> List[str]:
        """Flatten all symbols across all active domains."""
        symbols = []
        for d in self.active_domains():
            symbols.extend(d.symbols)
        return sorted(set(symbols))

    def all_price_symbols(self) -> List[str]:
        """Symbols that need live price feeds (crypto + equity)."""
        symbols = []
        for d in self.active_domains():
            if d.feed_type == "price":
                symbols.extend(d.symbols)
        return sorted(set(symbols))

    def all_venues(self) -> List[str]:
        """All venues across all active domains."""
        venues = []
        for d in self.active_domains():
            venues.extend(d.venues)
        return sorted(set(venues))

    def reconciliation_venues(self) -> List[str]:
        """Venues that have reconciliation configured."""
        return sorted(set(
            d.reconciliation_venue
            for d in self.active_domains()
            if d.reconciliation_venue
        ))

    def domain_is_paper_or_sim(self, domain_name: str) -> bool:
        """Check if a domain is in paper or sim mode (not live)."""
        d = self.domains.get(domain_name)
        if not d:
            return True
        return d.mode in (DomainMode.SIM, DomainMode.PAPER)

    def can_execute_live(self, domain_name: str) -> bool:
        """Check if a domain is cleared for live execution."""
        d = self.domains.get(domain_name)
        if not d or not d.enabled:
            return False
        return d.mode == DomainMode.LIVE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_capital_usd": self.total_capital_usd,
            "max_portfolio_notional_usd": self.max_portfolio_notional_usd,
            "tick_interval": self.tick_interval,
            "enable_execution": self.enable_execution,
            "enable_reconciliation": self.enable_reconciliation,
            "risk_limits": self.risk_limits.to_dict(),
            "reconciliation": self.reconciliation.to_dict(),
            "active_domains": [d.to_dict() for d in self.active_domains()],
            "all_venues": self.all_venues(),
            "reconciliation_venues": self.reconciliation_venues(),
            "instruments_registered": len(self.instruments),
        }


# ── Singleton ────────────────────────────────────────────────────────

_config: Optional[GlobalPaperConfig] = None
_config_lock = threading.Lock()


def get_paper_config() -> GlobalPaperConfig:
    """Get or create the global paper trading config singleton."""
    global _config
    if _config is None:
        with _config_lock:
            if _config is None:
                _config = GlobalPaperConfig()
    return _config
