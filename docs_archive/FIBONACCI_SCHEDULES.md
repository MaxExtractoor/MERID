# Fibonacci Schedules for MERID Swarms

_Last updated: 2026-01-17_

Fibonacci structures are most valuable in MERID when used as explainable, multi-scale schedules across hyperparameter search, swarm retries, and role specialization. This document outlines where to apply them and how to wire them into existing optimizers.

## 1. Hyperparameter & Strategy Search

| Use Case | Fibonacci Pattern | Benefit | Target Modules |
| --- | --- | --- | --- |
| Position sizing sweep | Step sizes follow Fib ratios (1, 2, 3, 5, 8 bps) | Coarse→fine exploration reduces rounds while staying interpretable | `core/optimizers/position_search.py`, `trading/positioning/` |
| Social gating thresholds | Fib ladder for confidence/coverage windows | Fast converge on multimodal surfaces (FSPSOSSA-style) | `social/social_aware_quant.py`, `governance/multi_agent_risk_controls.py` |
| Risk/explainability coverage | Fib grid for kill-switch or required coverage increments | Guarantees coverage tightening steps are explainable | `observability/`, `governance/` |

Implementation guidance:
- Use `fibonacci_range(min_value, max_value, steps)` from `core/optimizers/fibonacci.py` (see below) to generate candidate grids.
- Log selected Fib levels in `DecisionRationale` to reinforce explainability (“selected coverage=0.618 ladder level”).

## 2. Backoff & Retry Policies

| Context | Policy | Notes |
| --- | --- | --- |
| External API retries (CEX, CRM) | Fibonacci backoff: `delay = min(base * fib(k), max_delay)` | Smoother than pure exponential, avoids thundering herd |
| Swarm task rescheduling | golden-ratio backoff for orchestrator requeue times | Exposed in observability dashboards as deterministic schedule |

Implementation guidance:
- Use `FibonacciBackoff` helper with `base_delay`, `max_delay`, `jitter_pct`.
- Record delay + fib index in telemetry for auditability.

## 3. Multi-scale Swarm Roles

| Role tier | Lookback/time horizon | Example |
| --- | --- | --- |
| Coarse scout | 13 or 21-day horizon | Macro trend scanner |
| Mid analyst | 5 or 8-day horizon | Momentum/marketing cohort aggregator |
| Fine responder | 1, 2, 3-day horizon | Short-term social signals |

Implementation guidance:
- Use `fibonacci_window_levels(count=5, base_unit='day')` to assign lookbacks.
- Document ladder assignments in swarm orchestrator status payloads for explainability dashboards.

## 4. Governance & Explainability Hooks

1. Telemetry events include `fib_level` fields when schedules drive decisions.
2. Observability dashboard panel “Fibonacci Ladder Usage” tracks how often each level is selected and resulting performance.
3. Reward vectors cite explainability improvements when Fibonacci ladders are used (“+0.05 explainability for deterministic search schedule”).

## 5. Testing & Evaluation

- Add benchmark harness comparing Fib schedules vs current heuristics (backtests, ARR impact, coverage, latency).
- Promote Fibonacci variants only when they outperform or provide measurable explainability benefits.

See `core/optimizers/fibonacci.py` for shared utilities.
