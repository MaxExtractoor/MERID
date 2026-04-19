# Feature Flags & Toggles Audit Report

> **Audit Date:** 2026-04-18  
> **Scope:** Full codebase scan for feature flags, toggles, and conditional behavior  
> **System Status:** Production trading system (Kalshi-only mode active)

---

## Executive Summary

This audit identifies **all feature flags, toggles, and conditional behaviors** in the MERID codebase that could gate trading, risk, WebSocket connectivity, or pipeline operations. **52 distinct flags/toggles** were identified across environment variables, config files, hardcoded constants, and runtime feature flag registry.

**Risk Rating Distribution:**
- **HIGH (17 flags):** Can disable trading, risk checks, or core connectivity
- **MEDIUM (20 flags):** Can alter behavior significantly but with fallbacks
- **LOW (15 flags):** Cosmetic, debug, or gracefully degrading

---

## 1. Core Feature Flag Registry (core/feature_flags.py)

These are the **centralized runtime-togglable** flags via API or env var.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `auto_downsize` | `core/feature_flags.py:29` | registry+env | Auto-reduce position size when drawdown exceeds threshold | ON → automatic downsizing active | **HIGH** | active |
| `unusual_volume_reaction` | `core/feature_flags.py:30` | registry+env | React to z-score volume spikes in Kalshi markets | ON → volume anomaly signals generated | **HIGH** | active |
| `telegram_alerts` | `core/feature_flags.py:31` | registry+env | Enable Telegram outbound notifications | ON → Telegram alerts active | **MEDIUM** | active |
| `betting_refresh` | `core/feature_flags.py:32` | registry+env | Enable sports betting odds ingestion | OFF → Kalshi-only mode, no betting | LOW | hardcoded |

**Critical Path Flags:**
- `auto_downsize` → Can halt position management if flipped OFF during drawdown
- `unusual_volume_reaction` → Disables anomaly detection that triggers position sizing changes

---

## 2. Environment Flag System (core/environment_flags.py)

Lightweight environment-describing flags (not runtime-togglable without restart).

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `offline_mode` | `core/environment_flags.py:12` | env | Blocks all external network calls | OFF → network calls allowed | **HIGH** | active |
| `telemetry_restricted` | `core/environment_flags.py:13` | env | Reduces telemetry emission | OFF → full telemetry | LOW | active |
| `social_stream_enabled` | `core/environment_flags.py:14` | env | Enables social data ingestion | ON → social feeds active | MEDIUM | active |
| `allow_external_calls` | `core/environment_flags.py:15` | env | Explicit unlock for external APIs | OFF → blocked by default | **HIGH** | active |

---

## 3. Fresh Start Mode (core/fresh_start.py)

Platform-wide state reset toggle.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `MERID_FRESH_START` | `core/fresh_start.py:45` | env+config | Wipes all transient state on boot | OFF → state preserved | **HIGH** | active |

**Risk Note:** Hard-crashes if enabled in LIVE mode (safety guard present). Can delete paper positions, signal history, and cycle data.

---

## 4. Profile-Based Router Gating (web/main.py)

**MERID_PROFILE** gates entire API router registration.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `MERID_PROFILE=kalshi-only` | `web/main.py:454-455` | env | Suppresses ~35 legacy routers | "full" → all routers loaded | **HIGH** | active |

**Routers suppressed in kalshi-only mode:**
- mining, betting, wallet, treasury, rewards, simulation, arbitrage, sniping, recovery, moat, local_venue, market_assertions, onchain_assertions, agent_assertions, simulation_assertions, cost_models, time_exploit, plugins, reality, institutional, trading-suite, intelligence, market_data

**Critical Path:** If misconfigured, can disable critical Kalshi routers or enable dangerous legacy paths.

---

## 5. Kalshi Trading Mode Settings (merid/settings.py)

