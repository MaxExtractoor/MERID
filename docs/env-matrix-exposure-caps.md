# Kalshi Continuous Trader — Environment Variable Matrix

This document provides a comprehensive reference for all environment variables used to configure the `KalshiContinuousTrader` exposure caps and risk management parameters.

## Quick Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `KALSHI_TRADER_EXPOSURE_BTC` | 0.20 | Max bankroll % for BTC positions |
| `KALSHI_TRADER_EXPOSURE_ETH` | 0.15 | Max bankroll % for ETH positions |
| `KALSHI_TRADER_EXPOSURE_SOL` | 0.10 | Max bankroll % for SOL positions |
| `KALSHI_TRADER_EXPOSURE_XRP` | 0.10 | Max bankroll % for XRP positions |
| `KALSHI_TRADER_EXPOSURE_DOGE` | 0.10 | Max bankroll % for DOGE positions |
| `KALSHI_TRADER_EXPOSURE_DEFAULT` | 0.10 | Fallback exposure % for unlisted assets |
| `KALSHI_TRADER_GLOBAL_EXPOSURE` | 0.40 | Max total exposure across all crypto assets |
| `KALSHI_TRADER_MIN_ASSET_CAP_CENTS` | 100 | Minimum per-asset cap in cents ($1.00) |

## Detailed Configuration

### Per-Asset Exposure Caps

Each crypto asset has an independent exposure cap expressed as a fraction of total bankroll:

```bash
# Conservative allocation (default)
KALSHI_TRADER_EXPOSURE_BTC=0.20    # 20% — BTC gets largest allocation
KALSHI_TRADER_EXPOSURE_ETH=0.15    # 15%
KALSHI_TRADER_EXPOSURE_SOL=0.10    # 10%
KALSHI_TRADER_EXPOSURE_XRP=0.10    # 10%
KALSHI_TRADER_EXPOSURE_DOGE=0.10   # 10%
```

**Key behavior:** Independent buckets mean BTC at its cap does NOT block ETH/SOL/XRP/DOGE trading.

### Series Exposure Multipliers

Timeframe-specific scaling is applied automatically (not configurable via env):

| Timeframe | Multiplier | Result for 20% BTC Cap |
|-----------|------------|------------------------|
| 15m | 0.40 | 8% effective cap |
| 1h | 0.70 | 14% effective cap |
| daily | 1.00 | 20% effective cap |
| weekly | 1.00 | 20% effective cap |
| monthly | 0.80 | 16% effective cap |
| annual | 0.60 | 12% effective cap |

### Global Exposure Guardrail

```bash
KALSHI_TRADER_GLOBAL_EXPOSURE=0.40  # 40% of bankroll max across ALL crypto
```

This creates a two-stage gate:
1. Per-asset cap check first
2. Global exposure check second (sum of all crypto positions)

### Minimum Asset Cap Floor

```bash
KALSHI_TRADER_MIN_ASSET_CAP_CENTS=100  # $1.00 minimum
```

Prevents micro-account lockout when bankroll × exposure_pct would round to <$1.

## Risk Management Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KALSHI_TRADER_BANKROLL` | 0 | **Optional** static reference bankroll in cents for performance reporting only. Live trading uses bankroll_service_v2. If not set (0), performance % returns will be relative to 0. |
| `KALSHI_TRADER_RISK_PCT` | 0.02 | Max 2% bankroll risk per trade |
| `KALSHI_TRADER_KELLY_FRAC` | 0.25 | Quarter-Kelly sizing (survival-first) |
| `KALSHI_TRADER_MAX_EXPOSURE` | 0.20 | Legacy single-asset exposure cap |
| `KALSHI_TRADER_DD_HALT` | 0.20 | Halt trading at 20% drawdown |
| `KALSHI_TRADER_DD_REDUCE` | 0.10 | Reduce sizing at 10% drawdown |
| `KALSHI_TRADER_MIN_BALANCE` | 200 | Never trade below $2.00 reserve |

