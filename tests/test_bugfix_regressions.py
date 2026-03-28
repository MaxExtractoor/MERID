"""Regression tests for bugfixes: matching engine DOMAIN_CONFIGS import
and swarm/performance.py _coerce_dt naive/aware datetime mismatch.
"""

import pytest
from datetime import datetime, timezone, timedelta


# ======================================================================
# §1 init_matching_engines — DOMAIN_CONFIGS import regression
# ======================================================================

class TestInitMatchingEngines:
    """Verify init_matching_engines() no longer raises NameError."""

    def test_import_does_not_raise(self):
        """init_matching_engines must not raise NameError on DOMAIN_CONFIGS."""
        from merid.matching_engine import init_matching_engines
        # Should not raise NameError: name 'DOMAIN_CONFIGS' is not defined
        engines = init_matching_engines()
        assert isinstance(engines, dict)

    def test_returns_dict_of_engines(self):
        from merid.matching_engine import init_matching_engines, MatchingEngine
        engines = init_matching_engines()
        for name, engine in engines.items():
            assert isinstance(name, str)
            assert isinstance(engine, MatchingEngine)

    def test_prediction_engine_present(self):
        """Paper config enables a prediction matching engine."""
        from merid.matching_engine import init_matching_engines
        engines = init_matching_engines()
        assert "prediction" in engines, (
            "Expected 'prediction' domain engine from paper_config"
        )

    def test_engine_has_correct_domain(self):
        from merid.matching_engine import init_matching_engines
        engines = init_matching_engines()
        for name, engine in engines.items():
            assert engine.domain == name

    def test_from_config_classmethod(self):
        """MatchingEngine.from_config also imports DOMAIN_CONFIGS correctly."""
        from merid.matching_engine import MatchingEngine
        engine = MatchingEngine.from_config("prediction")
        assert engine.domain == "prediction"


# ======================================================================
# §2 _coerce_dt — naive/aware datetime fix
# ======================================================================

class TestCoerceDt:
    """Verify _coerce_dt always returns timezone-aware datetimes."""

    def test_z_suffix_returns_aware(self):
        """ISO string with Z suffix must produce UTC-aware datetime."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("2026-02-14T20:00:00Z")
        assert dt.tzinfo is not None
        assert dt.year == 2026
        assert dt.month == 2
        assert dt.day == 14
        assert dt.hour == 20

    def test_plus_zero_offset_returns_aware(self):
        """ISO string with +00:00 must produce UTC-aware datetime."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("2026-02-14T20:00:00+00:00")
        assert dt.tzinfo is not None

    def test_naive_iso_string_gets_utc(self):
        """ISO string without timezone must get UTC attached."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("2026-02-14T20:00:00")
        assert dt.tzinfo is not None
        assert dt.tzinfo == timezone.utc

    def test_non_utc_offset_preserved(self):
        """ISO string with non-UTC offset should preserve that offset."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("2026-02-14T15:00:00-05:00")
        assert dt.tzinfo is not None
        # Should be 20:00 UTC
        utc_dt = dt.astimezone(timezone.utc)
        assert utc_dt.hour == 20

    def test_fallback_on_garbage_returns_aware(self):
        """Invalid string must fall back to aware UTC datetime."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("not-a-date")
        assert dt.tzinfo is not None
        # Should be close to now
        diff = abs((datetime.now(timezone.utc) - dt).total_seconds())
        assert diff < 5

    def test_subtraction_from_aware_datetime_succeeds(self):
        """Core regression: subtracting _coerce_dt result from aware now must not raise."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("2026-02-14T20:00:00Z")
        now = datetime.now(timezone.utc)
        # This was the exact operation that raised TypeError before the fix
        diff = now - dt
        assert isinstance(diff, timedelta)

    def test_subtraction_from_naive_iso_succeeds(self):
        """Naive ISO input must also be subtractable from aware now."""
        from swarm.performance import _coerce_dt
        dt = _coerce_dt("2026-02-14T20:00:00")
        now = datetime.now(timezone.utc)
        diff = now - dt
        assert isinstance(diff, timedelta)

    def test_z_and_plus_zero_are_equal(self):
        """Z suffix and +00:00 for same time must produce equal datetimes."""
        from swarm.performance import _coerce_dt
        dt_z = _coerce_dt("2026-02-14T20:00:00Z")
        dt_plus = _coerce_dt("2026-02-14T20:00:00+00:00")
        assert dt_z == dt_plus


# ======================================================================
# §3 VenueConfig — base_url keyword argument regression
# ======================================================================

