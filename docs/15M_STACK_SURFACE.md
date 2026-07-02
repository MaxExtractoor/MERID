# 15m Kalshi Crypto Stack - Allowed Surface

**Purpose:** Define the exact set of modules that constitute the lean 15m Kalshi crypto trading stack. No other modules should be imported or referenced in 15m_live mode.

## Active 15m Modules (Allowed Surface)

### Core Trading Logic
- `merid/loop_15m.py` – Kalshi15mLoop and readiness checks
- `merid/prediction/agent_grid_15m.py` – LeanAgentGrid15m, LeanAgent15m, candidate collection, priority queue
- `merid/prediction/candidate_optimizer.py` – 15m optimizer, `_check_spot_data`, `generate_candidates`, MD/spot filters, dynamic windows

### Data Plane
- `data/unified_spot_service.py` – UnifiedSpotService, `get_unified_spot_service`, `get(asset)`, watchdog
- `merid/event_venues/kalshi/market_state.py` – KalshiMarketStateStore, canonical MD store and duality checks
- `merid/event_venues/kalshi/market_catalog.py` – KalshiMarketCatalog, series ticker extraction

### Venue Integration
- `merid/event_venues/kalshi/venue_adapter.py` – Kalshi venue adapter
- `merid/event_venues/kalshi/order_router.py` – Kalshi order router
- `merid/event_venues/kalshi/kalshi_risk.py` – KalshiRiskConfig (venue-specific, canonical)

### Configuration
- `config/kalshi_crypto_15m.yaml` – Single source of truth for 15m crypto risk / thresholds
  - **Current operational spread cap: 70 cents** (`guardrails.max_spread_cents: 70`)
  - **Rationale:** Live Kalshi crypto 15m markets typically trade at 45-61 cent spreads (BTC/ETH/SOL/XRP/DOGE). The previous 40c cap was blocking all trading. 70c allows participation while still managing adverse selection risk. This threshold is dynamic and should be tuned as market conditions evolve.
  - **Profile is the single knob:** All spread, depth, and quality thresholds are driven from this profile. No hardcoded magic numbers in code.
- `config/kalshi_agent_grid.yaml` – Agent topology only (5 agents, 15M series tickers)
- `config/kalshi_universe.py` – 15M series lookup used by grid and catalog

### Entry Point
- `web/main_15m_lean.py` – FastAPI entrypoint, startup thread, loop wiring

## Shared Infrastructure (Allowed)

### Generic Utilities
- Logging (standard library + custom loggers)
- Metrics (standard library + custom metrics)
- Time/datetime utilities
- Type hints and dataclasses

### Kalshi Venue Client
- `merid/event_venues/kalshi/*` (venue client, models, utilities)

## Forbidden Modules (Not Allowed in 15m_live Mode)

### PM Runtime
- PM runtime controllers
- PM portfolio abstractions
- PM correlation engines
- PM signal fusion

### Paper Trading
- Paper trading engine
- Paper session management
- Paper order simulation

### Reflection/Learning
- Reflection systems
- Learning algorithms
- Agent performance tracking (PM version)

### Social Broadcasters
- Social media integrations
- Telegram/X publishers (PM version)

### Cross-Venue Logic
- Cross-venue arbitrage
- Multi-venue order routing
- Cross-venue risk aggregation

### Legacy Configs
- `config/kalshi_15m_crypto_config.py` (deprecated, has banner)
- `config/crypto_threshold_matrix.yaml` (profile-gated)
- Old agent grid configs (archived)

### Legacy Agents
- HOURLY/D1/W1 agents (archived)
- KalshiContinuousTrader (legacy/research-only, has deprecation warning)
- KALSHI_ARB_SCANNER (archived)
- KALSHI_CATCH_ALL (archived)

## Import Policy

