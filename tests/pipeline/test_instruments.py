"""Tests for merid/pipeline/instruments.py — InstrumentRegistry and dynamic crypto seeding."""
import threading
from typing import List

import pytest

from merid.pipeline.instruments import (
    Instrument,
    InstrumentRegistry,
    build_default_registry,
    _build_crypto_instruments,
)


# ── Instrument dataclass ──────────────────────────────────────────────

class TestInstrument:
    def test_native_returns_venue_symbol(self):
        inst = Instrument(
            merid_symbol="BTC-USD",
            domain="crypto",
            venue_symbols={"binance": "BTCUSDT", "coinbase": "BTC-USD"},
        )
        assert inst.native("binance") == "BTCUSDT"
        assert inst.native("coinbase") == "BTC-USD"
        assert inst.native("missing") is None

    def test_venues_lists_all_mapped(self):
        inst = Instrument(
            merid_symbol="ETH-USD",
            domain="crypto",
            venue_symbols={"binance": "ETHUSDT", "kraken": "XETHZUSD"},
        )
        assert set(inst.venues()) == {"binance", "kraken"}

    def test_is_allowed_default_true(self):
        inst = Instrument(merid_symbol="BTC-USD", domain="crypto")
        assert inst.is_allowed("any_venue") is True

    def test_is_allowed_blocked_venue(self):
        inst = Instrument(
            merid_symbol="PM:KXBT-25FEB",
            domain="prediction",
            compliance_flags={"polymarket": False},
        )
        assert inst.is_allowed("polymarket") is False
        assert inst.is_allowed("kalshi") is True

    def test_to_dict_structure(self):
        inst = Instrument(
            merid_symbol="BTC-USD",
            domain="crypto",
            display_name="Bitcoin",
            venue_symbols={"binance": "BTCUSDT"},
            tags=["tier1"],
        )
        d = inst.to_dict()
        assert d["merid_symbol"] == "BTC-USD"
        assert d["domain"] == "crypto"
        assert "tier1" in d["tags"]


# ── InstrumentRegistry CRUD ───────────────────────────────────────────

class TestInstrumentRegistry:
    def _reg(self) -> InstrumentRegistry:
        return InstrumentRegistry()

    def test_register_and_get(self):
        reg = self._reg()
        inst = Instrument("BTC-USD", "crypto", venue_symbols={"binance": "BTCUSDT"})
        reg.register(inst)
        assert reg.get("BTC-USD") is inst

    def test_get_missing_returns_none(self):
        assert self._reg().get("GHOST-USD") is None

    def test_resolve(self):
        reg = self._reg()
        reg.register(Instrument("ETH-USD", "crypto", venue_symbols={"kraken": "XETHZUSD"}))
        assert reg.resolve("ETH-USD", "kraken") == "XETHZUSD"
        assert reg.resolve("ETH-USD", "missing") is None
        assert reg.resolve("GHOST", "kraken") is None

    def test_reverse_lookup(self):
        reg = self._reg()
        reg.register(Instrument("BTC-USD", "crypto", venue_symbols={"binance": "BTCUSDT"}))
        assert reg.reverse_lookup("binance", "BTCUSDT") == "BTC-USD"
        assert reg.reverse_lookup("binance", "ETHUSDT") is None
        assert reg.reverse_lookup("unknown", "BTCUSDT") is None

    def test_by_domain(self):
        reg = self._reg()
        reg.register(Instrument("BTC-USD", "crypto"))
        reg.register(Instrument("AAPL", "equity"))
        crypto = reg.by_domain("crypto")
        assert len(crypto) == 1
        assert crypto[0].merid_symbol == "BTC-USD"

    def test_by_venue(self):
        reg = self._reg()
        reg.register(Instrument("BTC-USD", "crypto", venue_symbols={"binance": "BTCUSDT"}))
        reg.register(Instrument("ETH-USD", "crypto", venue_symbols={"coinbase": "ETH-USD"}))
        assert len(reg.by_venue("binance")) == 1
        assert len(reg.by_venue("coinbase")) == 1

    def test_all_symbols(self):
        reg = self._reg()
        reg.register(Instrument("BTC-USD", "crypto"))
        reg.register(Instrument("AAPL", "equity"))
        assert set(reg.all_symbols()) == {"BTC-USD", "AAPL"}

    def test_check_compliance_unregistered_false(self):
        assert self._reg().check_compliance("GHOST", "binance") is False

    def test_summary_structure(self):
        reg = self._reg()
        reg.register(Instrument("BTC-USD", "crypto", venue_symbols={"binance": "BTCUSDT"}))
        reg.register(Instrument("AAPL", "equity", venue_symbols={"alpaca": "AAPL"}))
        s = reg.summary()
        assert s["total_instruments"] == 2
        assert s["domains"]["crypto"] == 1
        assert "binance" in s["venues"]

    def test_register_overwrites_existing(self):
        reg = self._reg()
        reg.register(Instrument("BTC-USD", "crypto", display_name="old"))
        reg.register(Instrument("BTC-USD", "crypto", display_name="new"))
        assert reg.get("BTC-USD").display_name == "new"


