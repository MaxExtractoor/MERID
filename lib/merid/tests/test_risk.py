from merid_trading import pre_trade_check, CircuitBreaker


def test_pre_trade_check_basic():
    ok, reason = pre_trade_check({"quantity": 10, "price": 5}, {"balance": 1000})
    assert ok is True

    ok, reason = pre_trade_check({"quantity": -1}, {"balance": 1000})
    assert ok is False
    assert reason == "invalid quantity"

    ok, reason = pre_trade_check({"quantity": 1000000, "price": 1000}, {"balance": 1000})
    assert ok is False


def test_circuit_breaker_trip():
    CircuitBreaker.reset()
    for _ in range(CircuitBreaker._threshold):
        CircuitBreaker.record_error()
    assert CircuitBreaker.is_tripped() is True
    CircuitBreaker.reset()
    assert CircuitBreaker.is_tripped() is False