### Allowed Imports
```python
# 15m-specific modules
from merid.loop_15m import Kalshi15mLoop
from merid.prediction.agent_grid_15m import LeanAgentGrid15m, LeanAgent15m
from merid.prediction.candidate_optimizer import CandidateOptimizer
from data.unified_spot_service import get_unified_spot_service
from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog

# Configuration
from config.kalshi_crypto_15m import *  # Profile config
from config.kalshi_agent_grid import load_agent_grid_config
from config.kalshi_universe import kalshi_agent_grid_catalog_series_tickers

# Generic utilities
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass
```

### Forbidden Imports
```python
# PM runtime
from merid.pm_runtime import *  # FORBIDDEN
from merid.portfolio import *  # FORBIDDEN

# Paper trading
from merid.prediction.paper_session import *  # FORBIDDEN
from merid.prediction.paper_trading import *  # FORBIDDEN

# Reflection/learning
from merid.agents.reflection import *  # FORBIDDEN
from merid.agents.learning import *  # FORBIDDEN

# Social broadcasters
from merid.interfaces.telegram import *  # FORBIDDEN
from merid.interfaces.x_publisher import *  # FORBIDDEN

# Cross-venue
from merid.arbitrage import *  # FORBIDDEN
from merid.multi_asset import *  # FORBIDDEN

# Legacy configs
from config.kalshi_15m_crypto_config import *  # FORBIDDEN (deprecated)
```

## Configuration Hierarchy

### For 15m_live Mode
1. **Profile:** `kalshi_crypto_15m.yaml` (single source of truth for risk/thresholds)
2. **Agent Topology:** `kalshi_agent_grid.yaml` (agent names, series tickers only)
3. **Series Lookup:** `kalshi_universe.py` (15M series tickers only)

### Profile Validation
- When `MERID_RUNTIME_MODE='15m_live'`:
  - `MERID_PROFILE` must be `kalshi_crypto_15m_v2`
  - Fail startup if profile is missing or invalid
  - Fail startup if deprecated config modules are imported

## Series Ticker Invariants

### Allowed Series (5 crypto 15M only)
- KXBTC15M
- KXETH15M
- KXSOL15M
- KXXRP15M
- KXDOGE15M

### Forbidden Series
- Base tickers (KXBTC, KXETH, etc.) – use 15M suffix
- HOURLY/D1/W1 series – not for 15m trading
- Cross-venue series – not for 15m stack

## Runtime Guards

### Startup Validation
1. Check `MERID_RUNTIME_MODE='15m_live'`
2. Validate `MERID_PROFILE=kalshi_crypto_15m_v2`
3. Verify `kalshi_crypto_15m.yaml` exists
4. Check forbidden modules not imported (sys.modules check)
5. Verify only 5 agents enabled in grid

### Periodic Validation
1. Log series tickers in use (should be 5 crypto 15M only)
2. Log imports from 15m modules (should be from allowed surface only)
3. Log profile in use (should be kalshi_crypto_15m_v2)

## Verification Checklist

### Code Level
- [ ] No imports from forbidden modules in 15m code
- [ ] No references to non-15M series tickers
- [ ] No calls to PM runtime functions
- [ ] No paper trading logic
- [ ] No reflection/learning systems
- [ ] No social broadcasters
- [ ] No cross-venue logic

### Configuration Level
- [ ] Profile hierarchy documented
- [ ] Profile resolver validates MERID_PROFILE
- [ ] Deprecated configs have banners
- [ ] Legacy configs in archive/

### Runtime Level
- [ ] Startup validation passes
- [ ] Logs show only 15m modules
- [ ] Logs show only 5 crypto 15M series
- [ ] No legacy references in logs
- [ ] Agent grid cycles running
- [ ] Candidates generated for 5 assets

## Migration Guide

### Moving Legacy Code
1. Add deprecation banner at top of file:
   ```python
   # LEGACY / DEMO: Not used by kalshi_crypto_15m_v2 15m stack.
   # Do not import from 15m code paths.
   ```

2. Move to `archive/legacy/` directory

3. Update imports in non-15m code to use new location

4. Verify 15m code no longer references moved module

### Adding New 15m Features
1. Add to allowed surface documentation
2. Follow import policy
3. Add to runtime validation if needed
4. Update verification checklist
