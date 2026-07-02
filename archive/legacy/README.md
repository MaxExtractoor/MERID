# Legacy Code Archive

**DEPRECATED - DO NOT USE IN PRODUCTION**

This directory contains legacy code that has been replaced by production components for the 15m Kalshi crypto trading system.

## Contents

- `agent_grid.py` - Legacy AgentGrid implementation (replaced by `merid/prediction/agent_grid_15m.py`)

## Production Stack

The production 15m Kalshi crypto trading system uses:
- **Agent Grid**: `merid/prediction/agent_grid_15m.py` (LeanAgentGrid15m)
- **Loop**: `merid/loop_15m.py`
- **Entry Point**: `web/main_15m_lean.py`
- **Startup Script**: `start_15m.ps1`
- **Config Profile**: `config/profiles/kalshi_crypto_15m_v2.yaml`

## Critical Assets

The production stack supports these 5 crypto assets:
- BTC/USD
- ETH/USD
- SOL/USD
- XRP/USD
- DOGE/USD

## Notes

- Legacy code is preserved for regression testing and historical reference
- Do not import or use legacy components in production code
- All new development should use production components
