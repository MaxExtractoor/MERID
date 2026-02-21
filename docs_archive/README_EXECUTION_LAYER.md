# MERID Execution Layer (Phase 1)

## Overview

The new `merid.execution` module provides a unified, async-first execution router that coordinates guard checks, explainability logging, and venue dispatch for all MERID trading intents.

## Structure

```text
merid/
├─ execution/
│  ├─ __init__.py          # Public exports
│  ├─ base.py              # TradeExecutor ABC + dataclasses
│  ├─ router.py            # ExecutionRouter (guards + explainability)
│  └─ executors/
│     ├─ __init__.py
│     ├─ coinbase.py       # Coinbase executor (real SDK calls)
│     ├─ jupiter.py        # Jupiter/Solana executor (real SDK calls)
│     ├─ fulcrom.py        # Fulcrom/Cronos executor (real SDK calls)
│     └─ cronos_onchain.py # Cronos onchain executor (real SDK calls)
```

## Usage

```python
from merid.execution import ExecutionRouter, TraderIdentity

router = ExecutionRouter()
result = await router.submit_trade(
    trader=TraderIdentity(trader_type="human", trader_id="alice"),
    venue_id="coinbase",
    symbol="BTC-USDT",
    side="buy",
    size=0.1,
)
```

## Integration

- Legacy `trading.router` now shims to the new `merid.execution.ExecutionRouter`.
- Existing adapters are wrapped via `_adapter_executor_factory` until native executors land.
- APIs (`web/api/trading_suite.py`) and agents (`trading/agents/execution_agent.py`) now call the async `submit_trade` path.

## Configuration

Key environment variables (see `.env.example`):

- `MERID_ENABLE_TRADING_SUITE` – Enable/disable the suite.
- `MERID_ALLOW_LIVE_TRADES` – Allow live trades (guarded).
- `MERID_MAX_NOTIONAL_PER_TRADE_USD` – Per‑trade notional cap.
- `MERID_TRADING_ALLOWED_VENUES` – Whitelist of venue IDs.
- Solana‑specific anti‑rug flags (`MERID_SOLANA_*`).
- Venue-specific credentials (Coinbase, Solana, Cronos, Fulcrom).

## Testing

```bash
pytest tests/unit/test_execution_router.py
pytest tests/unit/test_trade_executor.py
pytest tests/integration/test_full_cycle.py
```

## Dev Chat API

Simple text commands can trigger swarm actions and log explanations:

```bash
curl -X POST http://localhost:8000/api/v1/dev-chat/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "submit_test_trade"}'
```

Supported commands:

- `generate_tests <module>`
- `toggle_mode <mode>`
- `submit_test_trade`

## Docker Quickstart

```bash
docker-compose up
# Starts MERID API + Neo4j + Redis
# API available at http://localhost:8000
```

## Next Steps (Phase 2)

- Extend executors with real SDK authentication and signing.
- Add more venues (Kalshi, Alpaca, Webull, Crypto.com Exchange).
- Implement richer position tracking and PnL.
- Add more Dev Chat commands for swarm orchestration.
- Add end‑to‑end tests against testnet/paper accounts.
