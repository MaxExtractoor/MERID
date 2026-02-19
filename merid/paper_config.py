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


class DomainMode(str, Enum):
    SIM = "sim"
    PAPER = "paper"
    LIVE = "live"


# ── Per-Instrument Configuration ─────────────────────────────────────

@dataclass
class InstrumentConfig:
    """Per-instrument configuration with asset-class-specific overrides."""
    id: str                            # e.g. "BTC/USDT", "BTC260220C00036000", "NFL_GAME_1234"
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

    # ── Crypto ────────────────────────────────────────────────────────
    "crypto": DomainConfig(
        name="crypto",
        mode=DomainMode.PAPER,
        enabled=True,
        symbols=[
            # Majors
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT",
            # Alt L1/L2
            "ADA/USDT", "DOT/USDT", "ATOM/USDT", "NEAR/USDT",
            "APT/USDT", "SUI/USDT", "SEI/USDT",
            "POL/USDT", "ARB/USDT", "OP/USDT",
            # DeFi
            "LINK/USDT", "UNI/USDT", "AAVE/USDT", "MKR/USDT",
            "SNX/USDT", "CRV/USDT", "LDO/USDT",
            # Memecoins
            "DOGE/USDT", "SHIB/USDT", "PEPE/USDT", "WIF/USDT",
            "BONK/USDT", "FLOKI/USDT",
            # Infrastructure
            "FIL/USDT", "AR/USDT", "RENDER/USDT",
            # Stablecoins (reference)
            "USDC/USDT",
        ],
        venues=["kraken", "coinbase", "binance", "okx"],
        max_notional_usd=25_000.0,
        max_daily_loss_usd=1_000.0,
        max_positions=30,
        max_single_order_usd=5_000.0,
        max_leverage=3.0,
        allocation_pct=0.50,
        agent_categories=["research", "strategy", "risk"],
        reconciliation_venue="binance",  # Exchange snapshot for paper vs real comparison
        feed_type="price",
        feed_refresh_seconds=1.0,
        engine_type="paper_trading",
    ),

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

    # ── Equities / Options ────────────────────────────────────────────────
    "equity": DomainConfig(
        name="equity",
        mode=DomainMode.PAPER,
        enabled=True,
        symbols=[
            "AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "GOOGL", "META",
            "SPY", "QQQ", "IWM",
            # BTC options tracked via Alpaca
            "BTC260220C00036000",
        ],
        venues=["alpaca", "ibkr"],
        max_notional_usd=20_000.0,
        max_daily_loss_usd=500.0,
        max_positions=50,
        max_single_order_usd=2_000.0,
        max_leverage=2.0,
        allocation_pct=0.40,
        agent_categories=["research", "strategy", "risk"],
        reconciliation_venue="alpaca",
        feed_type="price",
        feed_refresh_seconds=5.0,
        engine_type="paper_trading",
    ),

    # ── Sports Betting ────────────────────────────────────────────────
    "betting": DomainConfig(
        name="betting",
        mode=DomainMode.PAPER,
        enabled=True,
        symbols=[
            # Sports leagues (TheOddsAPI sport keys)
            "americanfootball_nfl",
            "basketball_nba",
            "baseball_mlb",
            "icehockey_nhl",
            "soccer_epl",
            "soccer_usa_mls",
            "mma_mixed_martial_arts",
            "basketball_ncaab",
            "americanfootball_ncaaf",
        ],
        venues=[],                     # No direct betting venue — consensus/analysis only
        max_notional_usd=2_000.0,
        max_daily_loss_usd=200.0,
        max_positions=10,
        max_single_order_usd=200.0,
        max_leverage=1.0,
        allocation_pct=0.05,
        agent_categories=["research"],
        reconciliation_venue=None,
        feed_type="odds",
        feed_refresh_seconds=120.0,
        engine_type="betting_paper",
        matching_engine=MatchingEngineConfig(
            enabled=False,             # Analysis-only for now
            engine_type="clob",
            instruments=[],
        ),
    ),

    # ── Macro / Rates ─────────────────────────────────────────────────
    "macro": DomainConfig(
        name="macro",
        mode=DomainMode.PAPER,
        enabled=True,
        symbols=[
            # FRED series IDs
            "DFF",          # Fed Funds Rate
            "DGS10",        # 10Y Treasury
            "DGS2",         # 2Y Treasury
            "T10Y2Y",       # 10Y-2Y spread
            "DTWEXBGS",     # Trade-weighted USD
            "CPIAUCSL",     # CPI
            "UNRATE",       # Unemployment
            "VIXCLS",       # VIX
        ],
        venues=[],                     # Macro is read-only / signal generation
        max_notional_usd=10_000.0,
        max_daily_loss_usd=300.0,
        max_positions=10,
        max_single_order_usd=1_000.0,
        max_leverage=1.0,
        allocation_pct=0.20,
        agent_categories=["research"],
        reconciliation_venue=None,
        feed_type="macro",
        feed_refresh_seconds=300.0,
        engine_type="signal_only",
    ),
}


