"""§3 VenueConfig + ModeManager — Per-venue SIM/PAPER/LIVE gating.

Each venue can independently be in SIM, PAPER, or LIVE mode.
Domains (prediction, crypto, equity) can be enabled/disabled independently.

Kalshi mode is driven by the ``KALSHI_ENV`` environment variable:
    live  → TradingMode.LIVE  (real-money Kalshi production API)
    demo  → TradingMode.SIM   (Kalshi sandbox/demo API)
    <unset> → TradingMode.SIM with a WARNING log

Alpaca and IBKR entries in _DEFAULT_CONFIGS are LEGACY — they are
included only for compatibility with shared infrastructure that iterates
over venue configs.  They are NOT used in the production Kalshi path and
produce no live orders in a pure Kalshi deployment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.pipeline.mode_manager")


class TradingMode(str, Enum):
    SIM = "sim"
    PAPER = "paper"
    LIVE = "live"


@dataclass
class VenueConfig:
    """Per-venue configuration."""
    venue: str
    domain: str                        # "prediction", "crypto", "equity"
    mode: TradingMode = TradingMode.SIM
    enabled: bool = True
    api_key_env: str = ""              # Env var name for API key
    api_secret_env: str = ""           # Env var name for API secret
    api_url: str = ""
    rate_limit_per_second: float = 10.0
    max_order_size_usd: float = 1000.0
    notes: str = ""

    def has_credentials(self) -> bool:
        """Check if API credentials are available in environment."""
        if self.api_key_env and os.getenv(self.api_key_env):
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "venue": self.venue,
            "domain": self.domain,
            "mode": self.mode.value,
            "enabled": self.enabled,
            "has_credentials": self.has_credentials(),
            "rate_limit_per_second": self.rate_limit_per_second,
            "max_order_size_usd": self.max_order_size_usd,
        }


def _kalshi_default_mode() -> TradingMode:
    """Resolve Kalshi's default TradingMode from environment variables.

    Precedence:
      1. ``KALSHI_ENV=live``  → TradingMode.LIVE
      2. ``KALSHI_ENV=demo``  → TradingMode.SIM  (explicit demo/sandbox)
      3. ``KALSHI_ENV`` unset → TradingMode.SIM  + WARNING log
    """
    kalshi_env = os.getenv("KALSHI_ENV", "").lower().strip()
    if kalshi_env == "live":
        return TradingMode.LIVE
    if kalshi_env in ("demo", "sandbox", "staging"):
        return TradingMode.SIM
    logger.warning(
        "MERID_PIPELINE_MODE: KALSHI_ENV is not set — defaulting Kalshi venue to SIM. "
        "Set KALSHI_ENV=live in production to enable live Kalshi trading via the unified pipeline."
    )
    return TradingMode.SIM


# ── Default venue configs ────────────────────────────────────────────

_DEFAULT_CONFIGS: List[VenueConfig] = [
    # Prediction — Kalshi mode driven by KALSHI_ENV env var (live/demo/unset)
    VenueConfig(
        venue="kalshi", domain="prediction", mode=_kalshi_default_mode(),
        api_key_env="KALSHI_API_KEY_ID", api_secret_env="KALSHI_PRIVATE_KEY_PATH",
        api_url="https://api.elections.kalshi.com/trade-api/v2",
        max_order_size_usd=500.0,
    ),
    # Crypto
    VenueConfig(
        venue="binance", domain="crypto", mode=TradingMode.SIM,
        api_key_env="BINANCE_API_KEY", api_secret_env="BINANCE_API_SECRET",
        api_url="https://api.binance.us",
        rate_limit_per_second=10.0,
    ),
    VenueConfig(
        venue="coinbase", domain="crypto", mode=TradingMode.SIM,
        api_key_env="COINBASE_API_KEY", api_secret_env="COINBASE_API_SECRET",
        api_url="https://api.coinbase.com",
    ),
    VenueConfig(
        venue="kraken", domain="crypto", mode=TradingMode.SIM,
        api_key_env="KRAKEN_API_KEY", api_secret_env="KRAKEN_PRIVATE_KEY",
        api_url="https://api.kraken.com",
        rate_limit_per_second=0.33,  # Kraken is strict
    ),
    VenueConfig(
        venue="okx", domain="crypto", mode=TradingMode.SIM,
        api_key_env="OKX_KEY", api_secret_env="OKX_SECRET",
        api_url="https://www.okx.com",
        notes="Data/sim only for US residents unless legally cleared.",
    ),
    # LEGACY (Alpaca/IBKR) — not used in production Kalshi; equity domain only
    VenueConfig(
        venue="alpaca", domain="equity", mode=TradingMode.PAPER,
        api_key_env="ALPACA_API_KEY", api_secret_env="ALPACA_API_SECRET",
        api_url="https://paper-api.alpaca.markets",
        notes="LEGACY — Alpaca equity venue; not used in production Kalshi deployment.",
    ),
    VenueConfig(
        venue="ibkr", domain="equity", mode=TradingMode.PAPER,
        api_key_env="IBKR_PAPER_TRADING_USERNAME",
        api_url="127.0.0.1:7497",
        notes="LEGACY — IBKR equity venue; not used in production Kalshi deployment.",
    ),
]


class ModeManager:
    """Manages per-venue and per-domain trading modes.

    Usage::

        mm = ModeManager()
        mm.check_can_trade("binance")          # raises if SIM
        mm.set_venue_mode("binance", TradingMode.PAPER)
        mm.disable_domain("prediction")        # pause all PM venues
    """

    class VenueDisabledError(Exception):
        """Raised when a venue or its domain is disabled."""

    class ModeBlockedError(Exception):
        """Raised when the venue mode does not allow trading."""

    def __init__(self, configs: Optional[List[VenueConfig]] = None):
        self._configs: Dict[str, VenueConfig] = {}
        self._disabled_domains: Set[str] = set()
        for cfg in (configs or _DEFAULT_CONFIGS):
            self._configs[cfg.venue] = cfg

    # ── Venue config access ──────────────────────────────────────────

    def get_config(self, venue: str) -> Optional[VenueConfig]:
        return self._configs.get(venue)

    def list_venues(self) -> List[str]:
        return list(self._configs.keys())

    def venues_by_domain(self, domain: str) -> List[VenueConfig]:
        return [c for c in self._configs.values() if c.domain == domain]

    # ── Mode control ─────────────────────────────────────────────────

    def set_venue_mode(self, venue: str, mode: TradingMode) -> None:
        cfg = self._configs.get(venue)
        if not cfg:
            raise ValueError(f"Unknown venue: {venue}")
        old = cfg.mode
        cfg.mode = mode
        logger.info(f"Venue {venue} mode: {old.value} -> {mode.value}")

    def enable_venue(self, venue: str) -> None:
        cfg = self._configs.get(venue)
        if cfg:
            cfg.enabled = True
            logger.info(f"Venue {venue} enabled")

    def disable_venue(self, venue: str) -> None:
        cfg = self._configs.get(venue)
        if cfg:
            cfg.enabled = False
            logger.info(f"Venue {venue} disabled")

    def enable_domain(self, domain: str) -> None:
        self._disabled_domains.discard(domain)
        logger.info(f"Domain {domain} enabled")

    def disable_domain(self, domain: str) -> None:
        self._disabled_domains.add(domain)
        logger.info(f"Domain {domain} disabled")

    def is_domain_enabled(self, domain: str) -> bool:
        return domain not in self._disabled_domains

    # ── Checks ───────────────────────────────────────────────────────

    def check_can_trade(self, venue: str) -> None:
        """Raise if venue is disabled, domain is disabled, or mode is SIM."""
        cfg = self._configs.get(venue)
        if not cfg:
            raise self.VenueDisabledError(f"Unknown venue: {venue}")
        if not cfg.enabled:
            raise self.VenueDisabledError(f"Venue {venue} is disabled.")
        if cfg.domain in self._disabled_domains:
            raise self.VenueDisabledError(
                f"Domain '{cfg.domain}' is disabled. Venue {venue} cannot trade."
            )
        if cfg.mode == TradingMode.SIM:
            raise self.ModeBlockedError(
                f"Venue {venue} is in SIM mode. Switch to PAPER or LIVE."
            )

    def should_simulate(self, venue: str) -> bool:
        """Return True if fills should be simulated for this venue."""
        cfg = self._configs.get(venue)
        if not cfg:
            return True
        return cfg.mode in (TradingMode.SIM, TradingMode.PAPER)

    # ── Summary ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        return {
            "disabled_domains": sorted(self._disabled_domains),
            "venues": [c.to_dict() for c in self._configs.values()],
        }


# Module-level singleton
_manager: Optional[ModeManager] = None


def get_mode_manager() -> ModeManager:
    global _manager
    if _manager is None:
        _manager = ModeManager()
        # Log Kalshi mode so operators can verify the pipeline at startup.
        _k = _manager.get_config("kalshi")
        if _k is not None:
            if _k.mode == TradingMode.LIVE:
                logger.info(
                    "MERID_PIPELINE_MODE: Kalshi venue initialised in LIVE mode "
                    "(KALSHI_ENV=live). Real-money orders will be submitted via unified pipeline."
                )
            else:
                logger.warning(
                    "MERID_PIPELINE_MODE: Kalshi venue is in %s mode — "
                    "unified pipeline trades will be SIMULATED. "
                    "Set KALSHI_ENV=live for production Kalshi trading.",
                    _k.mode.value.upper(),
                )
    return _manager
