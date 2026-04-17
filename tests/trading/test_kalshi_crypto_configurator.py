"""KalshiCryptoConfigurator — deterministic rules match orchestration prompt."""

from __future__ import annotations

import json

import pytest

from merid.trading.kalshi_crypto_configurator import (
    CRYPTO_ASSETS,
    KALSHI_CRYPTO_CONFIGURATOR_SYSTEM_PROMPT,
    build_kalshi_crypto_scan_config,
    build_kalshi_crypto_scan_config_json,
)


def test_prompt_constant_is_substantial() -> None:
    assert "KalshiCryptoConfigurator" in KALSHI_CRYPTO_CONFIGURATOR_SYSTEM_PROMPT
    assert "0.10" in KALSHI_CRYPTO_CONFIGURATOR_SYSTEM_PROMPT
    assert "3600" in KALSHI_CRYPTO_CONFIGURATOR_SYSTEM_PROMPT


def test_example_multipliers_match_spec_document() -> None:
    mults = {
        "BTC": 1.0,
        "ETH": 1.3,
        "SOL": 2.0,
        "XRP": 1.8,
        "DOGE": 2.4,
    }
    btc_tf = ["15M", "1H", "1D", "1W"]
    cfg = build_kalshi_crypto_scan_config(
        base_width_btc=0.125,
        base_lookback_btc_seconds=900,
        btc_timeframes=btc_tf,
        vol_multipliers=mults,
    )

    assert cfg["BTC"] == {
        "width": 0.125,
        "lookback_seconds": 900,
        "timeframes": btc_tf,
    }
    assert cfg["ETH"]["width"] == pytest.approx(0.1625)
    assert cfg["ETH"]["lookback_seconds"] == 692
    assert cfg["ETH"]["timeframes"] == ["5M", "15M", "1H", "1D"]
    assert cfg["SOL"] == {
        "width": 0.25,
        "lookback_seconds": 450,
        "timeframes": ["1M", "5M", "15M", "1H"],
    }
    assert cfg["XRP"] == {
        "width": 0.225,
        "lookback_seconds": 500,
        "timeframes": ["5M", "15M", "1H", "1D"],
    }
    assert cfg["DOGE"] == {
        "width": 0.30,
        "lookback_seconds": 375,
        "timeframes": ["1M", "5M", "15M", "1H"],
    }

    assert set(cfg.keys()) == set(CRYPTO_ASSETS)


def test_width_clamp_low_and_high() -> None:
    cfg = build_kalshi_crypto_scan_config(
        base_width_btc=0.05,
        base_lookback_btc_seconds=900,
        btc_timeframes=["15M"],
        vol_multipliers={a: 1.0 for a in CRYPTO_ASSETS},
    )
    assert cfg["BTC"]["width"] == 0.10

    cfg2 = build_kalshi_crypto_scan_config(
        base_width_btc=0.20,
        base_lookback_btc_seconds=900,
        btc_timeframes=["15M"],
        vol_multipliers={a: 10.0 for a in CRYPTO_ASSETS},
    )
    assert cfg2["ETH"]["width"] == 0.35


def test_lookback_clamp() -> None:
    cfg = build_kalshi_crypto_scan_config(
        base_width_btc=0.125,
        base_lookback_btc_seconds=30,
        btc_timeframes=["15M"],
        vol_multipliers={a: 1.0 for a in CRYPTO_ASSETS},
    )
    assert cfg["BTC"]["lookback_seconds"] == 60

    cfg2 = build_kalshi_crypto_scan_config(
        base_width_btc=0.125,
        base_lookback_btc_seconds=100_000,
        btc_timeframes=["15M"],
        vol_multipliers={a: 1.0 for a in CRYPTO_ASSETS},
    )
    assert cfg2["BTC"]["lookback_seconds"] == 3600


def test_json_roundtrip_minified() -> None:
    s = build_kalshi_crypto_scan_config_json(
        base_width_btc=0.125,
        base_lookback_btc_seconds=900,
        btc_timeframes=["15M", "1H"],
        vol_multipliers={a: 1.0 for a in CRYPTO_ASSETS},
    )
    assert "\n" not in s or s.startswith("{")
    parsed = json.loads(s)
    assert parsed["BTC"]["lookback_seconds"] == 900


def test_missing_multiplier_raises() -> None:
    with pytest.raises(ValueError, match="missing keys"):
        build_kalshi_crypto_scan_config(
            base_width_btc=0.125,
            base_lookback_btc_seconds=900,
            btc_timeframes=["15M"],
            vol_multipliers={"BTC": 1.0},
        )
