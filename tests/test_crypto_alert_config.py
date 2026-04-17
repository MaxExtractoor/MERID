"""Tests for CryptoAlertConfig threshold accessors and _default fallback chain."""
import pytest

from config.crypto_alert_config import CryptoAlertConfig


class TestCryptoAlertConfig:
    def test_known_symbol_and_frequency_volatility(self):
        cfg = CryptoAlertConfig()
        assert cfg.volatility_threshold("BTC", "15m") == 0.15

    def test_unknown_frequency_falls_back_to_symbol_default(self):
        cfg = CryptoAlertConfig()
        # BTC has "_default": 0.25 in its freq map
        assert cfg.volatility_threshold("BTC", "unknown_freq") == 0.25

    def test_unknown_symbol_falls_back_to_global_default(self):
        cfg = CryptoAlertConfig()
        # "_default": {"_default": 0.25} in the top-level dict
        assert cfg.volatility_threshold("UNKNOWN", "15m") == 0.25

    def test_volume_threshold_known(self):
        cfg = CryptoAlertConfig()
        assert cfg.volume_threshold("ETH", "hourly") == 800

    def test_volume_threshold_unknown_symbol(self):
        cfg = CryptoAlertConfig()
        # Falls back to _default._default = 1000
        assert cfg.volume_threshold("ZZZCOIN", "15m") == 1000

    def test_min_volume_for_fifty_fifty_known(self):
        cfg = CryptoAlertConfig()
        assert cfg.min_volume_for_fifty_fifty("BTC", "15m") == 100

    def test_fifty_low_high(self):
        cfg = CryptoAlertConfig()
        assert cfg.fifty_low("BTC") == 0.45
        assert cfg.fifty_high("BTC") == 0.55

    def test_enabled_flag_default_true(self):
        cfg = CryptoAlertConfig()
        assert cfg.ENABLED is True

    def test_supported_symbols_default(self):
        cfg = CryptoAlertConfig()
        assert "BTC" in cfg.SUPPORTED_SYMBOLS
        assert "DOGE" in cfg.SUPPORTED_SYMBOLS
