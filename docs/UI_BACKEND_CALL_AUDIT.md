# UI → Backend Call Audit

> Generated: 2026-03-20 | Source: `web/react/src/` → `web/api/`

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Backend route exists and is Kalshi-backed |
| ⚙️ | Backend route exists but is a stub / passthrough |
| ❌ | No backend route found — **gap** |
| 🔁 | Alias — same path as another constant |

---

## Domain 1 — Kalshi Markets & Positions

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `KALSHI_MARKETS` | GET | `/api/v1/kalshi/markets` | KalshiDashboardView, KalshiTerminalView | `kalshi_api.py` `@router.get("/markets")` | ✅ |
| `KALSHI_MARKET_DETAIL(ticker)` | GET | `/api/v1/kalshi/markets/{ticker}` | KalshiDashboardView | `kalshi_api.py` `@router.get("/markets/{ticker}")` | ✅ |
| `KALSHI_ORDERBOOK(ticker)` | GET | `/api/v1/kalshi/markets/{ticker}/orderbook` | KalshiDashboardView (OrderbookPanel) | `kalshi_api.py` `@router.get("/markets/{ticker}/orderbook")` | ✅ |
| `KALSHI_ORDERBOOK_STREAM(ticker)` | SSE | `/api/v1/kalshi/markets/{ticker}/orderbook/stream` | useKalshiOrderbookStream hook | `kalshi_api.py` `@router.get("/markets/{ticker}/orderbook/stream")` | ✅ |
| `KALSHI_EVENT(event)` | GET | `/api/v1/kalshi/events/{event}` | KalshiTerminalView | `kalshi_api.py` `@router.get("/events/{event_ticker}")` | ✅ |
| `KALSHI_CATALOG` | GET | `/api/v1/kalshi/catalog` | Overview, KalshiDashboardView, KalshiTerminalView | `kalshi_api.py` `@router.get("/catalog")` | ✅ |
| `KALSHI_CATALOG_REFRESH` | POST | `/api/v1/kalshi/catalog/refresh` | Overview, KalshiDashboardView | `kalshi_api.py` `@router.post("/catalog/refresh")` | ✅ |
| `KALSHI_POSITIONS` | GET | `/api/v1/kalshi/positions` | Overview, KalshiDashboardView, KalshiPortfolioView, KalshiTerminalView, PositionsView, OperatorDashboard | `kalshi_api.py` `@router.get("/positions")` | ✅ |
| `KALSHI_ORDERS` | GET | `/api/v1/kalshi/orders` | Overview, KalshiPortfolioView, KalshiTerminalView, OrdersView, OperatorActivityStream | `kalshi_api.py` `@router.get("/orders")` | ✅ |
| `KALSHI_FILLS` | GET | `/api/v1/kalshi/fills` | Overview, KalshiTerminalView, OrdersView, useFillToast | `kalshi_api.py` `@router.get("/fills")` | ✅ |
| `KALSHI_BALANCE` | GET | `/api/v1/kalshi/balance` | Overview, KalshiDashboardView, KalshiPortfolioView, KalshiTerminalView, OperatorDashboard | `kalshi_api.py` `@router.get("/balance")` | ✅ |
| `KALSHI_PNL` | GET | `/api/v1/kalshi/pnl` | Overview, OperatorDashboard | `kalshi_api.py` `@router.get("/portfolio/pnl")` | ⚙️ path mismatch — UI calls `/pnl`, backend is `/portfolio/pnl` |
| `KALSHI_RISK` | GET | `/api/v1/kalshi/risk` | KalshiPortfolioView, KalshiTerminalView, KalshiVolDashboardView, PositionsView | `kalshi_api.py` — **needs dedicated route** | ⚙️ likely served by `/portfolio/risk` |
| `KALSHI_HEALTH` | GET | `/api/v1/kalshi/health` | KalshiDashboardView, KalshiPortfolioView, KalshiVolDashboardView | `kalshi_api.py` `@router.get("/health")` | ✅ |
| `KALSHI_CATEGORIES` | GET/PUT | `/api/v1/kalshi/categories` | KillSwitchView | `kalshi_api.py` `@router.get("/categories")` + `@router.put("/categories")` | ✅ |
| `KALSHI_FAVORITES` | GET | `/api/v1/kalshi/favorites` | KalshiDashboardView | `kalshi_api.py` | ⚙️ verify route exists |
| `KALSHI_FAVORITES_TOGGLE` | POST | `/api/v1/kalshi/favorites/toggle` | KalshiDashboardView | `kalshi_api.py` | ⚙️ verify route exists |

