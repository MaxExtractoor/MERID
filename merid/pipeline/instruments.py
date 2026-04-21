"""InstrumentRegistry — merid_symbol ↔ venue:native_symbol mapping.

Central mapping so swarm agents work with MERID-internal symbols while
adapters handle venue-specific identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import threading

from utils.logger import get_logger

logger = get_logger("merid.pipeline.instruments")


@dataclass
class Instrument:
    """A tradeable instrument across one or more venues."""
    merid_symbol: str              # e.g. "BTC-USD", "FED-25DEC", "AAPL"
    domain: str                    # "prediction", "crypto", "equity"
    display_name: str = ""
    venue_symbols: Dict[str, str] = field(default_factory=dict)  # venue -> native symbol
    tags: List[str] = field(default_factory=list)
    compliance_flags: Dict[str, bool] = field(default_factory=dict)  # venue -> allowed

    def native(self, venue: str) -> Optional[str]:
        """Get venue-native symbol, or None if not mapped."""
        return self.venue_symbols.get(venue)

    def venues(self) -> List[str]:
        """List venues this instrument is available on."""
        return list(self.venue_symbols.keys())

    def is_allowed(self, venue: str) -> bool:
        """Check if trading this instrument on this venue is allowed."""
        return self.compliance_flags.get(venue, True)

    def to_dict(self) -> dict:
        return {
            "merid_symbol": self.merid_symbol,
            "domain": self.domain,
            "display_name": self.display_name,
            "venue_symbols": self.venue_symbols,
            "tags": self.tags,
            "compliance_flags": self.compliance_flags,
        }


class InstrumentRegistry:
    """Central instrument registry for all MERID-supported instruments.

    Usage::

        reg = InstrumentRegistry()
        reg.register(Instrument(
            merid_symbol="BTC-USD",
            domain="crypto",
            venue_symbols={"binance": "BTCUSDT", "coinbase": "BTC-USD", "kraken": "XXBTZUSD"},
        ))
        native = reg.resolve("BTC-USD", "binance")  # "BTCUSDT"
        merid = reg.reverse_lookup("binance", "BTCUSDT")  # "BTC-USD"
    """

    def __init__(self) -> None:
        self._instruments: Dict[str, Instrument] = {}
        self._reverse: Dict[str, Dict[str, str]] = {}  # venue -> {native -> merid}

    def register(self, instrument: Instrument) -> None:
        """Register or update an instrument."""
        self._instruments[instrument.merid_symbol] = instrument
        for venue, native in instrument.venue_symbols.items():
            if venue not in self._reverse:
                self._reverse[venue] = {}
            self._reverse[venue][native] = instrument.merid_symbol

    def get(self, merid_symbol: str) -> Optional[Instrument]:
        return self._instruments.get(merid_symbol)

    def resolve(self, merid_symbol: str, venue: str) -> Optional[str]:
        """Resolve merid_symbol to venue-native symbol."""
        inst = self._instruments.get(merid_symbol)
        if inst:
            return inst.native(venue)
        return None

    def reverse_lookup(self, venue: str, native_symbol: str) -> Optional[str]:
        """Reverse-lookup: venue + native_symbol → merid_symbol."""
        venue_map = self._reverse.get(venue, {})
        return venue_map.get(native_symbol)

    def by_domain(self, domain: str) -> List[Instrument]:
        return [i for i in self._instruments.values() if i.domain == domain]

    def by_venue(self, venue: str) -> List[Instrument]:
        return [i for i in self._instruments.values() if venue in i.venue_symbols]

    def all_symbols(self) -> List[str]:
        return list(self._instruments.keys())

    def venues_for(self, merid_symbol: str) -> List[str]:
        inst = self._instruments.get(merid_symbol)
        return inst.venues() if inst else []

    def check_compliance(self, merid_symbol: str, venue: str) -> bool:
        """Check if trading merid_symbol on venue is compliant."""
        inst = self._instruments.get(merid_symbol)
        if not inst:
            return False
        return inst.is_allowed(venue)

    def summary(self) -> dict:
        domains: Dict[str, int] = {}
        venues: Set[str] = set()
        for inst in self._instruments.values():
            domains[inst.domain] = domains.get(inst.domain, 0) + 1
            venues.update(inst.venue_symbols.keys())
        return {
            "total_instruments": len(self._instruments),
            "domains": domains,
            "venues": sorted(venues),
        }


# ── Default instruments ──────────────────────────────────────────────

_KRAKEN_LEGACY: Dict[str, str] = {
    "BTC": "XXBTZUSD", "ETH": "XETHZUSD",
    "LTC": "XLTCZUSD", "XMR": "XXMRZUSD",
}
_SKIP_ASSET_KEYS = {"BNBUS"}  # duplicate spot alias — BNB is already registered


def _build_crypto_instruments(reg: InstrumentRegistry) -> None:
    """Populate registry with all top-50 crypto instruments from the asset universe."""
    from data.asset_universe import ASSET_UNIVERSE
    for key, asset in ASSET_UNIVERSE.items():
        if key in _SKIP_ASSET_KEYS:
            continue
        if "/" not in asset.symbol or ":" in asset.symbol:
            continue  # skip perp aliases (BTC/USD:USD format)
        if asset.category == "Stable":
            continue
        base = asset.symbol.split("/")[0]
        merid_sym = f"{base}-USD"
        if reg.get(merid_sym):
            continue  # already registered (e.g. from duplicate key)
        kraken_sym = _KRAKEN_LEGACY.get(base, f"{base}USDT")
        tags = [
            "tier1" if asset.liquidity_tier == 1 else
            "tier2" if asset.liquidity_tier == 2 else "tier3"
        ]
        if asset.has_perp:
            tags.append("has_perp")
        if asset.arb_eligible:
            tags.append("arb_eligible")
        if asset.signal_quality != "medium":
            tags.append(f"signal_{asset.signal_quality}")
        reg.register(Instrument(
            merid_symbol=merid_sym,
            domain="crypto",
            display_name=asset.name,
            venue_symbols={
                "binance":  f"{base}USDT",
                "coinbase": f"{base}-USD",
                "kraken":   kraken_sym,
                "okx":      f"{base}-USDT",
                "bybit":    f"{base}USDT",
            },
            tags=tags,
        ))


def build_default_registry() -> InstrumentRegistry:
    """Build a registry with common instruments pre-loaded."""
    reg = InstrumentRegistry()

    # Crypto — dynamically built from top-50 asset universe
    _build_crypto_instruments(reg)

    # Equities (Alpaca + IBKR)
    for sym in ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "SPY", "QQQ"]:
        reg.register(Instrument(
            merid_symbol=sym,
            domain="equity",
            display_name=sym,
            venue_symbols={"alpaca": sym, "ibkr": sym},
        ))

    # Prediction markets (Kalshi only)
    # These are dynamically populated from Kalshi API, but we seed a few
    for ticker in ["FED-25DEC-T3.00", "KXBT-25FEB-50K", "INXD-25FEB-6000"]:
        reg.register(Instrument(
            merid_symbol=f"PM:{ticker}",
            domain="prediction",
            display_name=ticker,
            venue_symbols={"kalshi": ticker},
            compliance_flags={"polymarket": False},  # blocked
        ))

    return reg


# Module-level singleton
_registry: Optional[InstrumentRegistry] = None
_registry_lock = threading.Lock()


def get_instrument_registry() -> InstrumentRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = build_default_registry()
    return _registry