# ── Instrument Registry ──────────────────────────────────────────────

INSTRUMENT_REGISTRY: Dict[str, InstrumentConfig] = {
    # ── Crypto majors ──────────────────────────────────────────────────
    "BTC/USDT": InstrumentConfig(
        id="BTC/USDT", domain="crypto",
        venues=["kraken", "coinbase", "binance", "okx"],
        min_size=0.0001, max_size=5.0, tick_size=0.50,
        max_leverage=3.0,
    ),
    "ETH/USDT": InstrumentConfig(
        id="ETH/USDT", domain="crypto",
        venues=["kraken", "coinbase", "binance", "okx"],
        min_size=0.001, max_size=50.0, tick_size=0.10,
        max_leverage=3.0,
    ),
    "SOL/USDT": InstrumentConfig(
        id="SOL/USDT", domain="crypto",
        venues=["kraken", "coinbase", "binance"],
        min_size=0.01, max_size=500.0, tick_size=0.01,
        max_leverage=3.0,
    ),
    "AVAX/USDT": InstrumentConfig(
        id="AVAX/USDT", domain="crypto",
        venues=["kraken", "coinbase", "binance"],
        min_size=0.1, max_size=1000.0, tick_size=0.01,
        max_leverage=3.0,
    ),

    # ── Crypto alt L1/L2 ──────────────────────────────────────────────
    "ADA/USDT": InstrumentConfig(
        id="ADA/USDT", domain="crypto",
        venues=["kraken", "binance", "okx"],
        min_size=1.0, max_size=50000.0, tick_size=0.0001,
        max_leverage=2.0,
    ),
    "DOT/USDT": InstrumentConfig(
        id="DOT/USDT", domain="crypto",
        venues=["kraken", "binance", "okx"],
        min_size=0.1, max_size=5000.0, tick_size=0.001,
        max_leverage=2.0,
    ),
    "ATOM/USDT": InstrumentConfig(
        id="ATOM/USDT", domain="crypto",
        venues=["kraken", "binance", "coinbase"],
        min_size=0.1, max_size=5000.0, tick_size=0.001,
        max_leverage=2.0,
    ),
    "NEAR/USDT": InstrumentConfig(
        id="NEAR/USDT", domain="crypto",
        venues=["binance", "okx"],
        min_size=0.1, max_size=10000.0, tick_size=0.001,
        max_leverage=2.0,
    ),
    "APT/USDT": InstrumentConfig(
        id="APT/USDT", domain="crypto",
        venues=["binance", "okx", "coinbase"],
        min_size=0.1, max_size=5000.0, tick_size=0.01,
        max_leverage=2.0,
    ),
    "SUI/USDT": InstrumentConfig(
        id="SUI/USDT", domain="crypto",
        venues=["binance", "okx"],
        min_size=1.0, max_size=50000.0, tick_size=0.0001,
        max_leverage=2.0,
    ),
    "SEI/USDT": InstrumentConfig(
        id="SEI/USDT", domain="crypto",
        venues=["binance", "okx"],
        min_size=1.0, max_size=50000.0, tick_size=0.0001,
        max_leverage=2.0,
    ),
    "POL/USDT": InstrumentConfig(
        id="POL/USDT", domain="crypto",
        venues=["kraken", "binance", "coinbase"],
        min_size=1.0, max_size=50000.0, tick_size=0.0001,
        max_leverage=2.0,
    ),
    "ARB/USDT": InstrumentConfig(
        id="ARB/USDT", domain="crypto",
        venues=["binance", "okx", "coinbase"],
        min_size=1.0, max_size=20000.0, tick_size=0.0001,
        max_leverage=2.0,
    ),
    "OP/USDT": InstrumentConfig(
        id="OP/USDT", domain="crypto",
        venues=["binance", "okx", "coinbase"],
        min_size=1.0, max_size=20000.0, tick_size=0.0001,
        max_leverage=2.0,
    ),

    # ── Crypto DeFi ───────────────────────────────────────────────────
    "LINK/USDT": InstrumentConfig(
        id="LINK/USDT", domain="crypto",
        venues=["kraken", "coinbase", "binance"],
        min_size=0.1, max_size=5000.0, tick_size=0.001,
        max_leverage=2.0,
    ),
    "UNI/USDT": InstrumentConfig(
        id="UNI/USDT", domain="crypto",
        venues=["kraken", "coinbase", "binance"],
        min_size=0.1, max_size=5000.0, tick_size=0.001,
        max_leverage=2.0,
    ),
    "AAVE/USDT": InstrumentConfig(
        id="AAVE/USDT", domain="crypto",
        venues=["kraken", "coinbase", "binance"],
        min_size=0.01, max_size=500.0, tick_size=0.01,
        max_leverage=2.0,
    ),
    "MKR/USDT": InstrumentConfig(
        id="MKR/USDT", domain="crypto",
        venues=["kraken", "coinbase", "binance"],
        min_size=0.001, max_size=50.0, tick_size=0.10,
        max_leverage=1.0,
    ),
    "SNX/USDT": InstrumentConfig(
        id="SNX/USDT", domain="crypto",
        venues=["binance", "okx"],
        min_size=1.0, max_size=10000.0, tick_size=0.001,
        max_leverage=1.0,
    ),
    "CRV/USDT": InstrumentConfig(
        id="CRV/USDT", domain="crypto",
        venues=["binance", "okx"],
        min_size=1.0, max_size=50000.0, tick_size=0.0001,
        max_leverage=1.0,
    ),
    "LDO/USDT": InstrumentConfig(
        id="LDO/USDT", domain="crypto",
        venues=["binance", "okx"],
        min_size=1.0, max_size=20000.0, tick_size=0.0001,
        max_leverage=1.0,
    ),

    # ── Crypto memecoins ──────────────────────────────────────────────
    "DOGE/USDT": InstrumentConfig(
        id="DOGE/USDT", domain="crypto",
        venues=["kraken", "coinbase", "binance"],
        min_size=10.0, max_size=500000.0, tick_size=0.00001,
        max_leverage=2.0,
    ),
    "SHIB/USDT": InstrumentConfig(
        id="SHIB/USDT", domain="crypto",
        venues=["binance", "okx"],
        min_size=100000.0, max_size=10000000000.0, tick_size=0.00000001,
        max_leverage=1.0,
    ),
    "PEPE/USDT": InstrumentConfig(
        id="PEPE/USDT", domain="crypto",
        venues=["binance", "okx"],
        min_size=100000.0, max_size=10000000000.0, tick_size=0.00000001,
        max_leverage=1.0,
    ),
    "WIF/USDT": InstrumentConfig(
        id="WIF/USDT", domain="crypto",
        venues=["binance", "okx"],
        min_size=1.0, max_size=100000.0, tick_size=0.0001,
        max_leverage=1.0,
    ),
    "BONK/USDT": InstrumentConfig(
        id="BONK/USDT", domain="crypto",
        venues=["binance", "okx"],
        min_size=100000.0, max_size=10000000000.0, tick_size=0.00000001,
        max_leverage=1.0,
    ),
    "FLOKI/USDT": InstrumentConfig(
        id="FLOKI/USDT", domain="crypto",
        venues=["binance", "okx"],
        min_size=100000.0, max_size=10000000000.0, tick_size=0.00000001,
        max_leverage=1.0,
    ),

    # ── Crypto infrastructure ─────────────────────────────────────────
    "FIL/USDT": InstrumentConfig(
        id="FIL/USDT", domain="crypto",
        venues=["kraken", "binance", "coinbase"],
        min_size=0.1, max_size=5000.0, tick_size=0.001,
        max_leverage=2.0,
    ),
    "AR/USDT": InstrumentConfig(
        id="AR/USDT", domain="crypto",
        venues=["binance", "okx"],
        min_size=0.1, max_size=2000.0, tick_size=0.01,
        max_leverage=1.0,
    ),
    "RENDER/USDT": InstrumentConfig(
        id="RENDER/USDT", domain="crypto",
        venues=["binance", "coinbase"],
        min_size=0.1, max_size=5000.0, tick_size=0.001,
        max_leverage=1.0,
    ),

    # ── Stablecoins (reference) ───────────────────────────────────────
    "USDC/USDT": InstrumentConfig(
        id="USDC/USDT", domain="crypto",
        venues=["kraken", "coinbase", "binance", "okx"],
        min_size=1.0, max_size=1000000.0, tick_size=0.0001,
        max_leverage=1.0,
    ),

    # ── Options ───────────────────────────────────────────────────────
    "BTC260220C00036000": InstrumentConfig(
        id="BTC260220C00036000", domain="equity",
        venues=["alpaca"],
        min_size=1.0, max_size=50.0, tick_size=0.01,
        underlying="BTC-USD", expiry="2026-02-20",
        strike=36_000.0, option_type="call",
        contract_multiplier=1.0,
    ),

    # ── Equities ──────────────────────────────────────────────────────
    "AAPL": InstrumentConfig(
        id="AAPL", domain="equity",
        venues=["alpaca", "ibkr"],
        min_size=1.0, max_size=1000.0, tick_size=0.01,
    ),
    "TSLA": InstrumentConfig(
        id="TSLA", domain="equity",
        venues=["alpaca", "ibkr"],
        min_size=1.0, max_size=500.0, tick_size=0.01,
    ),
    "NVDA": InstrumentConfig(
        id="NVDA", domain="equity",
        venues=["alpaca", "ibkr"],
        min_size=1.0, max_size=500.0, tick_size=0.01,
    ),
    "MSFT": InstrumentConfig(
        id="MSFT", domain="equity",
        venues=["alpaca", "ibkr"],
        min_size=1.0, max_size=500.0, tick_size=0.01,
    ),
    "AMZN": InstrumentConfig(
        id="AMZN", domain="equity",
        venues=["alpaca", "ibkr"],
        min_size=1.0, max_size=500.0, tick_size=0.01,
    ),
    "GOOGL": InstrumentConfig(
        id="GOOGL", domain="equity",
        venues=["alpaca", "ibkr"],
        min_size=1.0, max_size=500.0, tick_size=0.01,
    ),
    "META": InstrumentConfig(
        id="META", domain="equity",
        venues=["alpaca", "ibkr"],
        min_size=1.0, max_size=500.0, tick_size=0.01,
    ),
    "SPY": InstrumentConfig(
        id="SPY", domain="equity",
        venues=["alpaca", "ibkr"],
        min_size=1.0, max_size=500.0, tick_size=0.01,
    ),
    "QQQ": InstrumentConfig(
        id="QQQ", domain="equity",
        venues=["alpaca", "ibkr"],
        min_size=1.0, max_size=500.0, tick_size=0.01,
    ),
    "IWM": InstrumentConfig(
        id="IWM", domain="equity",
        venues=["alpaca", "ibkr"],
        min_size=1.0, max_size=500.0, tick_size=0.01,
    ),

    # ── Prediction markets ───────────────────────────────────────────
    # (dynamic — populated at runtime from Kalshi market fetch)

    # ── Sports betting ───────────────────────────────────────────────
    # (dynamic — populated at runtime from TheOddsAPI)
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


def get_paper_config() -> GlobalPaperConfig:
    """Get or create the global paper trading config singleton."""
    global _config
    if _config is None:
        _config = GlobalPaperConfig()
    return _config