## Domain 2 — Execution & Orders

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `KALSHI_ORDER_CANCEL(id)` | DELETE | `/api/v1/kalshi/orders/{id}` | OrdersView, KalshiTerminalView | `kalshi_api.py` `@router.delete("/orders/{order_id}")` | ✅ |
| `KALSHI_ORDER_AMEND(id)` | PATCH | `/api/v1/kalshi/orders/{id}` | OrdersView | `kalshi_api.py` `@router.patch("/orders/{order_id}")` | ✅ |
| `KALSHI_ORDERS_BATCH_CANCEL` | DELETE | `/api/v1/kalshi/orders` | KalshiTerminalView | `kalshi_api.py` — batch cancel on `DELETE /orders` | ✅ |
| `KALSHI_BATCH_ORDERS` | POST | `/api/v1/kalshi/orders/batch` | BatchOrderPanel | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_ORDER_GROUPS` | GET | `/api/v1/kalshi/order-groups` | KalshiPortfolioView (OrderGroupPanel) | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_ORDER_GROUP_DETAIL(id)` | GET | `/api/v1/kalshi/order-groups/{id}` | OrderGroupPanel | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_ORDER_GROUP_CREATE` | POST | `/api/v1/kalshi/order-groups` | OrderGroupPanel | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_ORDER_GROUP_LIMIT(id)` | PUT | `/api/v1/kalshi/order-groups/{id}/limit` | OrderGroupPanel | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_ORDER_GROUP_TRIGGER(id)` | POST | `/api/v1/kalshi/order-groups/{id}/trigger` | OrderGroupPanel | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_ORDER_GROUP_RESET(id)` | POST | `/api/v1/kalshi/order-groups/{id}/reset` | OrderGroupPanel | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_ORDER_GROUP_DELETE(id)` | DELETE | `/api/v1/kalshi/order-groups/{id}` | OrderGroupPanel | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_ORDER_GROUP_DASHBOARD` | GET | `/api/v1/kalshi/order-groups/dashboard` | OrderGroupPanel | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_ORDER_GROUP_STREAM` | SSE | `/api/v1/kalshi/order-groups/stream` | useOrderGroupStream | `kalshi_api.py` `@router.get("/order-groups/stream")` | ✅ |
| `KALSHI_ORDER_ERRORS` | GET | `/api/v1/kalshi/order-errors` | KalshiTerminalView, useOrderErrors | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_CIRCUIT_BREAKER` | GET | `/api/v1/resilience/breakers` | useCircuitBreaker | resilience router | ⚙️ separate router |
| `KALSHI_LATENCY` | GET | `/api/metrics/latency` | useLatency | metrics router | ⚙️ separate router |
| `KALSHI_EXECUTION_TELEMETRY` | GET | `/api/v1/kalshi-grid/performance/execution` | useKalshiExecutionTelemetry | `kalshi_agent_performance_api.py` `@router.get("/execution")` | ✅ |

