from merid.prediction.risk.settlement_risk_model import (
    estimate_settlement_variance,
    settlement_kelly_shrink_factor,
)


def test_shrink_monotonic_with_variance():
    s_low = settlement_kelly_shrink_factor(estimate_settlement_variance("BTC", 100.0, 0.001))
    s_high = settlement_kelly_shrink_factor(estimate_settlement_variance("BTC", 100.0, 0.05))
    assert s_high < s_low < 1.0