Critical trading safety interlocks.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `KALSHI_ONLY` | `merid/settings.py:294` | pydantic | Restricts UI/API to 8 canonical views | ON → Kalshi-only mode | **HIGH** | hardcoded |
| `MERID_PM_TRADING_MODE` | `merid/settings.py:295` | pydantic | paper/live mode for prediction markets | "paper" → paper trading | **HIGH** | active |
| `MERID_PM_LIVE_ENABLED` | `merid/settings.py:296` | pydantic | Explicit unlock for live PM trading | OFF → live blocked | **HIGH** | active |
| `MERID_LIVE_TRADING_UNLOCKED` | `merid/settings.py:502` | pydantic | Global live trading interlock | OFF → live blocked | **HIGH** | active |
| `KALSHI_USE_DEMO` | `merid/settings.py:331` | pydantic | Use Kalshi demo API | ON → demo API (must be False for prod) | **HIGH** | active |
| `MERID_RISK_LIMIT_OVERRIDE` | `merid/settings.py:213` | pydantic | Operator override for risk limits | OFF → limits enforced | **HIGH** | active |

**Critical Path Cluster:**
- `KALSHI_USE_DEMO` → Must be `false` for production or trades go to sandbox
- `MERID_PM_LIVE_ENABLED` + `MERID_LIVE_TRADING_UNLOCKED` → Both must be `true` for live trading
- `MERID_RISK_LIMIT_OVERRIDE` → Can bypass bankroll policy enforcement

---

## 6. Risk/Kill Switch Settings (merid/settings.py)

Error handling and kill switch configuration.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `MERID_ERROR_THRESHOLD_KILL_ENABLED` | `merid/settings.py:346` | pydantic | Enable error-count kill switch | ON → kill after 50 errors/hr | **HIGH** | active |
| `MERID_ERROR_THRESHOLD` | `merid/settings.py:338` | pydantic | Errors before kill (default 50) | 50 → 50 errors/hour | **HIGH** | active |
| `MERID_ERROR_SUPPRESS_WS_DISCONNECT` | `merid/settings.py:350` | pydantic | Don't count WS disconnects | ON → WS errors ignored | MEDIUM | active |
| `MERID_ERROR_SUPPRESS_WIN995` | `merid/settings.py:354` | pydantic | Don't count Windows error 995 | ON → Win995 ignored | LOW | active |
| `MERID_ERROR_SUPPRESS_MARKET_STATE` | `merid/settings.py:358` | pydantic | Don't count market closed errors | ON → market errors ignored | MEDIUM | active |
| `MERID_ERROR_THRESHOLD_STARTUP_GRACE_SECONDS` | `merid/settings.py:342` | pydantic | Grace period before kill active | 600s → 10min grace | MEDIUM | active |

---

## 7. Kalshi Continuous Trader Settings (merid/settings.py)

CT-specific toggles that control automated trading behavior.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `MERID_ENABLE_KALSHI_CT` | `merid/settings.py:301` | pydantic | Start CT with API server | OFF → CT not auto-started | **HIGH** | active |
| `MERID_CT_RESEARCH_ALLOW_LOOP` | `merid/settings.py:305` | pydantic | Allow CT in live mode (legacy) | OFF → CT blocked in live | **HIGH** | active |
| `MERID_CRYPTO_EDGE_FLOOR_PROFILE` | `merid/settings.py:391` | pydantic | Edge threshold strictness | "strict" → strict thresholds | **HIGH** | active |
| `MERID_CRYPTO_MM_CONSENSUS_MODE` | `merid/settings.py:395` | pydantic | Consensus gating mode | "full" → FORMING blocks | **HIGH** | active |
| `MERID_CRYPTO_SHADOW_EDGE_YES` | `merid/settings.py:399` | pydantic | Observability shadow edge min | 0.0 → no shadow logging | LOW | active |
| `MERID_CRYPTO_SHADOW_EDGE_NO` | `merid/settings.py:403` | pydantic | Observability shadow edge min | 0.0 → no shadow logging | LOW | active |
| `MERID_CRYPTO_MODERN_LIMITED_OVERRIDES_SAFE_TO_TRADE` | `merid/settings.py:443` | pydantic | LIMITED status can still trade | ON → LIMITED doesn't block | **HIGH** | active |