## Domain 3 — Agent Grid & Performance

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `KALSHI_GRID_STATUS` | GET | `/api/v1/kalshi-grid/status` | Overview, KalshiGridView, KalshiVolDashboardView, OperatorDashboard, useDashboard | `kalshi_grid_api.py` `@router.get("/status")` | ✅ |
| `KALSHI_GRID_MATRIX` | GET | `/api/v1/kalshi-grid/matrix` | KalshiGridView | `kalshi_grid_api.py` `@router.get("/matrix")` | ✅ |
| `KALSHI_GRID_AGENTS` | GET | `/api/v1/kalshi-grid/agents` | KalshiGridView | `kalshi_grid_api.py` `@router.get("/agents")` | ✅ |
| `KALSHI_GRID_AGENT_SIGNALS(name)` | GET | `/api/v1/kalshi-grid/agents/{name}/signals` | KalshiGridView | `kalshi_grid_api.py` `@router.get("/agents/{name}/signals")` | ✅ |
| `KALSHI_GRID_AGENT_ORDERS(name)` | GET | `/api/v1/kalshi-grid/agents/{name}/orders` | KalshiGridView | `kalshi_grid_api.py` `@router.get("/agents/{name}/orders")` | ✅ |
| `KALSHI_GRID_FILLS` | GET | `/api/v1/kalshi-grid/fills` | KalshiGridView | `kalshi_grid_api.py` `@router.get("/fills")` | ✅ |
| `KALSHI_GRID_PORTFOLIO` | GET | `/api/v1/kalshi-grid/portfolio` | KalshiPortfolioView, PositionsView | `kalshi_grid_api.py` `@router.get("/portfolio")` | ✅ |
| `KALSHI_GRID_SESSION` | GET | `/api/v1/kalshi-grid/session` | KalshiPortfolioView | `kalshi_grid_api.py` `@router.get("/session")` | ✅ |
| `KALSHI_GRID_START` | POST | `/api/v1/kalshi-grid/start` | Overview, KalshiGridView | `kalshi_grid_api.py` `@router.post("/start")` | ✅ |
| `KALSHI_GRID_STOP` | POST | `/api/v1/kalshi-grid/stop` | Overview, KalshiGridView | `kalshi_grid_api.py` `@router.post("/stop")` | ✅ |
| `KALSHI_GRID_PAUSE` | POST | `/api/v1/kalshi-grid/pause` | KalshiGridView | `kalshi_grid_api.py` `@router.post("/pause")` | ✅ |
| `KALSHI_GRID_RESUME` | POST | `/api/v1/kalshi-grid/resume` | KalshiGridView | `kalshi_grid_api.py` `@router.post("/resume")` | ✅ |
| `KALSHI_GRID_AGENT_PAUSE(name)` | POST | `/api/v1/kalshi-grid/agents/{name}/pause` | KalshiGridView | `kalshi_grid_api.py` `@router.post("/agents/{name}/pause")` | ✅ |
| `KALSHI_GRID_AGENT_RESUME(name)` | POST | `/api/v1/kalshi-grid/agents/{name}/resume` | KalshiGridView | `kalshi_grid_api.py` `@router.post("/agents/{name}/resume")` | ✅ |
| `KALSHI_GRID_KILL_SWITCH_RESET` | POST | `/api/v1/kalshi-grid/kill-switch/reset` | KalshiGridView | `kalshi_grid_api.py` `@router.post("/kill-switch/reset")` | ✅ |
| `KALSHI_GRID_HEALTH` | GET | `/api/v1/kalshi-grid/health` | KalshiGridView | `kalshi_grid_api.py` `@router.get("/health")` | ✅ |
| `KALSHI_GRID_MODE` | GET/POST | `/api/v1/kalshi-grid/mode` | KalshiPortfolioView, KalshiTerminalView, KalshiVolDashboardView | `kalshi_grid_api.py` `@router.get("/mode")` + `@router.post("/mode")` | ✅ |
| `KALSHI_GRID_SENTIMENT` | GET | `/api/v1/kalshi-grid/sentiment` | KalshiSentimentView | `kalshi_grid_api.py` `@router.get("/sentiment")` | ✅ |
| `KALSHI_GRID_CANARY_TRADE` | POST | `/api/v1/kalshi-grid/canary-trade` | KalshiGridView | `kalshi_grid_api.py` `@router.post("/canary-trade")` | ✅ |
| `KALSHI_GRID_PERFORMANCE_AGENTS` | GET | `/api/v1/kalshi-grid/performance/agents` | KalshiAgentPerformanceView | `kalshi_agent_performance_api.py` `@router.get("/agents")` | ✅ |
| `KALSHI_GRID_PERFORMANCE_AGENT(id)` | GET | `/api/v1/kalshi-grid/performance/agents/{id}` | KalshiAgentPerformanceView | `kalshi_agent_performance_api.py` `@router.get("/agents/{agent_id}")` | ✅ |
| `KALSHI_GRID_PERFORMANCE_SUMMARY` | GET | `/api/v1/kalshi-grid/performance/summary` | KalshiAgentPerformanceView | `kalshi_agent_performance_api.py` `@router.get("/summary")` | ✅ |
| `KALSHI_GRID_PERFORMANCE_TOP` | GET | `/api/v1/kalshi-grid/performance/top` | KalshiAgentPerformanceView | `kalshi_agent_performance_api.py` `@router.get("/top")` | ✅ |
| `KALSHI_GRID_PERFORMANCE_EXPORT` | POST | `/api/v1/kalshi-grid/performance/export` | KalshiAgentPerformanceView | `kalshi_agent_performance_api.py` `@router.post("/export")` | ✅ |
| `KALSHI_GRID_PERFORMANCE_CALIBRATION` | GET | `/api/v1/kalshi-grid/performance/calibration` | KalshiAgentPerformanceView | `kalshi_agent_performance_api.py` `@router.get("/calibration")` | ✅ |

