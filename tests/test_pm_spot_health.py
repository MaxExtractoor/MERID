"""pm_spot_health operator payload — effective OK, unusable reason, summary keys."""

from merid.prediction.pm_spot_health import get_operator_pm_spot_block


def test_operator_pm_spot_block_has_effective_fields():
    block = get_operator_pm_spot_block()
    assert "summary" in block
    assert "all_pm_assets_have_spot" in block["summary"]
    assert "assets" in block
    for _sym, row in block["assets"].items():
        assert "pm_spot_ok" in row
        assert "pm_spot_effective_ok" in row
        assert row["pm_spot_ok"] == row["pm_spot_effective_ok"]
        assert "pm_spot_unusable_reason" in row
        assert row["pm_spot_unusable_reason"] in (
            "ok",
            "no_asset",
            "no_price_feed",
            "no_quote_or_feed_ttl_expired",
            "pm_max_age_exceeded",
            "live_price_feed_unhealthy",
            "unknown",
        )
        assert "live_price_feed_healthy" in row
        assert "last_stream_tick_age_seconds" in row