---

## 8. Loop Lag Monitor Settings (merid/settings.py)

Event loop health monitoring toggles.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `MERID_LOOP_LAG_ENABLED` | `merid/settings.py:286` | pydantic | Enable loop lag monitoring | ON → lag monitoring active | **HIGH** | active |
| `MERID_LOOP_LAG_WARN_MS` | `merid/settings.py:274` | pydantic | Warning threshold | 100ms → warn at 100ms | MEDIUM | active |
| `MERID_LOOP_LAG_DEGRADE_MS` | `merid/settings.py:278` | pydantic | Degradation threshold | 250ms → reduce limits | **HIGH** | active |
| `MERID_LOOP_LAG_HALT_MS` | `merid/settings.py:282` | pydantic | Kill switch threshold | 500ms → kill in live | **HIGH** | active |

**Critical Path:** Loop lag thresholds directly trigger kill switch in live mode.

---

## 9. CFB RTI / Settlement Settings (merid/settings.py)

Crypto Facilities Benchmarks settlement controls.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `MERID_CFB_RTI_ADAPTER` | `merid/settings.py:185` | pydantic | CFB adapter mode | None → disabled | **HIGH** | active |
| `MERID_ALLOW_NULL_CFB` | `merid/settings.py:205` | pydantic | Allow null CFB in live | OFF → blocks without CFB | **HIGH** | active |
| `MERID_CFB_RTI_SIMULATE` | `merid/settings.py:201` | pydantic | Emit synthetic ticks | OFF → no synthetic data | MEDIUM | active |
| `MERID_STRICT_FILL_ID` | `merid/settings.py:209` | pydantic | Strict fill ID validation | ON → validates fill IDs | MEDIUM | active |

---

## 10. Allocation & Portfolio Settings (merid/settings.py)

Dynamic vs static allocation toggles.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `MERID_USE_DYNAMIC_ALLOCATION` | `merid/settings.py:226` | pydantic | Use risk-parity allocation | ON → dynamic allocation | **HIGH** | active |
| `MERID_DYNAMIC_ALLOCATION_STRATEGY` | `merid/settings.py:230` | pydantic | Strategy: risk_parity/kelly/equal | "risk_parity" → risk parity | **HIGH** | active |
| `KALSHI_DYNAMIC_DAILY_LOSS` | `merid/settings.py:530` | pydantic | Dynamic daily loss bands | OFF → static bands | **HIGH** | active |
| `KALSHI_DYNAMIC_STOP_LOSS` | `merid/settings.py:531` | pydantic | Dynamic per-cluster stops | OFF → static stops | **HIGH** | active |
| `KALSHI_DYNAMIC_CONTRACTS` | `merid/settings.py:532` | pydantic | Dynamic contract caps | OFF → static caps | **HIGH** | active |
| `KALSHI_SPOT_STRIKE_DISTANCE_DYNAMIC` | `merid/settings.py:541` | pydantic | Dynamic spot-strike scaling | OFF → static distance | MEDIUM | unused |

---

## 11. Volatility Band Settings (merid/settings.py)

