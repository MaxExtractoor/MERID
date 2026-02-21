# MERID — Environment Configuration

## Quick Setup

```bash
cp .env.example .env        # copy template
make serve                  # start API server
```

MERID runs in paper mode with zero configuration. Add Kalshi credentials below for live market data.

---

## Kalshi Credentials

```bash
KALSHI_API_KEY_ID=your_key_id
KALSHI_PRIVATE_KEY_PATH=path/to/private_key.pem
KALSHI_USE_DEMO=true                  # true = demo environment, false = production
```

Get credentials at [https://kalshi.com/](https://kalshi.com/) → Account → API Keys.

---

## Trading Mode

```bash
MERID_PM_TRADING_MODE=sim             # sim | paper | live
MERID_PM_LIVE_ENABLED=false           # must be true to enable live trading
```

| Mode | Behavior |
|------|----------|
| `sim` | Simulated fills, no API calls |
| `paper` | Real market data from Kalshi, simulated execution |
| `live` | Real orders on Kalshi (requires `MERID_PM_LIVE_ENABLED=true`) |

---

## Risk Limits

```bash
MERID_PM_MAX_NOTIONAL_PER_MARKET=500  # max notional per market ($)
MERID_PM_MAX_DAILY_LOSS=250           # daily loss limit ($)
MERID_PM_MAX_TOTAL_NOTIONAL=5000      # total portfolio notional cap ($)
MERID_TOTAL_CAPITAL_USD=50000         # total capital allocation
```

---

## Optional Services

```bash
# Graph database (consensus memory — not required)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Cache / pub-sub (not required)
REDIS_URL=redis://localhost:6379
```

---

## Fresh Start

```bash
MERID_FRESH_START=1                   # reset all state on next boot (paper mode only)
```

This clears paper positions, signals, consensus, and drift state. Kill switch state is preserved. Cannot be used in live mode.

---

## Notes

- Never commit `.env` to version control
- `.env.example` has the full variable list with defaults
- Run `make preflight` before committing to verify system health
