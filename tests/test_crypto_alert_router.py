"""Tests for CryptoAlertRouter — config, tags, snapshot, cooldown, rank, status."""
import time
import pytest

from config.crypto_alert_config import CryptoAlertConfig
from merid.alerts.crypto_alert_router import (
    MarketSnapshot, MarketTag, MarketSelectionItem, compute_tags,
    _rank_snapshots, CryptoAlertRouter,
)


def make_cfg(**kw) -> CryptoAlertConfig:
    return CryptoAlertConfig(**kw)


def make_snap(**overrides) -> MarketSnapshot:
    base = dict(
        symbol="BTC", market_id="KXBTCD-26MAR22", episode_id="KXBTCD",
        frequency="daily", status="active", title="Will BTC close above $87k?",
        volume_24h=6000, p_yes=0.52, spread_cents=2.0, depth_10c=100,
        seconds_to_expiry=3600.0, created_at=time.time() - 7200,
        is_new=False, is_trending=False, volatility_score=0.1, closing_soon=False,
    )
    base.update(overrides)
    return MarketSnapshot(**base)


# ---------------------------------------------------------------------------
# TestCryptoAlertConfig
# ---------------------------------------------------------------------------

class TestCryptoAlertConfig:
    def test_volatility_threshold_known_symbol_and_freq(self):
        cfg = make_cfg()
        val = cfg.volatility_threshold("BTC", "daily")
        assert isinstance(val, float) and val > 0

    def test_volatility_threshold_unknown_symbol_falls_back(self):
        cfg = make_cfg()
        assert isinstance(cfg.volatility_threshold("UNKNOWN", "daily"), float)

    def test_volatility_threshold_unknown_freq_falls_back(self):
        cfg = make_cfg()
        assert isinstance(cfg.volatility_threshold("BTC", "biannual"), float)

    def test_volume_threshold_returns_int(self):
        cfg = make_cfg()
        assert isinstance(cfg.volume_threshold("ETH", "15m"), int)

    def test_fifty_fifty_band_defaults(self):
        cfg = make_cfg()
        assert cfg.fifty_low("BTC") == pytest.approx(0.45)
        assert cfg.fifty_high("BTC") == pytest.approx(0.55)

    def test_min_volume_for_fifty_fifty_no_error(self):
        cfg = make_cfg()
        assert isinstance(cfg.min_volume_for_fifty_fifty("DOGE", "hourly"), int)

    def test_feature_flags_are_bool(self):
        cfg = make_cfg()
        assert isinstance(cfg.ENABLE_TELEGRAM_MARKET_ALERTS, bool)
        assert isinstance(cfg.ENABLE_FIFTY_FIFTY, bool)

    def test_volatility_threshold_symbol_dict_without_default_key(self):
        cfg = make_cfg()
        cfg.VOLATILITY_THRESHOLDS["LTC"] = {"daily": 0.30}
        result = cfg.volatility_threshold("LTC", "15m")
        assert isinstance(result, float) and result > 0


# ---------------------------------------------------------------------------
# TestComputeTags
# ---------------------------------------------------------------------------

