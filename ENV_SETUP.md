# MERID Environment Configuration

## Quick Setup

1. Copy the environment template:
```bash
cp .env.example .env
```

2. Fill in the required values for your environment

3. Start the system:
```bash
make serve              # FastAPI on port 8000
make loop-start         # MeridLoop orchestrator
```

## Key Environment Variables

### **Required for Basic Operation**
- None — MERID runs in SIM mode with zero configuration.

### **Exchange Credentials (for paper/live trading)**
- `ALPACA_API_KEY`, `ALPACA_API_SECRET` — Alpaca equities
- `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH` — Kalshi prediction markets
- `BINANCE_API_KEY`, `BINANCE_API_SECRET` — Binance crypto
- `COINBASE_API_KEY`, `COINBASE_API_SECRET` — Coinbase
- `KRAKEN_API_KEY`, `KRAKEN_PRIVATE_KEY` — Kraken
- `OKX_API_KEY`, `OKX_SECRET_KEY`, `OKX_PASSPHRASE` — OKX

### **Market Data APIs (optional, enhances live feeds)**
- `FINNHUB_API_KEY` — Finnhub market data
- `POLYGON_API_KEY` — Polygon market data
- `ALPHA_VANTAGE_API_KEY` — Alpha Vantage

### **Capital & Risk Configuration**
- `MERID_TOTAL_CAPITAL_USD` — Total capital (default: 50000)
- `MERID_MAX_PORTFOLIO_NOTIONAL_USD` — Max portfolio notional (default: 50000)
- `MERID_PM_TRADING_MODE` — Prediction market mode: sim/paper/live (default: sim)
- `MERID_PM_MAX_DAILY_LOSS` — PM daily loss limit (default: 250)

### **Optional Services**
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` — Graph database (optional)
- `REDIS_URL` — Caching and pub/sub (optional)

## Documentation Links

- **Quick Start**: [QUICKSTART.md](QUICKSTART.md)
- **Getting Started (1hr)**: [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)
- **Go-Live Checklist**: [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md)
- **API Reference**: [web/api/](web/api/) (or `/docs` when server is running)

## Development Notes

- Use `.env` for local development
- Never commit `.env` to version control
- All sensitive values should use your secrets manager
- See `.env.example` for complete variable list
- Run `make preflight` before committing
