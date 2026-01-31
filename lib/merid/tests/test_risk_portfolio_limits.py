from merid_trading import pre_trade_check
from core.autonomy_store import get_portfolio_limits


def test_reject_per_symbol_notional():
    portfolio = get_portfolio_limits("core")
    # core.max_notional == 1_000_000 in test data
    order = {"symbol": "BTC-USD", "side": "buy", "quantity": 10, "price": 200_000}
    ok, reason = pre_trade_check(order, {"balance": 100_000}, portfolio_limits=portfolio)
    assert ok is False
    assert reason == "notional exceeds portfolio limits"


def test_reject_daily_loss():
    portfolio = get_portfolio_limits("core")
    order = {"symbol": "BTC-USD", "side": "sell", "quantity": 1, "price": 1}
    # Simulate current loss of 49_900 and a projected loss of 200 -> exceeds max_daily_loss (50_000)
    ok, reason = pre_trade_check(order, {"balance": 100_000}, portfolio_limits=portfolio, projected_loss=200, current_day_loss=49_900)
    assert ok is False
    assert reason == "would exceed daily loss"


def test_reject_max_open_orders():
    portfolio = get_portfolio_limits("core")
    # core.max_open_orders == 25
    order = {"symbol": "ETH-USD", "side": "buy", "quantity": 1, "price": 1}
    ok, reason = pre_trade_check(order, {"balance": 100_000}, portfolio_limits=portfolio, open_orders=25)
    assert ok is False
    assert reason == "max open orders exceeded"