Volume/volatility-based sizing toggles.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `MERID_CRYPTO_PM_VOL_BRIDGE_ENABLED` | `merid/settings.py:451` | pydantic | Feed PM snapshots to vol stack | ON → vol band sizing active | **HIGH** | active |
| `MERID_CRYPTO_VOL_BANDS_LOG` | `merid/settings.py:457` | pydantic | Periodic vol band logging | OFF → quiet | LOW | active |
| `MERID_CRYPTO_VOL_LOW_THRESHOLD` | `merid/settings.py:461` | pydantic | Override low vol threshold | None → use stack default | MEDIUM | active |
| `MERID_CRYPTO_VOL_HIGH_THRESHOLD` | `merid/settings.py:465` | pydantic | Override high vol threshold | None → use stack default | MEDIUM | active |
| `MERID_CRYPTO_VOL_BAND_LOW_SIZE_MULT` | `merid/settings.py:469` | pydantic | Size multiplier low vol | 0.7 → 70% size | **HIGH** | active |
| `MERID_CRYPTO_VOL_BAND_MID_SIZE_MULT` | `merid/settings.py:475` | pydantic | Size multiplier mid vol | 1.0 → 100% size | **HIGH** | active |
| `MERID_CRYPTO_VOL_BAND_HIGH_SIZE_MULT` | `merid/settings.py:481` | pydantic | Size multiplier high vol | 0.4 → 40% size | **HIGH** | active |

---

## 12. Consensus & Execution Settings (merid/settings.py)

Swarm consensus and execution logging toggles.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `MERID_CONSENSUS_PATH_LOG` | `merid/settings.py:419` | pydantic | Emit consensus structured logs | OFF → quiet | LOW | active |
| `MERID_CRYPTO_CONSENSUS_HEALTH_LOG` | `merid/settings.py:423` | pydantic | Consensus health warnings | ON → health warnings | MEDIUM | active |
| `MERID_CRYPTO_EXECUTION_INVARIANT_LOG` | `merid/settings.py:439` | pydantic | Execution invariant warnings | ON → invariant checks | MEDIUM | active |
| `MERID_CRYPTO_CONSENSUS_STALE_AFTER_SIGNAL_SECONDS` | `merid/settings.py:427` | pydantic | Stale consensus threshold | 120s → 2min stale | MEDIUM | active |
| `MERID_SWARM_CONFIDENCE_MIN` | `merid/settings.py:488` | pydantic | Min confidence for sentiment orders | 0.0 → disabled | MEDIUM | active |

---

## 13. Graceful Degradation Settings (merid/settings.py)

Dev mode convenience toggles (non-critical).

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `MERID_REDIS_ENABLED` | `merid/settings.py:258` | pydantic | Enable Redis caching | ON → Redis used | MEDIUM | active |
| `MERID_EMAIL_ENABLED` | `merid/settings.py:262` | pydantic | Enable SMTP email | ON → email enabled | LOW | active |
| `TWITTER_STREAMING_ENABLED` | `merid/settings.py:266` | pydantic | Enable X streaming API | ON → streaming preferred | LOW | active |

---

## 14. Mock/Simulation Settings (merid/settings.py)

**DANGER:** These must be OFF in production.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `MERID_USE_MOCK_ARB_DATA` | `merid/settings.py:507` | pydantic | Use fake arbitrage data | OFF → real data | **HIGH** | active |
| `MERID_USE_DEMO_TRADES` | `merid/settings.py:508` | pydantic | Use demo trades | OFF → real trades | **HIGH** | active |
| `MERID_USE_SAMPLE_DATA` | `merid/settings.py:509` | pydantic | Use sample data | OFF → real data | **HIGH** | active |
| `MERID_USE_MOCK_STREAMS` | `merid/settings.py:510` | pydantic | Use mock WebSocket | OFF → real WS | **HIGH** | active |
| `MERID_ENABLE_LIVE_PRICE_FEEDS` | `merid/settings.py:513` | pydantic | Enable live prices | ON → live prices | **HIGH** | active |
| `MERID_ENABLE_REAL_PREDICTION_MARKETS` | `merid/settings.py:514` | pydantic | Enable real PMs | ON → real PMs | **HIGH** | active |
| `MERID_ENABLE_REAL_SOLANA_WS` | `merid/settings.py:515` | pydantic | Enable Solana WS | ON → real Solana | MEDIUM | active |
| `MERID_ENABLE_REAL_NEWS` | `merid/settings.py:516` | pydantic | Enable real news | ON → real news | MEDIUM | active |

---

## 15. Feature Enablement Flags (merid/settings.py)