class TestComputeTags:
    def test_no_tags_on_baseline_snap(self):
        snap = make_snap(volume_24h=0, p_yes=0.70, volatility_score=0.0)
        assert compute_tags(snap, make_cfg()) == set()

    def test_trending_tag_when_is_trending_true(self):
        snap = make_snap(is_trending=True)
        assert MarketTag.TRENDING in compute_tags(snap, make_cfg())

    def test_volatile_tag_when_score_exceeds_threshold(self):
        cfg = make_cfg()
        threshold = cfg.volatility_threshold("BTC", "daily")
        snap = make_snap(volatility_score=threshold + 0.1)
        assert MarketTag.VOLATILE in compute_tags(snap, cfg)

    def test_volatile_tag_absent_when_score_below_threshold(self):
        cfg = make_cfg()
        threshold = cfg.volatility_threshold("BTC", "daily")
        snap = make_snap(volatility_score=threshold - 0.01)
        assert MarketTag.VOLATILE not in compute_tags(snap, cfg)

    def test_new_tag_when_is_new_true(self):
        assert MarketTag.NEW in compute_tags(make_snap(is_new=True), make_cfg())

    def test_closing_soon_tag_when_flag_true(self):
        assert MarketTag.CLOSING_SOON in compute_tags(make_snap(closing_soon=True), make_cfg())

    def test_high_volume_tag_when_volume_exceeds_threshold(self):
        cfg = make_cfg()
        threshold = cfg.volume_threshold("BTC", "daily")
        snap = make_snap(volume_24h=threshold + 1)
        assert MarketTag.HIGH_VOLUME in compute_tags(snap, cfg)

    def test_fifty_fifty_tag_assigned(self):
        cfg = make_cfg()
        min_vol = cfg.min_volume_for_fifty_fifty("BTC", "daily")
        snap = make_snap(p_yes=0.50, volume_24h=min_vol + 100)
        assert MarketTag.FIFTY_FIFTY in compute_tags(snap, cfg)

    def test_fifty_fifty_suppressed_on_low_volume(self):
        cfg = make_cfg()
        min_vol = cfg.min_volume_for_fifty_fifty("BTC", "daily")
        snap = make_snap(p_yes=0.50, volume_24h=max(0, min_vol - 1))
        assert MarketTag.FIFTY_FIFTY not in compute_tags(snap, cfg)

    def test_fifty_fifty_suppressed_when_flag_disabled(self):
        cfg = make_cfg()
        cfg.ENABLE_FIFTY_FIFTY = False
        snap = make_snap(p_yes=0.50, volume_24h=99999)
        assert MarketTag.FIFTY_FIFTY not in compute_tags(snap, cfg)

    def test_multiple_tags_simultaneously(self):
        cfg = make_cfg()
        snap = make_snap(
            is_trending=True, closing_soon=True,
            volatility_score=cfg.volatility_threshold("BTC", "daily") + 0.1,
        )
        tags = compute_tags(snap, cfg)
        assert MarketTag.TRENDING in tags
        assert MarketTag.CLOSING_SOON in tags
        assert MarketTag.VOLATILE in tags

    def test_market_selection_item_fields(self):
        item = MarketSelectionItem(
            market_id="KXBTCD-26MAR22",
            title="Will BTC close above $87k?",
            frequency="daily",
            volume_24h=5000,
            p_yes=0.52,
            tags={MarketTag.TRENDING},
        )
        assert item.market_id == "KXBTCD-26MAR22"


# ---------------------------------------------------------------------------
# TestAlertCategoryExtension
# ---------------------------------------------------------------------------

class TestAlertCategoryExtension:
    def test_market_selection_category_exists(self):
        from merid.prediction.alerts import AlertCategory
        assert AlertCategory.MARKET_SELECTION.value == "market_selection"


# ---------------------------------------------------------------------------
# TestSnapshotConstruction
# ---------------------------------------------------------------------------

class TestSnapshotConstruction:
    def _make_router_with_meta(self):
        from merid.alerts.crypto_alert_router import _MarketMeta
        r = CryptoAlertRouter()
        r._market_meta["KXBTCD-26MAR22"] = _MarketMeta(
            ticker="KXBTCD-26MAR22",
            series_ticker="KXBTCD",
            title="Will BTC close above $87k?",
            status="active",
            created_at_ts=time.time() - 7200,
            open_interest=500,
        )
        return r

    def _make_state(self, ticker="KXBTCD-26MAR22", **kw):
        class FakeState:
            pass
        s = FakeState()
        s.ticker = ticker
        s.mid_cents = kw.get("mid_cents", 52)
        s.spread_cents = kw.get("spread_cents", 2.0)
        s.depth_10c = kw.get("depth_10c", 100)
        s.volume_24h = kw.get("volume_24h", 6000)
        s.seconds_to_expiry = kw.get("seconds_to_expiry", 3600.0)
        return s

    def test_build_snapshot_returns_none_for_unsupported_ticker(self):
        r = self._make_router_with_meta()
        assert r._build_snapshot(self._make_state(ticker="KXCORN-26MAR22")) is None

    def test_build_snapshot_returns_none_when_meta_missing(self):
        r = CryptoAlertRouter()
        assert r._build_snapshot(self._make_state()) is None

    def test_build_snapshot_p_yes_clamped_0_1(self):
        r = self._make_router_with_meta()
        snap = r._build_snapshot(self._make_state(mid_cents=200))
        assert snap is not None and 0.0 <= snap.p_yes <= 1.0

    def test_build_snapshot_symbol_correctly_inferred(self):
        r = self._make_router_with_meta()
        snap = r._build_snapshot(self._make_state())
        assert snap is not None and snap.symbol == "BTC"

    def test_build_snapshot_closing_soon_flag(self):
        r = self._make_router_with_meta()
        seconds = r._cfg.CLOSING_SOON_WINDOW_MINUTES * 60 - 30
        snap = r._build_snapshot(self._make_state(seconds_to_expiry=seconds))
        assert snap is not None and snap.closing_soon is True

    def test_build_snapshot_title_is_html_escaped(self):
        from merid.alerts.crypto_alert_router import _MarketMeta
        r = CryptoAlertRouter()
        r._market_meta["KXBTCD-26MAR22"] = _MarketMeta(
            ticker="KXBTCD-26MAR22",
            series_ticker="KXBTCD",
            title="Price > $87k & rising",
            status="active",
            created_at_ts=time.time() - 7200,
            open_interest=None,
        )
        snap = r._build_snapshot(self._make_state())
        assert snap is not None
        assert "&gt;" in snap.title
        assert ">" not in snap.title


