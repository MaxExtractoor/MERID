# MERID Live-Only Mode Configuration Guide

This document explains how to configure MERID to run in "live-only" mode where all UI sections, agents, and endpoints use real upstream data instead of mock or sample data.

## 🎯 What is Live-Only Mode?

Live-only mode ensures that:
- **No mock data** is used anywhere in the application
- **No demo/sample data** is displayed in the UI
- **All WebSocket streams** connect to real upstream services
- **All REST endpoints** call real APIs
- **All agents** use real market data and analysis

## 🔧 Configuration Steps

### 1. Environment Variables

Set these flags in your `.env` file:

```bash
# =============================================================================
# LIVE-ONLY MODE SETTINGS
# =============================================================================
# Disable all mock/demo data
MERID_USE_MOCK_ARB_DATA=false
MERID_USE_DEMO_TRADES=false
MERID_USE_SAMPLE_DATA=false
MERID_USE_MOCK_STREAMS=false

# Enable real-time features
MERID_ENABLE_LIVE_PRICE_FEEDS=true
MERID_ENABLE_REAL_PREDICTION_MARKETS=true
MERID_ENABLE_REAL_SOLANA_WS=true
MERID_ENABLE_REAL_NEWS=true
```

### 2. Feature Flags

Enable the real-time features you want:

```bash
# Real-time data sources
MERID_ENABLE_NEWS_AGENT=true
MERID_ENABLE_WHALE_INTEL=true
MERID_ENABLE_POLYMARKET=true

# Optional integrations (set to true if you have API keys)
MERID_ENABLE_CHAINLINK=false
MERID_ENABLE_AUGUR=false
```

### 3. API Keys

Configure real API keys for the services you want to use:

```bash
# Prediction Markets
POLYMARKET_API_KEY=your_real_api_key
POLYMARKET_API_SECRET=your_real_api_secret
POLYMARKET_WALLET_ADDRESS=your_wallet_address
POLYMARKET_PRIVATE_KEY=your_private_key

# Crypto Exchanges
ALPACA_API_KEY=your_alpaca_key
ALPACA_API_SECRET=your_alpaca_secret

# News & Social
X_BEARER_TOKEN=your_x_bearer_token
TELEGRAM_TOKEN=your_telegram_token
```

## 🚀 Starting MERID in Live-Only Mode

```bash
cd c:/Dev/MERID
uvicorn web.main:app --host 127.0.0.1 --port 8011 --reload --env-file .env
```

The `--env-file .env` flag ensures Uvicorn loads exactly one environment file, preventing any conflicts.

## 🔍 Validation

Run the validation script to confirm live-only mode:

```bash
python validate_live_only_mode.py
```

This will check:
- ✅ Mock data is disabled
- ✅ Demo trades are disabled  
- ✅ Sample data is disabled
- ✅ Mock streams are disabled
- ✅ Real-time features are enabled
- ✅ Mock routers are not loaded
- ✅ Only live endpoints are available

## 📊 Real Data Sources

### Price Feeds
- **Kraken** - Primary exchange for crypto prices
- **Coinbase** - Backup exchange for price data
- **Gemini** - Tertiary exchange for price data

### Prediction Markets
- **Polymarket** - Real prediction market data via Gamma API
- **Kalshi** - CFTC-regulated prediction markets
- **Augur** - Decentralized prediction markets (mock for now)

### Solana Blockchain
- **Real Solana RPC** - QuickNode, Helius, or your own node
- **Solana WebSocket** - Real transaction streams
- **Whale Detection** - Real large transaction monitoring

### News & Social
- **X/Twitter API** - Real social media sentiment
- **News Feeds** - Real news aggregation
- **Telegram** - Real notification delivery

## 🎛 UI Sections in Live-Only Mode

All UI sections will now display real data:

- **Dashboard** - Real system metrics and activity
- **Prediction Markets** - Live Polymarket data
- **Arbitrage** - Real arbitrage opportunities
- **Trading** - Real trading data and positions
- **Whales** - Real Solana whale activity
- **Agents** - Real agent performance and tasks
- **System** - Real system health and metrics
- **News** - Real news feeds and sentiment
- **Analytics** - Real performance analytics

## 🔄 WebSocket Streams

Real-time WebSocket connections:

- `/ws` - General system events
- `/ws/whales` - Solana whale transactions
- `/ws/prices` - Live price updates
- `/ws/trades` - Real trade executions
- `/ws/positions` - Real position updates
- `/ws/simulation` - Agent simulation events
- `/ws/system` - System health events
- `/ws/arbitrage` - Arbitrage opportunities
- `/ws/spectator/stream` - Spectator mode events

## 🚨 Troubleshooting

### Mock Data Still Appearing

1. Check environment variables:
   ```bash
   python -c "from merid.settings import settings; print(settings.MERID_USE_MOCK_ARB_DATA)"
   ```

2. Restart MERID with explicit env file:
   ```bash
   uvicorn web.main:app --env-file .env --reload
   ```

3. Clear browser cache and reload

### Real Data Not Loading

1. Check API keys are set correctly
2. Verify network connectivity
3. Check service status pages
4. Review logs for connection errors

### WebSocket Connection Issues

1. Verify WebSocket is enabled:
   ```bash
   python -c "from merid.settings import settings; print(settings.MERID_DEV_ALLOW_WS)"
   ```

2. Check firewall allows WebSocket connections
3. Verify WebSocket endpoints are reachable

## 📋 Configuration Checklist

- [ ] `MERID_USE_MOCK_ARB_DATA=false`
- [ ] `MERID_USE_DEMO_TRADES=false`
- [ ] `MERID_USE_SAMPLE_DATA=false`
- [ ] `MERID_USE_MOCK_STREAMS=false`
- [ ] `MERID_ENABLE_LIVE_PRICE_FEEDS=true`
- [ ] `MERID_ENABLE_REAL_PREDICTION_MARKETS=true`
- [ ] `MERID_ENABLE_REAL_SOLANA_WS=true`
- [ ] `MERID_ENABLE_REAL_NEWS=true`
- [ ] Mock routers removed from `web/main.py`
- [ ] Only live routers included
- [ ] Real API keys configured where needed
- [ ] Uvicorn started with `--env-file .env`

## 🎉 Benefits of Live-Only Mode

- **Real-time accuracy** - All data reflects current market conditions
- **Production readiness** - Configuration matches production expectations
- **No confusion** - Clear distinction between demo and live data
- **Better testing** - Tests run against real data patterns
- **User trust** - Users see actual performance, not simulated results

## 🔄 Switching Back to Demo Mode

If you need to temporarily enable demo mode for testing:

```bash
# Set demo flags in .env
MERID_USE_MOCK_ARB_DATA=true
MERID_USE_DEMO_TRADES=true
MERID_USE_SAMPLE_DATA=true
```

Then restart MERID.

---

**MERID Live-Only Mode ensures all users see real, actionable data from live upstream services.**