class TestVenueConfigBaseUrl:
    """Regression: VenueConfig.__init__() must accept base_url keyword argument.

    Traceback was: TypeError: VenueConfig.__init__() got an unexpected keyword
    argument 'base_url', originating in load_agent_grid_config.
    """

    def test_venue_config_accepts_base_url(self):
        """VenueConfig must accept base_url as a constructor keyword argument."""
        from merid.prediction.agent_grid_config import VenueConfig
        from decimal import Decimal
        # Exact same call pattern as load_agent_grid_config for Kalshi
        vc = VenueConfig(
            name="kalshi",
            base_url="https://trading-api.kalshi.com/trade-api/v2",
            use_demo=False,
            max_notional_per_expiry_usd=Decimal("5000"),
            max_open_markets_per_asset=20,
        )
        assert vc.base_url == "https://trading-api.kalshi.com/trade-api/v2"

    def test_venue_config_base_url_default(self):
        """VenueConfig.base_url default must be the production trading API URL."""
        from merid.prediction.agent_grid_config import VenueConfig
        vc = VenueConfig()
        assert vc.base_url == "https://trading-api.kalshi.com/trade-api/v2"

    def test_venue_config_base_url_overridable(self):
        """VenueConfig.base_url must be overridable to the demo URL."""
        from merid.prediction.agent_grid_config import VenueConfig
        demo_url = "https://demo-api.kalshi.com/trade-api/v2"
        vc = VenueConfig(base_url=demo_url)
        assert vc.base_url == demo_url

    def test_load_agent_grid_config_uses_base_url(self, tmp_path):
        """load_agent_grid_config must parse base_url from YAML without TypeError."""
        import yaml
        from merid.prediction.agent_grid_config import load_agent_grid_config

        cfg_data = {
            "venue": {
                "name": "kalshi",
                "base_url": "https://trading-api.kalshi.com/trade-api/v2",
                "use_demo": False,
                "max_notional_per_expiry_usd": 5000,
                "max_open_markets_per_asset": 20,
            },
            "session": {
                "maintenance_day": 3,
                "maintenance_start_et": "03:00",
                "maintenance_end_et": "05:00",
            },
            "agents": [],
            "portfolio_risk": {},
        }

        cfg_file = tmp_path / "test_kalshi_grid.yaml"
        cfg_file.write_text(yaml.dump(cfg_data), encoding="utf-8")

        # Must not raise TypeError
        config = load_agent_grid_config(path=str(cfg_file))
        assert config.venue.base_url == "https://trading-api.kalshi.com/trade-api/v2"
        assert config.venue.name == "kalshi"


# ======================================================================
# §4 MarketCandidate — best_no_bid / best_yes_bid attribute regression
# ======================================================================

class TestMarketCandidateBestNoBid:
    """Regression: MarketCandidate must carry best_yes_bid, best_yes_ask,
    best_no_bid, best_no_ask as Optional[float] fields.

    AttributeError: 'MarketCandidate' object has no attribute 'best_no_bid'
    would fire in _compute_edge when these fields are absent.
    """

    def test_market_candidate_has_best_no_bid(self):
        """MarketCandidate must accept best_no_bid as a constructor kwarg."""
        from merid.event_venues.kalshi.market_filter import MarketCandidate
        c = MarketCandidate(
            ticker="KXBTC-15M-26MAR25-T95000",
            underlying="BTC",
            timeframe="15m",
            best_bid_cents=54,
            best_ask_cents=56,
            mid_price_cents=55,
            best_yes_bid=0.54,
            best_yes_ask=0.56,
            best_no_bid=0.44,
            best_no_ask=0.46,
        )
        assert c.best_no_bid == 0.44

    def test_market_candidate_best_fields_default_to_none(self):
        """All four best_yes/no fields must default to None."""
        from merid.event_venues.kalshi.market_filter import MarketCandidate
        c = MarketCandidate(ticker="X", underlying="BTC", timeframe="15m")
        assert c.best_yes_bid is None
        assert c.best_yes_ask is None
        assert c.best_no_bid is None
        assert c.best_no_ask is None

    def test_trading_candidate_propagates_best_no_bid(self):
        """TradingCandidate.from_candidate must copy best_no_bid from base."""
        from merid.event_venues.kalshi.market_filter import MarketCandidate
        from merid.trading.kalshi_continuous_trader import TradingCandidate
        base = MarketCandidate(
            ticker="KXBTC-15M-26MAR25-T95000",
            underlying="BTC",
            timeframe="15m",
            best_yes_bid=0.54,
            best_yes_ask=0.56,
            best_no_bid=0.44,
            best_no_ask=0.46,
        )
        tc = TradingCandidate.from_candidate(base)
        assert tc.best_yes_bid == 0.54
        assert tc.best_yes_ask == 0.56
        assert tc.best_no_bid == 0.44
        assert tc.best_no_ask == 0.46

    def test_compute_edge_style_no_attribute_error(self):
        """Accessing best_no_bid (as _compute_edge does) must not raise AttributeError."""
        from merid.event_venues.kalshi.market_filter import MarketCandidate

        c = MarketCandidate(
            ticker="KXBTC-15M-26MAR25-T95000",
            underlying="BTC",
            timeframe="15m",
            best_bid_cents=54,
            best_ask_cents=56,
            mid_price_cents=55,
            best_yes_bid=0.54,
            best_yes_ask=0.56,
            best_no_bid=0.44,
            best_no_ask=0.46,
        )

        # Simulate the _compute_edge access pattern that caused the AttributeError
        edge = None
        if c.best_no_bid is not None:
            # In a Kalshi binary market: implied_yes_ask ≈ 1 - best_no_bid
            implied_yes_ask = 1.0 - c.best_no_bid
            if c.best_yes_bid is not None:
                edge = implied_yes_ask - c.best_yes_bid

        assert edge is not None
        assert isinstance(edge, float)
        assert abs(edge - (1.0 - 0.44 - 0.54)) < 1e-9  # 0.02

    def test_to_dict_includes_best_no_bid(self):
        """MarketCandidate.to_dict() must include all four best_yes/no fields."""
        from merid.event_venues.kalshi.market_filter import MarketCandidate
        c = MarketCandidate(
            ticker="X", underlying="BTC", timeframe="15m",
            best_yes_bid=0.54, best_yes_ask=0.56,
            best_no_bid=0.44, best_no_ask=0.46,
        )
        d = c.to_dict()
        assert "best_yes_bid" in d
        assert "best_yes_ask" in d
        assert "best_no_bid" in d
        assert "best_no_ask" in d
        assert d["best_no_bid"] == 0.44