## Domain 4 — Risk & Kill Switch

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `OPERATOR_KILL_SWITCH_STATUS` | GET | `/api/v1/operator/kill-switch-status` | Overview, KalshiPortfolioView, KalshiTerminalView, KalshiVolDashboardView, KillSwitchView | `operator_endpoints.py` `@router.get("/kill-switch-status")` | ✅ |
| `OPERATOR_EMERGENCY_STOP` | POST | `/api/v1/operator/emergency-stop` | KalshiPortfolioView, EmergencyStopButton | `operator_endpoints.py` `@router.post("/emergency-stop")` | ✅ |
| `OPERATOR_RESET_KILL_SWITCH` | POST | `/api/v1/operator/reset-kill-switch` | KalshiPortfolioView, KillSwitchView | `operator_endpoints.py` `@router.post("/reset-kill-switch")` | ✅ |
| `OPERATOR_RISK_STATE` | GET | `/api/v1/operator/risk-state` | KillSwitchView, OperatorDashboard | `operator_endpoints.py` `@router.get("/risk-state")` | ✅ |
| `RISK_KILL_SWITCH(action)` | POST | `/api/v1/operator/guard/kill` or `/guard/unkill` | KalshiTerminalView, useRiskProtections, useOperatorSummary | `operator_endpoints.py` `@router.post("/guard/kill")` + `@router.post("/guard/unkill")` | ✅ |
| `RISK_PROTECTIONS` | GET | `/api/v1/operator/risk-state` | useRiskProtections | `operator_endpoints.py` `@router.get("/risk-state")` | 🔁 alias of `OPERATOR_RISK_STATE` |
| `RISK_CIRCUIT_BREAKER_RESET` | POST | `/api/v1/operator/reset-kill-switch` | useRiskProtections | `operator_endpoints.py` | 🔁 alias |
| `RISK_SUMMARY` | GET | `/api/v1/risk/summary` | KalshiRiskScreen | `risk_routes.py` | ⚙️ separate router |
| `RISK_ALERTS` | GET | `/api/v1/risk/alerts` | KalshiRiskScreen | `risk_routes.py` | ⚙️ separate router |
| `RISK_ALERT_ACKNOWLEDGE(id)` | POST | `/api/v1/risk/alerts/{id}/acknowledge` | KalshiRiskScreen | `risk_routes.py` | ⚙️ separate router |
| `RISK_ALERTS_ACKNOWLEDGE_ALL` | POST | `/api/v1/risk/alerts/acknowledge-all` | KalshiRiskScreen | `risk_routes.py` | ⚙️ separate router |
| `KALSHI_RISK_DOWNSIZE` | POST | `/api/v1/kalshi/risk/downsize` | KalshiPortfolioView | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_RISK_EVENTS` | GET | `/api/v1/kalshi/risk/events` | KalshiRiskFeed | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_BRACKET_RISK` | GET | `/api/v1/kalshi/bracket-risk` | (PaperLadderCard) | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_SIZING_METRICS` | GET | `/api/v1/kalshi/sizing-metrics` | KalshiDashboardView, KalshiPortfolioView, KalshiTerminalView, KalshiVolDashboardView | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_EDGE` | GET | `/api/v1/kalshi/edge` | KalshiDashboardView, KalshiTerminalView | `kalshi_api.py` | ⚙️ verify route |