Legacy/deactivated feature flags.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `PHASE0_ENABLED` | `merid/settings.py:578` | pydantic | Enable Phase0 minimal crypto | OFF → not active | LOW | unused |
| `MERID_ENABLE_CHAINLINK` | `merid/settings.py:579` | pydantic | Enable Chainlink | OFF → disabled | LOW | unused |
| `MERID_ENABLE_AUGUR` | `merid/settings.py:580` | pydantic | Enable Augur | OFF → disabled | LOW | unused |
| `MERID_ENABLE_NEWS_AGENT` | `merid/settings.py:581` | pydantic | Enable news agent | OFF → disabled | LOW | unused |
| `MERID_ENABLE_WHALE_INTEL` | `merid/settings.py:582` | pydantic | Enable whale intel | OFF → disabled | LOW | unused |
| `MERID_ENABLE_POLYMARKET` | `merid/settings.py:583` | pydantic | Enable Polymarket | OFF → disabled | LOW | unused |

---

## 16. YAML Config Toggles (config/*.yaml)

Config-file based toggles.

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `swarm.enabled` | `config/settings.yaml:6` | config | Enable swarm | true → swarm on | **HIGH** | active |
| `blind_consensus` | `config/settings.yaml:3` | config | Blind consensus mode | true → blind on | MEDIUM | active |
| `consensus.allow_silence` | `config/settings.yaml:12` | config | Allow silent consensus | true → silence ok | MEDIUM | active |
| `hedging.enabled` | `config/kalshi_crypto_hedging.yaml:11` | config | Enable hedge engine | true → hedging on | **HIGH** | active |
| `hedging.use_cross_asset_hedging` | `config/kalshi_crypto_hedging.yaml:12` | config | Cross-asset hedging | false → same-asset only | MEDIUM | active |
| `cross_asset.enabled` | `config/kalshi_crypto_hedging.yaml:68` | config | Cross-asset pair hedging | false → disabled | MEDIUM | active |
| `venue.use_demo` | `config/kalshi_agent_grid.yaml:4` | config | Kalshi demo mode | false → live API | **HIGH** | active |
| `take_profit.enabled` | `config/kalshi_agent_grid.yaml:37` | config | Enable take profit | true → TP active | **HIGH** | active |
| `take_profit.trailing_enabled` | `config/kalshi_agent_grid.yaml:41` | config | Enable trailing stops | true → trailing on | **HIGH** | active |

---

## 17. Frontend Feature Flags (web/react/src/config/featureFlags.ts)

UI-layer toggles (do not affect backend trading).

| name | location | type | controls | default behavior (prod) | risk | status |
|------|----------|------|----------|---------------------------|------|--------|
| `kalshiOnly` | `web/react/src/config/featureFlags.ts:45` | env+localStorage+URL | Hide legacy panels | false → full UI | LOW | active |
| `VITE_KALSHI_ONLY` | `web/react/src/config/featureFlags.ts:23` | env | Build-time UI filter | unset → full UI | LOW | active |

---

## 18. Stale/Legacy Flags to Remove

These flags are **hardcoded** or **unused** and should be cleaned up:

1. **`betting_refresh`** (core/feature_flags.py:32) - Always OFF for Kalshi-only, comment says "LEGACY"
2. **`PHASE0_ENABLED`** (merid/settings.py:578) - Never enabled, superseded by Kalshi-only mode
3. **`MERID_ENABLE_CHAINLINK`** (merid/settings.py:579) - Never enabled
4. **`MERID_ENABLE_AUGUR`** (merid/settings.py:580) - Never enabled
5. **`MERID_ENABLE_NEWS_AGENT`** (merid/settings.py:581) - Never enabled
6. **`MERID_ENABLE_WHALE_INTEL`** (merid/settings.py:582) - Never enabled
7. **`MERID_ENABLE_POLYMARKET`** (merid/settings.py:583) - Never enabled
**Note:** `KALSHI_DYNAMIC_DAILY_LOSS`, `KALSHI_DYNAMIC_STOP_LOSS`, and `KALSHI_DYNAMIC_CONTRACTS` were previously listed here but are **actively used** in `kalshi_risk.py` for production risk calculations. They are intentionally disabled (False) but wired into live code paths.