## Operational Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KALSHI_TRADER_INTERVAL` | 60 | Trading cycle interval in seconds |
| `KALSHI_TRADER_DRY_RUN` | false | Paper trading mode (no real orders) |
| `KALSHI_TRADER_SMOKE_TEST` | false | Relaxes constraints for e2e testing |
| `KALSHI_TRADER_MAX_PRICE` | 35 | Never buy contracts above 35¢ |
| `KALSHI_TRADER_MIN_PRICE` | 2 | Skip penny contracts (no liquidity) |
| `KALSHI_TRADER_MAX_POSITION` | 3 | Max contracts held per ticker |
| `KALSHI_TRADER_MAX_OPEN` | 5 | Max simultaneous markets |
| `KALSHI_TRADER_MAX_SCAN` | 10 | Max markets to scan per cycle |

## Kalshi Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `KALSHI_ENV` | demo | "live" for production, "demo" for sandbox |
| `KALSHI_API_KEY_ID` | "" | API key identifier |
| `KALSHI_PRIVATE_KEY_PATH` | kalshi_private_key.pem | Path to RSA private key |
| `KALSHI_API_BASE_URL` | (auto) | Override API endpoint |
| `KALSHI_CT_AUTO_EXIT` | false | Enable automatic position exit |
| `KALSHI_CT_BYPASS_PM_LIVE_GATE` | false | Bypass PM live interlock (dangerous) |

## Example Configurations

### Conservative (Low Risk)
```bash
KALSHI_TRADER_EXPOSURE_BTC=0.15
KALSHI_TRADER_EXPOSURE_ETH=0.10
KALSHI_TRADER_EXPOSURE_SOL=0.05
KALSHI_TRADER_EXPOSURE_XRP=0.05
KALSHI_TRADER_EXPOSURE_DOGE=0.05
KALSHI_TRADER_GLOBAL_EXPOSURE=0.25
KALSHI_TRADER_RISK_PCT=0.01
KALSHI_TRADER_KELLY_FRAC=0.15
```

### Aggressive (Higher Risk)
```bash
KALSHI_TRADER_EXPOSURE_BTC=0.30
KALSHI_TRADER_EXPOSURE_ETH=0.25
KALSHI_TRADER_EXPOSURE_SOL=0.15
KALSHI_TRADER_EXPOSURE_XRP=0.15
KALSHI_TRADER_EXPOSURE_DOGE=0.15
KALSHI_TRADER_GLOBAL_EXPOSURE=0.60
KALSHI_TRADER_RISK_PCT=0.03
KALSHI_TRADER_KELLY_FRAC=0.35
```

### Testing/Simulation
```bash
KALSHI_TRADER_DRY_RUN=true
KALSHI_TRADER_BANKROLL=10000  # $100 static reference for performance reporting (OPTIONAL - not required for trading)
KALSHI_TRADER_EXPOSURE_BTC=0.50
KALSHI_TRADER_GLOBAL_EXPOSURE=1.00
KALSHI_TRADER_SMOKE_TEST=true
```

## Validation

At startup, the trader validates all exposure caps via `_validate_asset_wiring()`:

1. **Asset Universe Check:** All active assets must match `EXPECTED_CRYPTO_UNIVERSE`
2. **CoinGecko ID Check:** All assets must have CoinGecko IDs for spot price fetching
3. **Spot Fallback Check:** All assets must have Coinbase + Binance fallback mappings
4. **Exposure Cap Check:** All assets must have exposure caps defined
5. **Series Resolution Check:** All series tickers must resolve to known assets

Missing caps trigger `[CRYPTO-WIRING-BUG]` errors with fail-fast behavior.

## Dashboard Integration

Status snapshots (for MERID dashboard) include:

```json
{
  "active_assets": ["BTC", "ETH", "SOL", "XRP", "DOGE"],
  "config": {
    "asset_max_exposure_pct": {
      "BTC": 0.20,
      "ETH": 0.15,
      "SOL": 0.10,
      "XRP": 0.10,
      "DOGE": 0.10
    }
  },
  "spot_prices": {
    "BTC": {"price": 45000.00, "age_seconds": 12, "source": "coingecko"}
  }
}
```

Access via: `GET /api/v1/kalshi/continuous-trader/status` (if wired in API)