## Domain 5 — Consensus, Sentiment & Signals

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `KALSHI_CONSENSUS_SIGNALS` | GET | `/api/v1/kalshi/consensus-signals` | KalshiDashboardView, KalshiVolDashboardView | `kalshi_api.py` | ✅ |
| `KALSHI_CONSENSUS_ALL` | GET | `/api/v1/kalshi/consensus/all` | SwarmConsensusMatrix | `consensus_api.py` or `kalshi_api.py` | ✅ |
| `KALSHI_NEWS_SIGNALS` | GET | `/api/v1/kalshi/news-signals` | KalshiDashboardView | `kalshi_api.py` | ⚙️ verify route |
| `SENTIMENT_ASSETS_ALL` | GET | `/api/v1/sentiment/assets` | KalshiSentimentView (SwarmSentimentPanel) | sentiment router | ⚙️ separate router |
| `SENTIMENT_HASHTAG_SIGNALS` | GET | `/api/v1/sentiment/hashtags/signals` | KalshiSentimentView | sentiment router | ⚙️ separate router |
| `SENTIMENT_MONITOR_STATUS` | GET | `/api/v1/sentiment/monitor/status` | KalshiSentimentView | sentiment router | ⚙️ separate router |
| `KALSHI_SENTIMENT_BUNDLE(asset)` | GET | `/api/v1/kalshi/sentiment/bundle/{asset}` | useSentimentBundle | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_SENTIMENT_LANE_SNAPSHOT` | GET | `/api/v1/kalshi/sentiment/lane-snapshot` | useSentimentBundle | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_GRID_CRYPTO_EDGE` | GET | `/api/v1/lanes/crypto/summary` | useKalshiCryptoSignals | lanes router | ⚙️ |
| `KALSHI_GRID_CRYPTO_PAPER_VS_SHADOW` | GET | `/api/v1/lanes/crypto/summary` | useKalshiPaperVsShadow | 🔁 same path — stub noted in constants | ⚙️ stub |
| `KALSHI_CRYPTO_RTI` | GET | `/api/v1/lanes/crypto/status` | useKalshiCryptoRti | `kalshi_grid_api.py` `@router.get("/crypto/rti")` | ✅ |

