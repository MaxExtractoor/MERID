# Phase 21f – Self-healing Social & Bot Layer

_Status: Draft v0.1 (2026-01-15)_

Phase 21f ensures MERID’s social ingestion and bot interfaces remain trustworthy under failure. The scope covers ingestion resiliency, bot auto-recovery, and data-quality monitoring.

---

## 1. Goals

1. **Make social ingestion non-critical** – degraded feeds must not halt trading; health signals should guide exposure.
2. **Self-heal bot interfaces** – X/Twitter bot, Telegram console, and other social agents auto-detect disconnects and recover with bounded backoff.
3. **Feed failures into learning loops** – capture incidents, data drift, and latency spikes for tuning thresholds and alerts.
4. **Expose health + data quality** – operators can query live ingest freshness, error counts, fallback activations, and safety posture.

---

## 2. Architecture Overview

```
X/Twitter API       Telegram API         Other Social Feeds
      \                 |                   /
       \                |                  /
        --> Ingestion Workers (rate-limit aware) --> Social Data Quality Monitor
                   |                                          |
                   v                                          v
            SocialBotHealthMonitor <----> Observability Stack (metrics/events)
                   |
         +---------+-----------+
         |                     |
   XBotService            TelegramBotService
         |                     |
   Backend API Surface   Ops/User Consoles
         |
   Risk + Telemetry Layers
```

Key components:
- **SocialBotHealthMonitor**: tracks component heartbeats, failure counts, backoff, and recovery actions.
- **SocialDataQualityMonitor**: measures ingestion freshness, drop rates, and latency per source.
- **Observability Stack**: receives structured events (fallback activation, circuit breakers, safe-mode entries) for dashboards.

---

## 3. Functional Requirements

### 3.1 Social Ingestion Resilience
- Rate-limit handling with adaptive backoff (min/max bounds).
- Graceful degradation (pauses classification but keeps broker alive).
- Fallback fetcher path (cached copy / last-known data) to maintain telemetry.
- Alert when data staleness exceeds configurable SLA.

### 3.2 Bot Self-healing
- Automatic reconnect loop with capped exponential backoff.
- Component registration with health monitor (name, type, auto-reconnect flag).
- Rolling heartbeat updates; missed heartbeat triggers recoveries.
- Command processing errors recorded with correlation IDs and forwarded to breach detection.

### 3.3 Failure Learning & Alerting
- Failure history persisted in monitor (timestamp, recoverable flag, evidence).
- Metrics forwarded to `event_stream` (`social_health`, `telegram_command`, etc.).
- Operators can query `/x/status` for `social_bot_health` summary.

### 3.4 Data Quality Monitoring
- Track batches per source: counts, first/last timestamps, latency distribution.
- Detect stale feeds (no data for N minutes) and high error rates.
- Provide JSON status for dashboards and CLI.

---

## 4. Implementation Tasks

1. **Health Monitor Enhancements**
   - Add component registry, heartbeat/failure tracking, backoff calculators, and recovery actions.
   - Integrate with `SocialBotHealthMonitor` singleton and ObservabilityStack logs.

2. **X/Twitter Ingestion Integration**
   - Wrap fetch loop with monitor hooks; publish data-quality stats per batch.
   - Record rate-limit hits and HTTP errors as degradations.

3. **Bot Service Integration**
   - Wire X bot + Telegram bot services to register components, emit heartbeats, and log backend failures.
   - Surface health snapshot via `/x/status`.

4. **Data Quality Monitor**
   - New `social/social_data_quality.py` module with per-source metrics and SLA evaluation.
   - Provide `get_social_data_quality_report()` for APIs + dashboards.

5. **Observability Hooks**
   - Publish `social_health` events to `event_stream` when status changes.
   - Record metrics in Observability Stack (latency, drop rate, fallback count).

6. **Tests** (Phase 2)
   - Unit tests for monitor state transitions, rate-limit scenarios, and data-quality alerts.

---

## 5. Configuration & Ops

- Config knobs: heartbeat interval, stale threshold (default 5 min), max backoff (5 min), recovery window (15 min), alert channels.
- Expose environment variables for Telegram service token, fallback endpoints, and quality thresholds.
- Document runbooks for manual intervention (manual reconnect, override kill switches).

---

Deliverable: resilient social/bot layer with measurable health, automated recovery, and operator visibility.
