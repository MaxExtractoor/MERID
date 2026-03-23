# Kalshi Continuous Trader Verification Report

This report validates the BTC discovery and execution loop that powers the Kalshi AgentGrid.

## Architecture
- Live loop is `AgentGrid` + `KalshiTradingAgent`, started from `web/main.py` lifespan. It supervises the Kalshi catalog refresh and WebSocket bridge and exposes `/api/v1/kalshi-grid/health` for runtime checks.
- `KalshiMarketCatalog` is the single source of venue markets. It refreshes on startup and every `refresh_interval_s`, keeping a capped 200-market view from `GET /markets?status=open&limit=200`.

## BTC Market Discovery
- Pipeline: `list_markets(status=open, limit=200)` → enrich catalog → regex filter `^KX(BTC|BITCOIN)` → timeframe classification → volume sort → cap 5.
- Discovery diagnostics are logged every cycle with counts for raw → BTC → timeframe → selected tickers, so "no tradeable BTC" is tied to the exact funnel stage.
- Catalog refresh logs BTC visibility globally (total, 15m, 1h, sample tickers).

## Health & Observability
- `/api/v1/kalshi-grid/health` includes BTC visibility (`total`, `m15`, `h1`, `sample_tickers`) in addition to catalog size, WS bridge state, rate limits, and risk status.
- `btc15m_lane` records blocked-cycle reasons with structured context (phase, risk, sentiment, drawdown).
- `KalshiExecutor.execute_trade` logs which gate (kill switch, VenueGate, risk manager, deployment) vetoed an order to avoid silent drops.

## Root-Cause Labels for "No Tradeable BTC"
- `phase_locked_asset` / `phase_locked_timeframe` — promotion gates not open.
- `api_empty` — Kalshi returned zero markets.
- `no_btc_markets` — venue has open markets but none tagged BTC.
- `no_btc_timeframe` — BTC exists but not in requested timeframe.
- `volume_filter` — BTC timeframe markets present but none survive volume/sort selection.

## Regression Coverage
- `tests/test_btc_market_discovery.py` verifies the BTC discovery funnel: BTC-only selection, timeframe narrowing, volume ordering, and reason labeling when the venue returns nothing.

## Local Testing Notes
- Use `PYTEST_LIGHT_STUBS=1` with `pytest -c pytest.ini.local tests/test_btc_market_discovery.py` to bypass heavy Telegram/Neo4j deps during offline BTC diagnostics.