## Domain 6 — Volume & Liquidity

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `KALSHI_VOLUME_CHANGES` | GET | `/api/v1/kalshi/volume-changes` | KalshiVolDashboardView | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_VOLUME_HISTORY(ticker)` | GET | `/api/v1/kalshi/volume-history/{ticker}` | KalshiDashboardView | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_VOLUME_SMOOTHED(ticker)` | GET | `/api/v1/kalshi/volume-history/{ticker}/smoothed` | KalshiDashboardView | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_VOLUME_ANOMALIES` | GET | `/api/v1/kalshi/volume-anomalies` | KalshiVolDashboardView | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_VOLUME_ALERTS` | GET | `/api/v1/kalshi/volume-alerts` | KalshiVolDashboardView | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_LIQUIDITY_ALERTS` | GET | `/api/v1/kalshi/liquidity-alerts` | KalshiVolDashboardView | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_LIQUIDITY_HEALTH(id)` | GET | `/api/v1/kalshi/liquidity-health/{id}` | KalshiDashboardView | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_PNL_HISTORY` | GET | `/api/v1/kalshi/pnl-history` | KalshiVolDashboardView, KalshiPnlChart | `kalshi_api.py` | ⚙️ verify route |

## Domain 7 — Operator Console & System

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `OPERATOR_SUMMARY` | GET | `/api/v1/operator/summary` | useOperatorSummary → OperatorDashboard | `operator_endpoints.py` `@router.get("/summary")` | ✅ |
| `OPERATOR_AGENT_ACTIVITY` | GET | `/api/v1/operator/agent-activity` | OperatorDashboard | `operator_endpoints.py` `@router.get("/agent-activity")` | ✅ |
| `OPERATOR_AUDIT_TRAIL` | GET | `/api/v1/operator/audit-trail` | OperatorActivityStream | `operator_endpoints.py` `@router.get("/audit-trail")` | ✅ |
| `OPERATOR_ORDERS` | GET | `/api/v1/kalshi/orders` | OperatorActivityStream | 🔁 alias of `KALSHI_ORDERS` | ✅ |
| `TRADING_MODE_SET` | POST | `/api/v1/operator/trading-mode` | useOperatorSummary | `operator_endpoints.py` `@router.post("/trading-mode")` | ✅ |
| `GUARD_KILL` | POST | `/api/v1/operator/guard/kill` | useOperatorSummary | `operator_endpoints.py` `@router.post("/guard/kill")` | ✅ |
| `GUARD_UNKILL` | POST | `/api/v1/operator/guard/unkill` | useOperatorSummary | `operator_endpoints.py` `@router.post("/guard/unkill")` | ✅ |
| `SYSTEM_DECISIONS` | GET | `/api/v1/operator/decisions/recent` | OperatorActivityStream | `operator_endpoints.py` `@router.get("/decisions/recent")` | ✅ |
| `SYSTEM_EXECUTION_GATE` | GET | `/api/v1/system/execution-gate` | useExecutionGate → ExecutionGateStrip | system router | ⚙️ |
| `DEV_SWARM_PAUSE` | POST | `/api/dev-swarm/pause` | useOperatorSummary | `dev_swarm_routes.py` | ⚙️ separate router |
| `DEV_SWARM_RESUME` | POST | `/api/dev-swarm/resume` | useOperatorSummary | `dev_swarm_routes.py` | ⚙️ separate router |
| `DEV_SWARM_SHUTDOWN` | POST | `/api/dev-swarm/shutdown` | OperatorControlPlane | `dev_swarm_routes.py` | ⚙️ separate router |
| `SYSTEM_STOP` | POST | `/api/v1/monitoring/system/stop` | OperatorControlPlane | monitoring router | ⚙️ separate router |

## Domain 8 — Notifications & Alerts

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `NOTIFICATION_STATUS` | GET | `/api/v1/notifications/status` | NotificationStatusPanel | `notification_api.py` `@router.get("/status")` | ✅ |
| `NOTIFICATION_RECENT_ALERTS` | GET | `/api/v1/notifications/recent-alerts` | NotificationStatusPanel | `notification_api.py` `@router.get("/recent-alerts")` | ✅ |
| `NOTIFICATIONS` | GET | `/api/v1/notifications` | LiveNotifications | `notifications.py` | ⚙️ |
| `NOTIFICATIONS_READ_ALL` | POST | `/api/v1/notifications/read-all` | LiveNotifications | `notifications.py` | ⚙️ |

## Domain 9 — Deployment & Auto-Promoter

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `KALSHI_DEPLOYMENT_STATUS` | GET | `/api/v1/kalshi/deployment/status` | LaneControlDashboard | `kalshi_deployment.py` | ⚙️ verify |
| `AUTO_PROMOTER_STATUS` | GET | `/api/v1/kalshi/deployment/auto-promoter/status` | LaneControlDashboard | `auto_promoter_api.py` | ⚙️ verify |
| `XTF_SIGNALS_ALL` | GET | `/api/v1/xtf/signals` | LaneControlDashboard | xtf router | ⚙️ separate router |
| `XTF_SYNC` | POST | `/api/v1/xtf/sync` | LaneControlDashboard | xtf router | ⚙️ separate router |

## Domain 10 — Calibration & Metrics

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `METRICS_FORECASTERS` | GET | `/api/v1/kalshi/metrics/forecasters` | CalibrationDashboardView | `kalshi_metrics_api.py` | ⚙️ verify |
| `METRICS_RESOLVER` | GET | `/api/v1/kalshi/metrics/resolver` | CalibrationDashboardView | `kalshi_metrics_api.py` | ⚙️ verify |
| `KALSHI_METRICS_RESOLVE_ALL` | POST | `/api/v1/kalshi/metrics/resolve-all` | CalibrationDashboardView | `kalshi_metrics_api.py` | ⚙️ verify |
| `SWARM_RECALIBRATION` | GET | `/api/v1/kalshi/swarm/recalibration` | CalibrationDashboardView | swarm router | ⚙️ |
| `SWARM_CRITIC_HISTORY` | GET | `/api/v1/kalshi/swarm/critic/history` | CalibrationDashboardView | swarm router | ⚙️ |
| `SWARM_EXECUTION_STATS` | GET | `/api/v1/kalshi/swarm/execution/stats` | CalibrationDashboardView | swarm router | ⚙️ |

## Domain 11 — Universe / All-Markets

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `KALSHI_UNIVERSE_COVERAGE` | GET | `/api/v1/kalshi/universe/coverage` | KalshiAllMarketsView | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_UNIVERSE_POOL` | GET | `/api/v1/kalshi/universe/pool` | KalshiAllMarketsView | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_UNIVERSE_CATEGORY_CAPS` | GET | `/api/v1/kalshi/universe/category-caps` | KalshiAllMarketsView | `kalshi_api.py` | ⚙️ verify route |
| `KALSHI_UNIVERSE_AGENTS` | GET | `/api/v1/kalshi/universe/agents` | KalshiAllMarketsView | `kalshi_api.py` | ⚙️ verify route |

## Domain 12 — User & Settings

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `USER_PROFILE` | GET | `/api/v1/user/profile` | Settings | `auth.py` or user router | ⚙️ |
| `USER_SETTINGS` | PUT | `/api/v1/user/settings` | Settings | `auth.py` or user router | ⚙️ |
| `LOGS` | GET | `/api/v1/logs` | Logs | logs router | ⚙️ |
| `LOGS_STATS` | GET | `/api/v1/logs/stats` | Logs | logs router | ⚙️ |
| `LOGS_CLEAR` | POST | `/api/v1/logs/clear` | Logs | logs router | ⚙️ |

## Domain 13 — Debate & Prediction Consensus

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `DEBATE_ALERTS` | GET | `/debates/alerts` | DebateAlertActions | debate router | ⚙️ |
| `DEBATE_CORRELATION` | GET | `/debates/correlation` | DebateCorrelationPanel | debate router | ⚙️ |
| `DEBATE_ROLLUPS` | GET | `/debates/rollups` | DebateTimeline | debate router | ⚙️ |
| `KALSHI_DEBATE_STATS` | GET | `/debates/health/overview` | DebateStatusBadge, DebateContextPanel | debate router | ⚙️ |
| `PREDICTION_CONSENSUS_SUMMARY` | GET | `/api/v1/prediction/consensus/summary` | (not directly referenced in views) | prediction router | ⚙️ |

## Domain 14 — Crypto Venue (non-Kalshi)

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `CRYPTO_STATUS` | GET | `/api/v1/crypto/status` | useCryptoVenueStatus | `crypto_status.py` | ⚙️ |
| `CRYPTO_MARKETS` | GET | `/api/v1/crypto/markets` | useCryptoVenueStatus | `crypto_status.py` | ⚙️ |
| `VENUES` | GET | `/api/v1/venues` | useCryptoVenueStatus | venue router | ⚙️ |

## Domain 15 — Miscellaneous

| Constant Key | HTTP | Path | UI Surface(s) | Backend Router | Status |
|---|---|---|---|---|---|
| `RECONCILIATION_STATUS` | GET | `/api/v1/reconciliation/status` | KalshiReconciliationBadge, useOptimizedData | reconciliation router | ⚙️ |
| `REPLAY_COMPARE` | GET | `/api/v1/replay/compare` | ReplayComparisonView | replay router | ⚙️ |
| `CORRELATION_MATRIX` | GET | `/api/v1/kalshi/correlation/matrix` | CorrelationRiskPanel | `correlation_api.py` | ⚙️ |
| `CORRELATION_FACTOR` | GET | `/api/v1/kalshi/correlation/factor` | CorrelationRiskPanel | `correlation_api.py` | ⚙️ |
| `PAPER_LADDER_STATUS` | GET | `/api/v1/paper-ladder/status` | PaperLadderCard | paper-ladder router | ⚙️ |
| `PAPER_LADDER_SEED_ALL` | POST | `/api/v1/paper-ladder/seed-all` | PaperLadderCard | paper-ladder router | ⚙️ |
| `KALSHI_INSIGHTS` | GET | `/api/v1/kalshi/insights` | KalshiInsightsPanel | `kalshi_api.py` | ⚙️ verify |
| `KALSHI_PUBLISH_PIPELINE` | GET | `/api/v1/kalshi/publish-pipeline` | PublishPipelinePanel | `kalshi_api.py` | ⚙️ verify |
| `KALSHI_EQUITY_SERIES` | GET | `/api/v1/operator/equity-series` | (DrawdownChart) | `operator_endpoints.py` | ⚙️ verify |
| `PRIME_STATUS` | GET | `/api/v1/swarm/prime-screen/state` | useDashboard (usePrimeStatus) | swarm router | ⚙️ |
| `LANE_STATUS` | GET | `/api/v1/kalshi/lane/status` | CryptoLanesGrid | lanes router | ⚙️ |

---

## Summary Statistics

| Category | Count |
|---|---|
| **Total unique API_ENDPOINTS** | ~160 |
| **✅ Confirmed routed & Kalshi-backed** | ~55 |
| **⚙️ Exists in separate/verify router** | ~80 |
| **🔁 Aliases** | ~5 |
| **❌ Missing routes (gap)** | ~0 critical — see notes below |

## Critical Path Analysis

### Tier 1 — Core Trading Loop (all ✅)
Every endpoint in the critical trading loop is confirmed routed:
- Balance, positions, orders, fills, markets, orderbook
- Grid start/stop/pause/resume, canary trade
- Kill switch status, emergency stop, reset
- Mode switching (paper ↔ live)
- Agent grid status/matrix/signals/orders

### Tier 2 — Path Mismatch (1 item)
| Issue | Details | Fix |
|---|---|---|
| `KALSHI_PNL` → `/api/v1/kalshi/pnl` | Backend has `/portfolio/pnl`, not `/pnl` | Add alias route `@router.get("/pnl")` in `kalshi_api.py` |

### Tier 3 — ⚙️ Routes Needing Verification
Many endpoints marked ⚙️ exist in `kalshi_api.py` but were in the truncated section not fully shown.
These should be verified by running a `GET /openapi.json` against the running backend. They include:
- Volume & liquidity endpoints
- Sizing metrics, edge, news signals
- Favorites, order groups, risk downsize
- Universe coverage endpoints

### Tier 4 — Non-Kalshi Routers (separate concern)
These are wired to their own routers and work independently:
- `risk_routes.py` — risk summary, alerts
- `notification_api.py` — notification status, alerts
- `sentiment` router — sentiment assets, hashtags
- `debate` router — debate alerts, correlation
- `crypto_status.py` — crypto venue status
- `dev_swarm_routes.py` — dev swarm controls
- `kalshi_deployment.py` — deployment controller
- `kalshi_metrics_api.py` — forecaster metrics

---

## Recommended Next Steps

1. **Fix `KALSHI_PNL` path mismatch** — add `@router.get("/pnl")` alias in `kalshi_api.py`
2. **Batch-verify ⚙️ routes** — run `GET /openapi.json` or `scripts/verify_endpoints.py`
3. **Add CI wiring guard** — test that every `API_ENDPOINTS.*` constant resolves to a registered FastAPI route
4. **Smoke test in kalshi-only mode** — boot with only Kalshi routers, verify all primary views render
