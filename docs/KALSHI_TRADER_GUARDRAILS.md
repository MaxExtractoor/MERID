# Kalshi trader guardrails uplift

## Bugs addressed
- Market probability derivation ignored contract direction, treating bearish threshold markets as if **YES** meant price goes up, leading to absurd long tail YES fills (e.g., BTC ≤59k while spot ~69k). (model.py, trading_agent.py)
- Strategy selection treated any speculative edge as tradeable without geometry, fee-aware edge, or Kelly viability checks, allowing negative-EV or catastrophic-strike YES orders. (strategy.py)

## Fixes implemented
- Canonical `KalshiMarketShape` normalization clarifies market type (UP/DOWN vs threshold ≤/≥), strike, expiry, and prices for each candidate. (merid/prediction/market_shape.py, trading_agent.py)
- Spot-aware fee-adjusted edge now respects market type when mapping spot/strike distance to probabilities. (model.py)
- Config-driven guardrails (move bands, min win prob, min net-edge per price band, Kelly>0) filter edges before sizing; geometry forbids YES on implausible moves unless tail bets are enabled. (strategy.py)
- Added targeted strategy tests covering catastrophic strike rejection and YES/NO selection on UP/DOWN markets. (tests/test_prediction_markets.py)

## Tuning knobs
- `MoveBandsConfig`: max_abs_move_{15m,1h,1d}, allow_tail_bets.
- `EdgeThresholdConfig`: min_true_win_prob, min_net_edge_bps_by_price_band for low/mid/high price bands.
- Adjust these via `StrategyConfig` to reflect live volatility and fee/edge appetite.
