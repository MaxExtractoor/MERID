"""CI Test: Settlement Guard Per-Timeframe

P0-003 Audit CI Test — Validates that settlement guards are timeframe-specific
and aligned with Kalshi/CF Benchmarks methodology.

Run: pytest tests/ci/test_settlement_guard_timeframes.py -v
"""
from __future__ import annotations

import pytest

from merid.event_venues.kalshi.cfb_settlement import (
    get_settlement_guard_seconds,
    _get_settlement_guard_seconds,
    _SETTLEMENT_GUARD_BY_TIMEFRAME,
    SETTLEMENT_BY_KEY,
)


class TestSettlementGuardPerTimeframe:
    """Validate per-timeframe settlement guard values."""

    def test_15m_guard_is_tightest(self) -> None:
        """15m contracts should have the tightest guard (30s)."""
        guard = _get_settlement_guard_seconds("15m")
        assert guard == 30, f"Expected 30s for 15m, got {guard}s"

    def test_1h_guard_is_standard(self) -> None:
        """1h contracts should have standard guard (60s)."""
        guard = _get_settlement_guard_seconds("1h")
        assert guard == 60, f"Expected 60s for 1h, got {guard}s"

    def test_daily_guard_is_extended(self) -> None:
        """Daily contracts should have extended guard (300s = 5min)."""
        guard = _get_settlement_guard_seconds("daily")
        assert guard == 300, f"Expected 300s for daily, got {guard}s"

    def test_weekly_guard_is_extended(self) -> None:
        """Weekly contracts should have extended guard (300s = 5min)."""
        guard = _get_settlement_guard_seconds("weekly")
        assert guard == 300, f"Expected 300s for weekly, got {guard}s"

    def test_monthly_guard_is_extended(self) -> None:
        """Monthly contracts should have extended guard (300s = 5min)."""
        guard = _get_settlement_guard_seconds("monthly")
        assert guard == 300, f"Expected 300s for monthly, got {guard}s"

    def test_annual_guard_is_extended(self) -> None:
        """Annual contracts should have extended guard (300s = 5min)."""
        guard = _get_settlement_guard_seconds("annual")
        assert guard == 300, f"Expected 300s for annual, got {guard}s"

    def test_case_insensitive_lookup(self) -> None:
        """Timeframe lookup should be case-insensitive."""
        assert _get_settlement_guard_seconds("15M") == 30
        assert _get_settlement_guard_seconds("1H") == 60
        assert _get_settlement_guard_seconds("DAILY") == 300

    def test_unknown_timeframe_fallback(self) -> None:
        """Unknown timeframes should fallback to 60s."""
        guard = _get_settlement_guard_seconds("unknown_tf")
        assert guard == 60, f"Expected 60s fallback, got {guard}s"


class TestSettlementGuardIntegration:
    """Validate settlement guard integration with asset/timeframe params."""

    def test_btc_15m_guard(self) -> None:
        """BTC 15m should use 30s guard."""
        guard = get_settlement_guard_seconds("BTC", "15m")
        assert guard == 30, f"BTC 15m guard should be 30s, got {guard}s"

    def test_btc_1h_guard(self) -> None:
        """BTC 1h should use 60s guard."""
        guard = get_settlement_guard_seconds("BTC", "1h")
        assert guard == 60, f"BTC 1h guard should be 60s, got {guard}s"

    def test_btc_daily_guard(self) -> None:
        """BTC daily should use 300s guard."""
        guard = get_settlement_guard_seconds("BTC", "daily")
        assert guard == 300, f"BTC daily guard should be 300s, got {guard}s"

    def test_eth_15m_guard(self) -> None:
        """ETH 15m should use 30s guard."""
        guard = get_settlement_guard_seconds("ETH", "15m")
        assert guard == 30, f"ETH 15m guard should be 30s, got {guard}s"

    def test_all_crypto_assets_use_same_timeframe_guards(self) -> None:
        """All crypto assets should use consistent timeframe guards."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        timeframes = ["15m", "1h", "daily", "weekly"]
        expected_guards = {"15m": 30, "1h": 60, "daily": 300, "weekly": 300}

        for asset in assets:
            for tf in timeframes:
                guard = get_settlement_guard_seconds(asset, tf)
                expected = expected_guards[tf]
                assert guard == expected, \
                    f"{asset} {tf} guard mismatch: expected {expected}s, got {guard}s"


class TestSettlementParamsAlignment:
    """Validate settlement params have correct per-timeframe guards."""

    def test_all_settlement_params_have_guards(self) -> None:
        """All SETTLEMENT_BY_KEY entries should have settlement_guard_seconds."""
        for (asset, tf), params in SETTLEMENT_BY_KEY.items():
            assert params.settlement_guard_seconds > 0, \
                f"{asset} {tf} missing settlement_guard_seconds"

    def test_15m_params_use_30s_guard(self) -> None:
        """All 15m settlement params should use 30s guard."""
        for (asset, tf), params in SETTLEMENT_BY_KEY.items():
            if tf == "15m":
                assert params.settlement_guard_seconds == 30, \
                    f"{asset} 15m should use 30s guard, got {params.settlement_guard_seconds}s"

    def test_1h_params_use_60s_guard(self) -> None:
        """All 1h settlement params should use 60s guard."""
        for (asset, tf), params in SETTLEMENT_BY_KEY.items():
            if tf == "1h":
                assert params.settlement_guard_seconds == 60, \
                    f"{asset} 1h should use 60s guard, got {params.settlement_guard_seconds}s"

    def test_daily_params_use_300s_guard(self) -> None:
        """All daily settlement params should use 300s guard."""
        for (asset, tf), params in SETTLEMENT_BY_KEY.items():
            if tf == "daily":
                assert params.settlement_guard_seconds == 300, \
                    f"{asset} daily should use 300s guard, got {params.settlement_guard_seconds}s"


class TestSettlementGuardOrdering:
    """Validate guard values follow expected ordering (shorter timeframes = tighter guards)."""

    def test_guard_ordering(self) -> None:
        """15m < 1h < daily/weekly/monthly/annual in guard duration."""
        guard_15m = _get_settlement_guard_seconds("15m")
        guard_1h = _get_settlement_guard_seconds("1h")
        guard_daily = _get_settlement_guard_seconds("daily")
        guard_weekly = _get_settlement_guard_seconds("weekly")

        assert guard_15m < guard_1h, f"15m guard ({guard_15m}s) should be < 1h guard ({guard_1h}s)"
        assert guard_1h < guard_daily, f"1h guard ({guard_1h}s) should be < daily guard ({guard_daily}s)"
        assert guard_daily == guard_weekly, \
            f"daily ({guard_daily}s) and weekly ({guard_weekly}s) guards should be equal"


class TestSettlementGuardDocumentation:
    """Validate settlement guard has proper documentation references."""

    def test_guard_docstring_exists(self) -> None:
        """get_settlement_guard_seconds should have docstring referencing Kalshi/CF docs."""
        docstring = get_settlement_guard_seconds.__doc__
        assert docstring is not None, "Missing docstring"
        assert "Kalshi" in docstring or "CF Benchmarks" in docstring or "60 seconds" in docstring, \
            "Docstring should reference Kalshi/CF methodology"

    def test_settlement_guard_dict_documented(self) -> None:
        """_SETTLEMENT_GUARD_BY_TIMEFRAME should have comment explaining values."""
        # Check module has expected comment
        import merid.event_venues.kalshi.cfb_settlement as mod
        import inspect
        source = inspect.getsource(mod)
        assert "Kalshi docs" in source or "60 seconds" in source or "RTI" in source, \
            "Source should document Kalshi settlement methodology"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