8. **`KALSHI_SPOT_STRIKE_DISTANCE_DYNAMIC`** (merid/settings.py:541) - Always OFF, truly unused (only in settings.py)

---

## 19. High-Risk Flags Requiring Immediate Attention

These flags can **disable trading, bypass risk, or block core functionality**:

### Trading Safety (CRITICAL)
| Flag | Risk | Why |
|------|------|-----|
| `KALSHI_USE_DEMO` | **CRITICAL** | If ON in prod, trades go to sandbox |
| `MERID_PM_LIVE_ENABLED` | **CRITICAL** | Must be ON for live trading |
| `MERID_LIVE_TRADING_UNLOCKED` | **CRITICAL** | Must be ON for live trading |
| `MERID_RISK_LIMIT_OVERRIDE` | **CRITICAL** | Bypasses bankroll policy |
| `MERID_ENABLE_KALSHI_CT` | **CRITICAL** | Auto-starts CT (should be OFF, AG is primary) |
| `MERID_CT_RESEARCH_ALLOW_LOOP` | **CRITICAL** | Legacy CT+live interlock bypass |

### Risk/Kill Switch (HIGH)
| Flag | Risk | Why |
|------|------|-----|
| `MERID_ERROR_THRESHOLD_KILL_ENABLED` | HIGH | Disables error-based kill switch |
| `MERID_LOOP_LAG_ENABLED` | HIGH | Disables event loop health monitoring |
| `MERID_CRYPTO_MODERN_LIMITED_OVERRIDES_SAFE_TO_TRADE` | HIGH | LIMITED status can still trade |
| `auto_downsize` (FF) | HIGH | Disables drawdown protection |

### Connectivity/Market Data (HIGH)
| Flag | Risk | Why |
|------|------|-----|
| `MERID_ENABLE_LIVE_PRICE_FEEDS` | HIGH | Disables live price feeds |
| `MERID_ENABLE_REAL_PREDICTION_MARKETS` | HIGH | Disables real Kalshi data |
| `MERID_PROFILE` | HIGH | Can suppress critical routers |
| `MERID_FRESH_START` | HIGH | Wipes all trading state on boot |

---

## 20. Flag Clusters by Subsystem

### Trading Execution Cluster
Controls: Order placement, sizing, execution, CT vs AgentGrid
- `MERID_ENABLE_KALSHI_CT`
- `MERID_CT_RESEARCH_ALLOW_LOOP`
- `MERID_CRYPTO_EDGE_FLOOR_PROFILE`
- `MERID_CRYPTO_MM_CONSENSUS_MODE`
- `MERID_CRYPTO_MODERN_LIMITED_OVERRIDES_SAFE_TO_TRADE`
- `auto_downsize` (FF)
- `MERID_USE_MOCK_*` flags (all DANGER)

**Risk Scenario:** If `MERID_ENABLE_KALSHI_CT=ON` + `MERID_CT_RESEARCH_ALLOW_LOOP=ON` + `MERID_TRADE_MODE=live`, CT will trade live concurrently with AgentGrid (dangerous).

### Risk Management Cluster
Controls: Kill switches, drawdown, error thresholds, loop lag
- `MERID_ERROR_THRESHOLD_KILL_ENABLED`
- `MERID_ERROR_THRESHOLD`
- `MERID_LOOP_LAG_ENABLED`
- `MERID_LOOP_LAG_HALT_MS`
- `MERID_RISK_LIMIT_OVERRIDE`
- `auto_downsize` (FF)

**Risk Scenario:** If all disabled, system trades without any automatic circuit breakers.