# ---------------------------------------------------------------------------
# TestCooldownMap
# ---------------------------------------------------------------------------

class TestCooldownMap:
    def test_not_suppressed_initially(self):
        r = CryptoAlertRouter()
        key = r._key_risk("BTC", "ep1", "warning")
        assert not r._is_suppressed(key, 5.0)

    def test_suppressed_after_record_fired(self):
        r = CryptoAlertRouter()
        key = r._key_risk("BTC", "ep1", "warning")
        r._record_fired(key)
        assert r._is_suppressed(key, 5.0)

    def test_risk_key_and_market_key_are_distinct(self):
        r = CryptoAlertRouter()
        assert r._key_risk("BTC", "ep1", "warning") != r._key_market_selection("BTC", MarketTag.TRENDING)

    def test_different_symbols_have_different_keys(self):
        r = CryptoAlertRouter()
        assert r._key_risk("BTC", "ep1", "warning") != r._key_risk("ETH", "ep1", "warning")

    def test_severity_escalation_key_differs(self):
        r = CryptoAlertRouter()
        assert r._key_risk("BTC", "ep1", "warning") != r._key_risk("BTC", "ep1", "critical")

    def test_market_selection_key_per_tag(self):
        r = CryptoAlertRouter()
        assert r._key_market_selection("BTC", MarketTag.TRENDING) != r._key_market_selection("BTC", MarketTag.VOLATILE)

    def test_cooldown_expires(self):
        r = CryptoAlertRouter()
        key = r._key_risk("BTC", "ep1", "warning")
        r._cooldowns[key] = time.monotonic() - 400  # 400s ago > 5 min
        assert not r._is_suppressed(key, 5.0)


# ---------------------------------------------------------------------------
# TestRankAndSelect
# ---------------------------------------------------------------------------

class TestRankAndSelect:
    def test_trending_ranks_by_volume_descending(self):
        snaps = [
            make_snap(market_id="A", is_trending=True, volume_24h=100),
            make_snap(market_id="B", is_trending=True, volume_24h=500),
            make_snap(market_id="C", is_trending=False, volume_24h=1000),
        ]
        ranked = _rank_snapshots(snaps, MarketTag.TRENDING, 5)
        assert len(ranked) == 2
        assert ranked[0].market_id == "B"

    def test_volatile_ranks_by_volatility_score(self):
        snaps = [
            make_snap(market_id="X", volatility_score=0.5),
            make_snap(market_id="Y", volatility_score=0.9),
            make_snap(market_id="Z", volatility_score=0.3),
        ]
        ranked = _rank_snapshots(snaps, MarketTag.VOLATILE, 2)
        assert ranked[0].market_id == "Y"
        assert len(ranked) == 2

    def test_closing_soon_ranks_by_expiry_ascending(self):
        snaps = [
            make_snap(market_id="P", closing_soon=True, seconds_to_expiry=300),
            make_snap(market_id="Q", closing_soon=True, seconds_to_expiry=100),
            make_snap(market_id="R", closing_soon=False, seconds_to_expiry=50),
        ]
        ranked = _rank_snapshots(snaps, MarketTag.CLOSING_SOON, 5)
        assert ranked[0].market_id == "Q"

    def test_top_n_cap_respected(self):
        snaps = [make_snap(market_id=str(i), volume_24h=i * 10) for i in range(10)]
        assert len(_rank_snapshots(snaps, MarketTag.HIGH_VOLUME, 4)) <= 4


# ---------------------------------------------------------------------------
# TestRouterStatusEndpoint
# ---------------------------------------------------------------------------

class TestRouterStatusEndpoint:
    def test_status_dict_shape(self):
        r = CryptoAlertRouter()
        status = r.get_status()
        assert "running" in status
        assert "last_tick_ts" in status
        assert "error_count" in status

    def test_metrics_dict_shape(self):
        r = CryptoAlertRouter()
        metrics = r.get_metrics()
        assert "counters" in metrics
        assert "gauges" in metrics
