# KALSHI Lifecycle × Startup / Shutdown Matrix

> Single-page reference for every phase of the MERID-Kalshi trading pipeline.
> Use this table alongside `docs/KALSHI_INTEGRATION_AUDIT_REPORT_2026.md`
> and the ops runbooks in `ops/runbooks/` when onboarding or responding to incidents.

**Last updated:** 2026-03-28  
**Scope:** All 8 lifecycle phases (DISCOVER → ANALYZE → CONSENSUS → SIZE → EXECUTE → MONITOR → PROMOTE → PROTECT)

---

## Lifecycle Matrix

| Phase | Startup pre-conditions | Runtime invariants | Shutdown actions |
|-------|------------------------|-------------------|-----------------|
| **DISCOVER** | Kalshi REST client initialised and authenticated; market discovery filters (status, min/max close timestamps, asset tickers) loaded from config; periodic scheduler registered and first discovery job enqueued; market catalog non-empty after `start()` (fail-fast if zero markets returned). | Scheduler fires on configured cadence; every received market is schema-validated (Pydantic); SLA breach alerts fired if discovery latency exceeds threshold; catalog index kept fresh via WebSocket push + periodic REST poll. | Scheduler stopped; no new discovery jobs enqueued; in-flight REST calls allowed to complete or timed out; final catalog snapshot persisted to DB. |
| **ANALYZE** | Market snapshot store accessible; signal builder registry wired to at least one builder per supported asset/timeframe pair; sentiment bus (`SentimentBusV2`) and vol-targeting feed initialised; downstream errors isolated (discovery must not crash on analyzer failure). | Every discovered market has at least one active analyzer pipeline instance; analyzer errors are logged without propagating to DISCOVER; stale-signal detection rejects snapshots older than configured TTL; clock-skew monitoring active. | All analyzer tasks stopped or marked read-only; no new executable signals emitted; last computed signals flushed to signal store for CONSENSUS to drain. |
| **CONSENSUS** | Swarm matrix subscriptions established; at least one agent opinion registered per supported domain; consensus artifact store (DB table / in-memory cache) initialised; anti-herding check configured; can operate on historical snapshots if Kalshi is unavailable. | `TaCoConsensusCoordinator` produces a `TradePlan` for every qualifying signal; thread-safe consensus cache prevents race conditions; veto mechanism reachable; decay-aware weighting applied; consensus state persisted after each cycle. | All swarm workers stopped; last consensus state flushed and visible in UI; no new `TradePlan` objects enqueued for SIZE. |
| **SIZE** | Bankroll config, Kelly fraction, vol-scaling, and drawdown parameters loaded and validated (no hard-coded dollar values); `KalshiContinuousTrader` subscribed to `ApprovedSignal` bus; absolute position caps enforced; division-by-zero guard active on Kelly formula. | Position sizes computed for every `ApprovedSignal` received; per-asset and portfolio caps checked before emitting a sized intent; fill-quality feedback loop updates sizing parameters; dry-run flag respected (sizes computed but not forwarded to EXECUTE when off). | No worker consuming `ApprovedSignal` bus for live sizing; in-flight sizing computations allowed to complete; results logged even if EXECUTE is already halted. |
| **EXECUTE** | Auth credentials (API key + RSA PEM path) loaded from env/secrets, not hard-coded; correct environment selected (`MERID_ENV=prod\|sim`); dry-run flag defaults to **on** at first boot; rate-limit bucket initialised; execution adapters ready but gated by global execution flag. | Global execution flag is the single on/off switch — no order reaches Kalshi without it being enabled; every order attempt logged with intent ID, symbol, side, size, and result; open-order reconciliation runs on a heartbeat; iceberg order splitting active for large sizes. | Global execution flag flipped off **first** (no new orders); in-flight order submissions awaited up to configured timeout; open "working" orders cancelled per policy; all order states persisted; adapters closed; Kalshi WebSocket sessions terminated. |
| **MONITOR** | Metrics exporters mounted (Prometheus / structured JSON); log handlers attached to all phases; health-check endpoints (`/health`, `/api/v1/dependencies/health`) live; UI widgets for per-phase status and Kalshi connection tiles registered; at least one heartbeat per phase configured. | Per-phase heartbeat emits on each cycle; Kalshi REST ping and WebSocket staleness check run on configured interval; fill-quality anomaly detection active; position reconciliation compares DB state vs Kalshi API on each heartbeat; alert manager fires on SLA breach or anomaly. | Final metrics/log flush before process exit; UI set to "offline / maintenance" state; all open positions and orders visible in UI as of last heartbeat; heartbeat tasks stopped cleanly. |
| **PROMOTE** | Feature flags and deployment states (paper → shadow → canary → live) registered in config and surfaced in UI (Lane Control view); `DeploymentController` initialised; auto-promotion gate thresholds (Sharpe, win-rate, calibration error) loaded from config. | New strategies or markets enter via paper shadow mode before reaching live; auto-promoter checks performance gates before advancing any agent; canary routes limited to configured share of traffic; promotion/demotion events logged and visible in UI; UI provides confirmation step before flag toggle. | Feature flags reset to safe defaults; canary routes turned off; any shadow-mode agents demoted to paper; promotion audit log flushed; Lane Control UI reflects final deployment state. |
| **PROTECT** | Global kill-switch wired and testable before go-live; per-market, per-asset, per-day, and portfolio loss caps loaded and validated; `KalshiRiskManager` initialised with `KalshiRiskConfig`; kill-switch dry-run mode available for pre-flight checks; PROTECT phase has no dependency on Kalshi health. | Kill-switch check runs before every order submission; per-day loss cap monitored on every fill; portfolio drawdown circuit breaker fires if threshold crossed; PROTECT state visible in UI (KillSwitchView / OperatorDashboard); kill-switch engaged independently of other phases — EXECUTE stops immediately. | Kill-switch engaged **before** process exit on any controlled shutdown; final cap utilisation written to logs; UI shows "PROTECT engaged" badge; no new orders possible until kill-switch explicitly reset by operator. |

