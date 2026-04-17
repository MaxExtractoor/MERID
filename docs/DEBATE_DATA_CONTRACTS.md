---
title: Debate Integration Backend Contracts
description: API contracts the frontend depends on for alerts, historical contribution series, and aggregation rollups.
---

## 1. Debate Alerts Feed (`GET /debates/alerts`)

### Purpose
Single source of truth for all debate-driven anomalies. Feeds:
- `useDebateAlerts({ timeWindowDays, tierFilter, utilizationFilter })`
- Ops compact panel, inline badges, "Problems only" filters

### Query Parameters
| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `days_back` | integer | ✅ | Window in days (matches `timeWindowDays`). |
| `tier` | enum (`gold`, `silver`, `bronze`, `restricted`, `all`) | ❌ | Defaults to `all`. Front end sends `tierFilter ?? 'all'`. |
| `utilization_band` | enum (`low`, `medium`, `high`, `all`) | ❌ | Defaults to `all`. Matches our utilization chip filters. |
| `problems_only` | boolean | ❌ | Optional future flag to return only triggered alerts. |

### Response Shape
```json
{
  "window_days": 7,
  "generated_at": "2026-03-05T06:02:11Z",
  "alerts": [
    {
      "agent_id": "kalshi-btc15m-tier1",
      "tier": "gold",
      "utilization_pct": 0.94,
      "metric_id": "quota-saturation",
      "metric_label": "Quota utilization above 90%",
      "severity": "warning", // warning|critical
      "message": "Agent has consumed 94% of allocated debate quota",
      "triggered_at": "2026-03-05T05:55:00Z",
      "supporting_values": {
        "quota_pct": 0.25,
        "debate_contribution_pct": -0.03
      }
    }
  ]
}
```

### Notes
- Alerts **must** be returned newest→oldest to avoid front end resorting.
- `utilization_pct` and `tier` let the UI render badges without extra lookups.
- Unrecognized metrics should still include `metric_id`/`metric_label`; the UI will display the label verbatim.
- `severity: "warning"` is for soft thresholds (approaching quota, flat contribution); `severity: "critical"` is for hard breaches (negative debate PnL beyond bounds, quota cap exceeded). Keep exactly these two levels so colors/badges stay consistent.
- When `problems_only=false` (default), the backend may also emit informational/recovery alerts. The UI currently ignores them, but this keeps the contract forward-compatible.

## 2. Historical Contribution Series (`GET /debates/historical-contribution`)

### Purpose
Provides sparkline data for:
- Agent detail panel trend chart
- Attribution tab micro-trends (future use)

### Query Parameters
| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `agent_id` | string | ✅ | Required for per-agent view. |
| `days_back` | integer | ✅ | Matches `timeWindowDays` selector. |
| `points` | integer | ❌ | If omitted, backend should return 6–20 evenly spaced samples over `window_days` (the hook currently assumes ~uniform spacing). |

### Response Shape
```json
{
  "agent_id": "kalshi-btc15m-tier1",
  "window_days": 7,
  "points": [
    {
      "timestamp": "2026-03-05T05:00:00Z",
      "debate_contribution_pct": 0.012,
      "win_rate": 0.54,
      "utilization_pct": 0.61
    },
    {
      "timestamp": "2026-03-05T06:00:00Z",
      "debate_contribution_pct": -0.004,
      "win_rate": 0.52,
      "utilization_pct": 0.64
    }
  ]
}
```

### Notes
- Points must be chronological (oldest→newest). The hook assumes even spacing but will display any consistent order.
- Missing data → return empty `points` with `200 OK` so the UI can render "No history yet".
- Future enhancement: allow `team_id` or `strategy_id` instead of `agent_id` (see rollups below).

## 3. Team / Strategy Rollups (`GET /debates/rollups`)

### Purpose
Prepares for the upcoming portfolio-level attribution tables the UI will add once backend metrics exist.

### Query Parameters
| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `group_by` | enum (`team`, `strategy`, `configuration`) | ✅ | Determines row dimension. |
| `days_back` | integer | ✅ | Window alignment with `timeWindowDays`. |

### Response Shape
```json
{
  "group_by": "team",
  "window_days": 7,
  "rows": [
    {
      "id": "team-btc-fast",
      "label": "BTC Fast Lane",
      "debate_contribution_pct": 0.031,
      "sharpe_delta": 0.12,
      "drawdown_delta": -0.5,
      "agents": ["kalshi-btc15m-tier1", "kalshi-btc1h-tier2"],
      "utilization_pct": 0.78
    }
  ]
}
```

### Notes
- `sharpe_delta` / `drawdown_delta` represent the contribution attributed to debate overrides vs. baseline.
- `agents` array allows drill-down links to keep the cross-tab narrative intact.
- Even though the UI doesn’t surface this yet, shipping the endpoint in advance lets us light it up quickly.

## General Contract Guarantees

- For a fixed parameter set, responses are deterministic within a short horizon (no random sampling/pagination surprises).
- Arrays follow the documented order: alerts newest→oldest, historical points oldest→newest, rollup rows stable per request (backend may sort by contribution or label but should do so consistently).

## Implementation Checklist
- [ ] Add validation + typing for all new query params.
- [ ] Wire alerts feed to persisted anomaly detection (debate quotas + attribution metrics) and expose via REST.
- [ ] Persist historical contribution snapshots (or compute on the fly) per agent.
- [ ] Backfill rollup metrics or derive from existing debate attribution tables.
- [ ] Update OpenAPI schema once endpoints land; the React hooks already reflect the shape above.