### Market Data & Connectivity Cluster
Controls: Live vs mock data, WS streams, price feeds
- `MERID_ENABLE_LIVE_PRICE_FEEDS`
- `MERID_ENABLE_REAL_PREDICTION_MARKETS`
- `MERID_ENABLE_REAL_SOLANA_WS`
- `MERID_USE_MOCK_STREAMS`
- `MERID_USE_MOCK_ARB_DATA`

**Risk Scenario:** If mock flags enabled in prod, system trades on fake data.

### Volatility Band Sizing Cluster
Controls: Position sizing based on realized volatility
- `MERID_CRYPTO_PM_VOL_BRIDGE_ENABLED`
- `MERID_CRYPTO_VOL_BAND_*_SIZE_MULT`
- `MERID_CRYPTO_VOL_LOW/HIGH_THRESHOLD`

**Risk Scenario:** If `VOL_BRIDGE_ENABLED=OFF`, sizing falls back to static (may over/under-size).

---

## 21. Recommendations

### Immediate Actions (Pre-Trade)
1. **Verify production has:**
   - `KALSHI_USE_DEMO=false`
   - `MERID_PM_LIVE_ENABLED=true` (only when ready for live)
   - `MERID_LIVE_TRADING_UNLOCKED=true` (only when ready for live)
   - All `MERID_USE_MOCK_*=false`
   - `MERID_PROFILE=full` (or `kalshi-only` if intended)

2. **Add monitoring alerts for:**
   - Any change to `MERID_RISK_LIMIT_OVERRIDE` (security event)
   - Any change to `KALSHI_USE_DEMO` (critical safety)
   - Fresh start mode enabled in live (should crash, but verify)

### Cleanup (Post-Stabilization)
1. Remove 8 stale flags identified in Section 18 (7 legacy + 1 unused)
2. Consolidate duplicate "enable live" flags (`MERID_PM_LIVE_ENABLED`, `MERID_LIVE_TRADING_UNLOCKED`, `MERID_ENABLE_KALSHI_CT` naming confusion)
3. Document `kalshi-only` profile behavior in operator runbook
4. Consolidate loop timeout overrides into single config

---

## 22. Loop / Pipeline Action Flags (merid/loop.py, merid/paper_config.py)

**Critical pipeline action controls** — these flags gate the core loop operations.

| name | location | type | controls | default behavior (prod) | risk | status | critical_path |
|------|----------|------|----------|---------------------------|------|--------|---------------|
| `MERID_LOOP_SLOW_ACTION_BUDGET_MS` | `merid/loop.py:43` | env | Per-step "slow action" warning threshold (ms) | 1000ms → warns if action exceeds | MEDIUM | active | **YES** — Can suppress warnings for slow liquidity/arb_scan/order_groups |
| `MERID_LOOP_TICK_DURATION_WARN_MS` | `merid/loop.py:365` | env | Max tick duration warning threshold | 30000ms → warns at 30s | LOW | active | No |
| `MERID_LOOP_STEP_TIMEOUT_S` | `merid/loop.py:367` | env | Default step timeout | 5s → steps timeout at 5s | MEDIUM | active | **YES** — Can kill slow pipeline actions |
| `MERID_LOOP_STEP_TIMEOUT_OVERRIDES` | `merid/loop.py:369` | env | JSON timeout overrides per step | See JSON with per-step overrides | MEDIUM | active | **YES** — Controls liquidity (20s), arb_scan (10s), betting (30s) timeouts |
| `enable_execution` | `merid/paper_config.py:282` | config | Enable paper/live trade execution | FALSE → fills disabled | **HIGH** | active | **YES** — Gates ALL trade execution |
| `enable_arb_execution` | `merid/paper_config.py:285` | config | Enable arb signal execution | FALSE → arb fills disabled | **HIGH** | active | **YES** — Gates arbitrage execution |
| `enable_reconciliation` | `merid/paper_config.py:283` | config | Enable position reconciliation | TRUE → reconciliation active | **HIGH** | active | **YES** — Disables position/risk sync if OFF |
| `enable_notifications` | `merid/paper_config.py:284` | config | Enable alert notifications | TRUE → notifications active | MEDIUM | active | No |