---

## Startup Order (dependency chain)

```
1. Config & secrets validated (API keys, PEM paths, bankroll limits, env selection)
2. DB migrations completed (signals, orders, positions, lifecycle logs)
3. Signal/consensus/execution buses created and smoke-tested
4. Kalshi REST connectivity test (ping + markets/list filtered to crypto) logged
5. PROTECT  — risk caps and kill-switch loaded
6. MONITOR  — exporters, health checks, heartbeat tasks started
7. DISCOVER — market catalog populated, scheduler registered
8. ANALYZE  — signal builders wired to catalog
9. CONSENSUS — swarm workers subscribed to signal bus
10. SIZE    — bankroll config and Kelly parameters loaded; dry-run ON
11. PROMOTE — feature flags and deployment states registered
12. EXECUTE — adapters opened; dry-run flag may be lifted by operator
```

**Green-board condition (acceptance test):** All lifecycle heartbeats present · at least one crypto market discovered · at least one `ApprovedSignal` produced · one sizing computed · one test order either sent (sandbox) or simulated (dry-run).

---

## Shutdown Order (safe unwind)

```
1. PROTECT  — global execution flag off; kill-switch engaged; log + UI confirm
2. DISCOVER / ANALYZE — schedulers stopped; analyzers marked read-only
3. Signal buses drained up to time limit; dropped work logged explicitly
4. EXECUTE  — in-flight submissions awaited; open orders cancelled per policy;
               Kalshi sessions / WebSocket connections closed
5. CONSENSUS / SIZE — workers stopped; last state persisted
6. PROMOTE  — flags reset to safe defaults
7. MONITOR  — final metrics/log flush; UI set to offline/maintenance
```

**Post-abnormal-stop checklist:** On next startup, compare open positions and orders from Kalshi API against DB; alert on any mismatch; require operator acknowledgement before re-enabling EXECUTE.

---

## Trigger surfaces

| Trigger | Effect |
|---------|--------|
| OS signal (`SIGTERM`/`SIGINT`) | Graceful shutdown via ASGI lifespan teardown |
| Admin API / UI "Pause trading" button | EXECUTE → halted; PROTECT → kill-switch on |
| CI/CD deploy | Rolling restart; EXECUTE disabled until readiness probe passes |
| Error-threshold breach | Alert fired; optionally auto-halts EXECUTE |
| Kalshi maintenance detection | DISCOVER/EXECUTE → degraded; ANALYZE/CONSENSUS continue on cached data |
| Risk breach (daily loss / drawdown cap) | PROTECT auto-engages; EXECUTE stops immediately |

---

## Cross-references

| Resource | Path |
|----------|------|
| Full phase audit with findings & fixes | `docs/KALSHI_INTEGRATION_AUDIT_REPORT_2026.md` |
| Gap analysis | `docs/KALSHI_SWARM_GAP_ANALYSIS.md` |
| UI component map & 8-step workflow | `docs/UI/kalshi_workflow.md` |
| Dependency health API | `merid/monitoring/dependency_health.py` |
| Kill-switch implementation | `merid/risk/kill_switches.py` |
| Promotion engine | `merid/risk/promotion_engine.py` |
| Continuous trader / filter pipeline | `merid/trading/kalshi_continuous_trader.py` |
| Execution coordinator | `execution/execution_coordinator.py` |
| Database / service runbooks | `ops/runbooks/` |
