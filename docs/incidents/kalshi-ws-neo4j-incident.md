# Kalshi WebSocket Overload and Neo4j Memory Incident

## Incident Summary
- Breaking News Analysis energy kicked off, invoking all agents; orchestration continued despite downstream errors.
- Kalshi WebSocket feed flooded the bounded queue (max 4096) causing repeated drops of oldest messages while still accepting new ones.
- Orderbook deltas arrived for markets without a cached snapshot, so many deltas were discarded outright.
- Neo4j history lookups failed with "memory unavailable," removing long-term context for agents that relied on it.
- Strategy, risk, and other agents processed the energy on partial or missing market data, raising the chance of acting on stale state.
- No circuit breaker halted trading; the system kept running in degraded mode.
- Observability showed gaps: no per-market drop metrics, no rate vs processing measurements, and no automatic backpressure escalation.

## 1) Timeline & Components
- T0: Breaking News Analysis energy created; core orchestrator fans out to archivist, analyst, strategy, synthesizer, risk, and skeptic agents.
- T0+small: Kalshi WebSocket listener (`merid/event_venues/kalshi/ws.py`) starts receiving ticker/orderbook messages; queue begins to fill.
- T0+? : Queue reaches maxsize=4096; warnings log "WS message queue full -- dropped oldest message (queue_size=4096)" indicating producer > consumer throughput and loss of oldest messages.
- T0+? : Orderbook deltas arrive for markets lacking snapshots; logs state "Dropping orderbook delta for <market> -- no snapshot cached yet", so deltas are ignored and state cannot advance.
- T0+? : Archivist agent queries Neo4j for history; returns "History query failed: Neo4j memory unavailable", removing historical context.
- T0+? : Despite above, agents continue the energy; strategies and risk operate on incomplete orderbooks and missing history, with no halt or backpressure propagated.

## 2) Root Causes
- WebSocket queue saturation: Single async queue (max 4096) accepts all messages; when callback processing slows (agent fan-out, heavy computation, or blocking I/O), producer keeps enqueuing and drops oldest. There is no adaptive backpressure to slow subscriptions, shard by market, or shed load by priority, so sustained bursts exhaust the queue and lose data.
- Deltas without snapshots: The code applies a hard check that drops any delta when market_id not in the snapshot cache. Causes include subscribing to deltas before requesting snapshots, snapshots being evicted on reconnect while deltas still arrive, or blank/unknown market_ids in messages. There is no retry/resubscribe to refresh missing snapshots, nor buffering of deltas until a snapshot lands.
- Neo4j memory unavailable: Suggests heap or page cache exhaustion, likely from concurrent heavy history queries triggered by the energy (multiple agents querying in parallel), lack of bounded query shapes/index use, and possible pile-up if retries occur while DB is already constrained. With memory unavailable, archivist cannot supply context; yet downstream agents proceed.

## 3) Impact on Trading & Risk
- Orderbook accuracy: Dropped messages and discarded deltas mean bid/ask levels and seq numbers can regress or stall; snapshots are stale, making local book inconsistent with venue.
- Strategy decisions: Signals may be generated on outdated spreads/liquidity; edges can be overstated or flip sign if bids/asks moved. Momentum or microstructure models become untrustworthy.
- Risk controls: Position sizing and exposure limits using stale books may under-estimate risk; guardrails depending on recent liquidity can misfire.
- Position management/PnL: Execution logic may chase prices that no longer exist, increasing rejects/slippage; hedges may lag, widening PnL volatility.
- Degraded vs unsafe: Occasional drops with rapid recovery are degraded-but-observable; sustained queue saturation, repeated delta drops, or Neo4j unavailable during decision windows are unsafe-to-trade and should trigger circuit breakers.

## 4) Instrumentation & Metrics Plan
- WS rate vs throughput: Counters `kalshi_ws.messages_received_total`, `kalshi_ws.messages_processed_total`; gauge/histogram `kalshi_ws.process_time_ms` and `kalshi_ws.loop_lag_ms`. Add meter `kalshi_ws.ingress_rate_per_sec` vs `kalshi_ws.process_rate_per_sec`.
- Queue health: Gauge `kalshi_ws.queue_depth` with `queue_max`; counter `kalshi_ws.queue_dropped_total` labeled by `channel` and `market_id`; structured log `{"evt":"ws_queue_drop","queue_depth":4096,"channel":type,"market":ticker}`.
- Snapshot vs delta sequencing: Counter `kalshi_ws.delta_before_snapshot_total{market_id}`; log `{"evt":"delta_without_snapshot","market":m,"seq":seq,"ts":...}`; metric for snapshot age `kalshi_ws.snapshot_age_ms{market_id}` to detect stale caches.
- Market ID validation: Counter `kalshi_ws.blank_market_id_total`; log and sample payloads when `ticker` is missing.
- Neo4j health: Gauges for heap, page cache, and pool in-use; histogram `neo4j.query_latency_ms` tagged by query class; counter `neo4j.errors_total{code}` with `memory_unavailable` bucket. Emit structured log `{"evt":"neo4j_error","code":"memory_unavailable","query":"history_lookup","retries":n}`.
- Agent-level impact: Trace/log when agents skip or downgrade actions due to data-quality flags; metric `trading.data_quality_score` aggregated from WS and Neo4j signals.

## 5) Code & Architecture Changes
- Backpressure and sharding for Kalshi WS: Introduce per-channel/per-market queues with max depth and drop policies that favor newest; measure processing lag and temporarily pause subscriptions or reduce channel set when lag > threshold. Consider worker pool to parallelize processing by market shard.
- Enforce snapshot invariants: Require snapshot receipt before accepting deltas; on delta-before-snapshot, auto-request snapshot for that market and buffer limited deltas by seq. On reconnect, force snapshot refresh and block downstream until cached.
- Validate market IDs: Reject/alert on messages missing `ticker`/`market_ticker`; add guardrails to ignore and resubscribe if market id is blank.
- Neo4j resilience: Add retry with circuit breaker; fall back to cached summaries when Neo4j reports memory unavailable; cap concurrent history queries per energy to avoid stampede; add timeouts and bounded result sizes.
- Data-quality gates: Compute a `data_quality_score` from queue drop rate, snapshot age, and Neo4j health. If below threshold or drop_rate > X% or queue_depth > 80% for Y seconds, stop strategies/risk execution and mark venue unhealthy.
- Staged agent execution: Gate strategy/risk agents until market data stabilizes (recent snapshot + low queue depth) and archivist context is available; otherwise defer or run in read-only/dry mode.
- Thresholds to start: queue_depth > 0.8 * max for 5s or drop_rate > 0.5% -> degrade; >2% or any sustained delta-before-snapshot for >3s -> halt trading; Neo4j memory_unavailable or latency p95 > 2s -> halt history-dependent paths.