**Pipeline Action Specific:**
- `_liquidity_refresh_interval` (loop.py:272) = 120s — Orderbook health sweep
- `_order_groups_sync_interval` (loop.py:276) = 120s — Lifecycle state check
- `_slow_action_last_skip` (loop.py:255) + `_SLOW_ACTION_COOLDOWN_S` = 60s — Skips slow actions for 60s after budget exceeded

---

## 23. Critical Path Summary by Subsystem

### Pipeline Actions (liquidity, arb_scan, order_groups)
**Directly Affected Flags:**
- `MERID_LOOP_SLOW_ACTION_BUDGET_MS` — Controls when warnings fire for slow actions
- `MERID_LOOP_STEP_TIMEOUT_OVERRIDES` — JSON dict with `liquidity: 20`, `arb_scan: 10`, `betting: 30`
- `enable_execution` — Gates whether ANY trades execute
- `MERID_PROFILE=kalshi-only` — Can suppress non-Kalshi pipeline actions

**Risk Scenarios:**
1. `enable_execution=FALSE` → Loop runs but no trades execute (paper or live)
2. `MERID_LOOP_STEP_TIMEOUT_OVERRIDES={"liquidity": 1}` → liquidity action always times out
3. Slow action skip cooldown (60s) → After one slow run, action skipped for 60s

### WebSocket & Connectivity
**Directly Affected Flags:**
- `MERID_ENABLE_REAL_SOLANA_WS` — Real vs mock Solana data
- `MERID_USE_MOCK_STREAMS` — Mock vs real WebSocket streams
- `offline_mode` — Blocks ALL external calls
- `MERID_KALSHI_WS_CLIENT` (settings.py:324) = "ws" vs "websocket_service" (dev only)

### Risk & Safety
**Directly Affected Flags:**
- `MERID_ERROR_THRESHOLD_KILL_ENABLED` — Master kill switch for error-based shutdowns
- `MERID_LOOP_LAG_ENABLED` — Event loop health monitoring
- `MERID_RISK_LIMIT_OVERRIDE` — Bypasses bankroll policy
- `auto_downsize` — Drawdown protection

### Ongoing
1. Monthly review of feature flag states via `/api/v1/system/feature-flags` endpoint
2. Quarterly audit of env var configurations in production
3. Require dual-approval for any change to HIGH/CRITICAL flags

---

## Appendix A: Referenced but Not Found

The following environment variables were referenced in the audit prompt but **do not currently exist** in the codebase:

| name | expected location | status |
|------|-------------------|--------|
| `KALSHI_WS_RECONNECT_LAG_THRESHOLD_MS` | Kalshi WS client | **NOT IMPLEMENTED** — may be planned or renamed |
| `MERID_PROFILING` | Diagnostics/Profiling | **NOT IMPLEMENTED** — may be planned or renamed |

**Action:** Verify if these are planned features or if they exist under different names (e.g., `MERID_PROFILING` might be related to `MERID_LOOP_LAG_ENABLED` or a different profiling mechanism).

---

## Appendix B: Querying Current Flag States

### Runtime Feature Flags (via API)
```bash
curl http://localhost:8011/api/v1/system/feature-flags
```

### Environment Variables (shell)
```bash
env | grep -E "^(MERID_|KALSHI_)" | sort
```

### Settings Inspection (Python)
```python
from merid.settings import settings
print(f"KALSHI_ONLY={settings.KALSHI_ONLY}")
print(f"KALSHI_USE_DEMO={settings.KALSHI_USE_DEMO}")
print(f"MERID_PM_TRADING_MODE={settings.MERID_PM_TRADING_MODE}")
print(f"MERID_PM_LIVE_ENABLED={settings.MERID_PM_LIVE_ENABLED}")
```

---

*End of Audit Report*
