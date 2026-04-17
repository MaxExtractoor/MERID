from merid.event_venues.kalshi.settlement_execution_guard import evaluate_settlement_order


def test_buy_blocked_final_minute_crypto_ticker(monkeypatch):
    monkeypatch.setenv("MERID_RTI_SETTLEMENT_ORDER_POLICY", "reduce_ok")
    r = evaluate_settlement_order(
        ticker="KXBTC15M-26JAN011200-0",
        action="buy",
        seconds_to_expiry=30.0,
        count=1,
    )
    assert r is not None


def test_buy_allowed_outside_window():
    assert (
        evaluate_settlement_order(
            ticker="KXBTC15M-26JAN011200-0",
            action="buy",
            seconds_to_expiry=120.0,
            count=1,
        )
        is None
    )


def test_non_crypto_ticker_passes():
    assert (
        evaluate_settlement_order(
            ticker="KXFED-25DEC-T5.00",
            action="buy",
            seconds_to_expiry=10.0,
            count=1,
        )
        is None
    )
