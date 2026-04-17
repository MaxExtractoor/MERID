# WHITELIST Paydown Tracker

> Goal: shrink `WHITELIST` in `tests/test_ui_backend_contract.py` to ≤ 15 entries.
> Current: 32 entries (cap: 45). Review weekly; pick 1–2 per cycle.

## Categories & Action Plan

### A. Router import failures (7 entries) — fix imports or gate properly

| Entry | Root Cause | Action |
|-------|-----------|--------|
| `GET /api/v1/notifications/status` | `notification_api.py` → missing `notification_worker` | Stub the worker or extract the router |
| `GET /api/v1/notifications/recent-alerts` | Same | Same |
| `POST /api/v1/notifications/telegram/send` | Same | Same |
| `GET /api/v1/notifications/telegram/status` | Same | Same |
| `GET /api/v1/risk/agents/{agentId}/*` (3) | `risk_routes.py` → missing `KalshiTradingAdapter` | Fix adapter import or make optional |
| `POST /api/v1/risk/alerts/acknowledge-all` | Same | Same |
| `POST /api/v1/risk/alerts/{alertId}/acknowledge` | Same | Same |
| `POST /api/v1/risk/downsize-all` | Same | Same |
| `DELETE /api/v1/risk/kill-switch` | Same | Same |

**Priority: HIGH** — These are real features blocked by import wiring, not
intentional gaps.

### B. Kalshi-only gated stubs (13 entries) — implement or delete

| Entry | What it serves | Action |
|-------|---------------|--------|
| `GET /api/v1/data/freshness` | Data freshness panel | Implement real endpoint (data exists in price feed) |
| `GET /api/v1/logs` | Log viewer | Implement or remove frontend constant |
| `POST /api/v1/logs/clear` | Log clear action | Implement or remove |
| `GET /api/v1/logs/stats` | Log stats | Implement or remove |
| `GET /api/v1/notifications` | Notification list | Merge with notification_api fix above |
| `POST /api/v1/notifications/read-all` | Mark all read | Same |
| `GET /api/v1/notifications/telegram/log` | Telegram log | Same |
| `POST /api/v1/notifications/{id}/read` | Mark one read | Same |
| `GET /api/v1/pipeline/venues` | Venue list | Already has real data attempt; promote |
| `GET /api/v1/risk/alerts` | Risk alerts list | Merge with risk_routes fix |
| `GET /api/v1/risk/position-limits` | Position limits | Same |
| `GET /api/v1/user/profile` | User profile | Implement minimal version |
| `PUT /api/v1/user/settings` | User settings | Implement minimal version |

**Priority: MEDIUM** — These are stubs; decide implement vs delete per entry.

### C. Dead constants (5 entries) — delete from frontend

| Entry | Verdict |
|-------|---------|
| `POST /api/v1/auth/refresh` | Delete constant — JWT refresh not planned |
| `GET /api/v1/paper-trading/{portfolioId}` | Delete or re-route to session API |
| `GET /api/v1/pipeline/venue/mode` | Delete — legacy crypto pipeline |
| `POST /api/v1/pipeline/venue/{action}` | Delete — legacy |
| `GET /api/v1/pipeline/venues/{venue}/pnl` | Delete — legacy |

**Priority: LOW** — Clean but harmless dead code.

### D. Non-v1 routes (7 entries) — architectural

| Entry | Verdict |
|-------|---------|
| `GET /debates/*` (5) | Move to `/api/v1/debates/*` or remove constants |
| `GET /api/x/status` | Keep — separate auth surface |
| `POST /api/x/post` | Keep — separate auth surface |
| `POST /api/dev-swarm/*` (3) | Keep — dev-only, gated |

**Priority: LOW** — Not causing user-facing issues.

## Weekly Cadence

Each Monday:
1. Pick 1–2 entries from the highest-priority unfixed category.
2. Fix them (implement, delete constant, or fix import).
3. Remove from `WHITELIST`.
4. Lower the `max_allowed` cap by the same amount.
5. Run `py -m pytest tests/test_ui_backend_contract.py -v` to confirm.