# ── Dynamic crypto seeding from asset universe ─────────────────────────

class TestBuildCryptoInstruments:
    def test_builds_instruments_from_universe(self):
        reg = InstrumentRegistry()
        _build_crypto_instruments(reg)
        crypto = reg.by_domain("crypto")
        assert len(crypto) >= 30, f"Expected ≥30 crypto instruments, got {len(crypto)}"

    def test_btc_registered_with_multi_venue(self):
        reg = InstrumentRegistry()
        _build_crypto_instruments(reg)
        btc = reg.get("BTC-USD")
        assert btc is not None
        assert btc.domain == "crypto"
        assert reg.resolve("BTC-USD", "binance") == "BTCUSDT"
        assert reg.resolve("BTC-USD", "coinbase") == "BTC-USD"

    def test_btc_has_tier1_tag(self):
        reg = InstrumentRegistry()
        _build_crypto_instruments(reg)
        btc = reg.get("BTC-USD")
        assert "tier1" in btc.tags

    def test_btc_has_perp_and_arb_tags(self):
        reg = InstrumentRegistry()
        _build_crypto_instruments(reg)
        btc = reg.get("BTC-USD")
        assert "has_perp" in btc.tags
        assert "arb_eligible" in btc.tags

    def test_low_signal_asset_has_signal_low_tag(self):
        reg = InstrumentRegistry()
        _build_crypto_instruments(reg)
        algo = reg.get("ALGO-USD")
        if algo:  # ALGO exists in universe with signal_quality='low'
            assert "signal_low" in algo.tags

    def test_no_perp_aliases_in_registry(self):
        reg = InstrumentRegistry()
        _build_crypto_instruments(reg)
        for sym in reg.all_symbols():
            assert ":" not in sym, f"Perp alias {sym!r} leaked into registry"

    def test_no_stablecoins_in_registry(self):
        reg = InstrumentRegistry()
        _build_crypto_instruments(reg)
        all_syms = {inst.merid_symbol for inst in reg.by_domain("crypto")}
        for stable in ("USDT-USD", "USDC-USD", "DAI-USD"):
            assert stable not in all_syms, f"Stablecoin {stable} should not be in crypto registry"

    def test_bnbus_alias_skipped(self):
        reg = InstrumentRegistry()
        _build_crypto_instruments(reg)
        assert reg.get("BNB-USD") is not None  # canonical BNB registered
        assert "BNBUS" not in reg.all_symbols()  # alias excluded

    def test_kraken_legacy_mapping_for_btc(self):
        reg = InstrumentRegistry()
        _build_crypto_instruments(reg)
        assert reg.resolve("BTC-USD", "kraken") == "XXBTZUSD"

    def test_kraken_generic_fallback_for_sol(self):
        reg = InstrumentRegistry()
        _build_crypto_instruments(reg)
        assert reg.resolve("SOL-USD", "kraken") == "SOLUSDT"


# ── build_default_registry ────────────────────────────────────────────

class TestBuildDefaultRegistry:
    def test_has_crypto_equity_prediction_domains(self):
        reg = build_default_registry()
        s = reg.summary()
        assert "crypto" in s["domains"]
        assert "equity" in s["domains"]
        assert "prediction" in s["domains"]

    def test_equity_aapl_registered(self):
        reg = build_default_registry()
        aapl = reg.get("AAPL")
        assert aapl is not None
        assert aapl.domain == "equity"
        assert reg.resolve("AAPL", "alpaca") == "AAPL"

    def test_prediction_market_seed_registered(self):
        reg = build_default_registry()
        kalshi = reg.get("PM:KXBT-25FEB-50K")
        assert kalshi is not None
        assert kalshi.domain == "prediction"
        assert kalshi.is_allowed("polymarket") is False

    def test_crypto_count_at_least_30(self):
        reg = build_default_registry()
        assert reg.summary()["domains"]["crypto"] >= 30


# ── Singleton double-checked locking ────────────────────────────────

class TestGetInstrumentRegistrySingleton:
    def test_returns_same_instance(self):
        from merid.pipeline.instruments import get_instrument_registry
        r1 = get_instrument_registry()
        r2 = get_instrument_registry()
        assert r1 is r2

    def test_thread_safe_concurrent_access(self):
        """Multiple threads must receive the same singleton instance."""
        from merid.pipeline import instruments as _mod
        import importlib

        # Force reset for isolation
        _mod._registry = None

        results: List[InstrumentRegistry] = []
        errors: List[Exception] = []

        def _get():
            try:
                results.append(_mod.get_instrument_registry())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_get) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        first = results[0]
        assert all(r is first for r in results)
