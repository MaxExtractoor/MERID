from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="MERID API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/v1/system/health")
async def health():
    return {
        "status": "ok",
        "timestamp": "2026-03-08T02:44:00.000Z",
        "services": {
            "kalshi": "ok",
            "risk": "ok",
        },
    }

@app.get("/api/v1/kalshi/fills")
async def get_fills():
    return {"fills": []}

@app.get("/api/v1/kalshi/pnl")
async def get_pnl():
    return {"pnl": 0.0}

@app.get("/api/v1/kalshi/balance")
async def get_balance():
    return {"balance": 0.0}

@app.get("/api/v1/risk/protections")
async def get_protections():
    return {
        "max_drawdown": 0.1,
        "max_position_size": 1000,
        "enabled": True,
    }

@app.get("/api/v1/system/execution-gate")
async def get_execution_gate():
    return {
        "status": "open",
        "mode": "paper",
        "last_check": "2026-03-08T02:49:00.000Z"
    }

@app.get("/api/v1/operator/kill-switch-status")
async def get_kill_switch_status():
    return {
        "active": False,
        "triggered_at": None,
        "reason": None
    }

@app.get("/api/system/health")
async def get_system_health():
    return {
        "status": "ok",
        "timestamp": "2026-03-08T02:49:00.000Z",
        "services": {
            "kalshi": "ok",
            "risk": "ok",
        }
    }

@app.get("/api/agents/summary")
async def get_agents_summary():
    return {
        "total_agents": 0,
        "active_agents": 0,
        "agents": []
    }

# Additional endpoints to fix 404 errors
@app.get("/api/v1/notifications")
async def get_notifications():
    return {"notifications": []}

@app.get("/api/v1/kalshi-grid/mode")
async def get_kalshi_grid_mode():
    return {"mode": "paper", "enabled": True}

@app.get("/api/v1/kalshi-grid/status")
async def get_kalshi_grid_status():
    return {"status": "stopped", "agents": 0, "active": False}

@app.get("/api/v1/operator/agent-activity")
async def get_operator_agent_activity():
    return {"activity": [], "summary": {"total": 0, "active": 0}}

@app.get("/api/v1/kalshi/catalog")
async def get_kalshi_catalog():
    return {"markets": [], "total": 0}

@app.get("/api/v1/kalshi/positions")
async def get_kalshi_positions():
    return {"positions": [], "total_value": 0.0}

@app.get("/api/v1/kalshi/orders")
async def get_kalshi_orders():
    return {"orders": [], "total": 0}

@app.get("/api/v1/kalshi/risk")
async def get_kalshi_risk():
    return {"risk_score": 0.0, "exposure": 0.0, "limits": {}}

@app.get("/api/v1/kalshi/health")
async def get_kalshi_health():
    return {"status": "ok", "connectivity": True, "last_update": "2026-03-08T02:52:00.000Z"}

@app.get("/api/v1/operator/summary")
async def get_operator_summary():
    return {"agents": 0, "active": 0, "pnl": 0.0, "risk": "low"}

@app.get("/api/v1/data/freshness")
async def get_data_freshness():
    return {"fresh": True, "last_update": "2026-03-08T02:52:00.000Z", "stale_sources": []}

@app.get("/api/v1/reconciliation/unified-status")
async def get_reconciliation_status():
    return {"status": "ok", "discrepancies": 0, "last_check": "2026-03-08T02:52:00.000Z"}

@app.get("/api/v1/system/mode-safety")
async def get_system_mode_safety():
    return {"safe": True, "mode": "paper", "guards": []}

@app.get("/api/v1/system/pnl-consistency")
async def get_system_pnl_consistency():
    return {"consistent": True, "discrepancies": [], "last_check": "2026-03-08T02:52:00.000Z"}

@app.get("/api/v1/system/price-feed-staleness")
async def get_system_price_feed_staleness():
    return {"stale": False, "last_update": "2026-03-08T02:52:00.000Z", "sources": []}

@app.get("/api/v1/system/session-log")
async def get_system_session_log():
    return {"logs": [], "total": 0, "last_id": 0}

@app.get("/api/v1/system/symbol-status")
async def get_system_symbol_status():
    return {"symbols": [], "active": 0, "total": 0}

@app.get("/api/v1/system/fresh-start")
async def get_system_fresh_start():
    return {"ready": True, "timestamp": "2026-03-08T02:52:00.000Z"}

@app.get("/api/v1/loop/status")
async def get_loop_status():
    return {"running": False, "mode": "paper", "last_tick": None}

@app.get("/api/v1/loop/execution/status")
async def get_loop_execution_status():
    return {"executing": False, "mode": "paper", "last_execution": None}

@app.get("/api/v1/loop/live-readiness")
async def get_loop_live_readiness():
    return {"ready": False, "checks": {"kalshi": False, "risk": False}}

@app.get("/api/v1/loop/tick-log")
async def get_loop_tick_log():
    return {"ticks": [], "total": 0, "last_tick": None}

@app.get("/api/v1/telemetry")
async def get_telemetry():
    return {"metrics": {}, "uptime": 0, "version": "1.0.0"}

@app.get("/api/v1/risk/summary")
async def get_risk_summary():
    return {"overall_risk": "low", "score": 0.0, "limits": {}}

@app.get("/api/v1/risk/halt-status")
async def get_risk_halt_status():
    return {"halted": False, "reason": None, "timestamp": None}

@app.get("/api/v1/risk/staleness")
async def get_risk_staleness():
    return {"stale": False, "last_update": "2026-03-08T02:52:00.000Z"}

@app.get("/api/v1/risk/alerts")
async def get_risk_alerts():
    return {"alerts": [], "active": 0, "critical": 0}

@app.get("/api/v1/risk/position-limits")
async def get_risk_position_limits():
    return {"limits": [], "total_limit": 0.0, "utilization": 0.0}

@app.get("/api/v1/risk/agents")
async def get_risk_agents():
    return {"agents": [], "total": 0, "at_risk": 0}

@app.get("/api/v1/trading-mode/mode")
async def get_trading_mode():
    return {"mode": "paper", "live_enabled": False, "paper_enabled": True}

@app.get("/api/v1/paper-trading/{portfolio_id}")
async def get_paper_trading_portfolio(portfolio_id: str):
    return {"portfolio_id": portfolio_id, "positions": [], "pnl": 0.0, "cash": 10000.0}

@app.get("/api/v1/logs")
async def get_logs():
    return {"logs": [], "total": 0, "levels": []}

@app.get("/api/v1/logs/stats")
async def get_logs_stats():
    return {"total": 0, "by_level": {}, "by_component": {}}

@app.get("/api/v1/user/profile")
async def get_user_profile():
    return {"user_id": "demo", "name": "Demo User", "permissions": []}

@app.get("/api/v1/user/settings")
async def get_user_settings():
    return {"settings": {}, "preferences": {}}

@app.get("/api/v1/pipeline/venues")
async def get_pipeline_venues():
    return {"venues": [], "active": 0, "total": 0}

@app.get("/api/v1/pipeline/venue-mode")
async def get_pipeline_venue_mode():
    return {"mode": "paper", "venues": []}

@app.get("/api/v1/paper-ladder/status")
async def get_paper_ladder_status():
    return {"status": "stopped", "rungs": [], "current": 0}

@app.get("/api/v1/kalshi-grid/matrix")
async def get_kalshi_grid_matrix():
    return {"matrix": [], "agents": [], "performance": {}}

@app.get("/api/v1/kalshi-grid/agents")
async def get_kalshi_grid_agents():
    return {"agents": [], "total": 0, "active": 0}

@app.get("/api/v1/kalshi-grid/fills")
async def get_kalshi_grid_fills():
    return {"fills": [], "total": 0, "volume": 0.0}

@app.get("/api/v1/kalshi-grid/portfolio")
async def get_kalshi_grid_portfolio():
    return {"positions": [], "pnl": 0.0, "value": 0.0}

@app.get("/api/v1/kalshi-grid/session")
async def get_kalshi_grid_session():
    return {"session_id": "demo", "start_time": None, "status": "stopped"}

@app.get("/api/v1/kalshi-grid/health")
async def get_kalshi_grid_health():
    return {"healthy": True, "checks": {}, "last_check": "2026-03-08T02:52:00.000Z"}

@app.get("/api/v1/kalshi-grid/performance/agents")
async def get_kalshi_grid_performance_agents():
    return {"agents": [], "summary": {"total_pnl": 0.0, "total_agents": 0}}

@app.get("/api/v1/kalshi-grid/performance/summary")
async def get_kalshi_grid_performance_summary():
    return {"summary": {"pnl": 0.0, "sharpe": 0.0, "agents": 0}}

@app.get("/api/v1/kalshi/markets")
async def get_kalshi_markets():
    return {"markets": [], "total": 0, "active": 0}

@app.get("/api/v1/prime/status")
async def get_prime_status():
    return {"status": "inactive", "subscription": None, "features": []}

@app.get("/api/v1/signals/alerts/history")
async def get_signals_alerts_history():
    return {"alerts": [], "total": 0, "last_alert": None}

@app.get("/api/v1/explainability/decisions")
async def get_explainability_decisions():
    return {"decisions": [], "total": 0, "last_decision": None}

@app.get("/api/x/status")
async def get_x_bot_status():
    return {"status": "inactive", "last_post": None, "connected": False}

@app.get("/api/v1/notifications/telegram/status")
async def get_telegram_bot_status():
    return {"status": "inactive", "connected": False, "last_message": None}

@app.get("/api/v1/operator/decisions/recent")
async def get_operator_decisions_recent():
    return {"decisions": [], "total": 0, "last_decision": None}

@app.get("/api/v1/operator/risk-state")
async def get_operator_risk_state():
    return {"state": "normal", "risk_level": "low", "alerts": []}

@app.get("/api/v1/operator/audit-trail")
async def get_operator_audit_trail():
    return {"entries": [], "total": 0, "last_entry": None}

@app.get("/api/dev-swarm/pause")
async def get_dev_swarm_pause():
    return {"paused": False, "timestamp": None}

@app.get("/api/dev-swarm/resume")
async def get_dev_swarm_resume():
    return {"resumed": True, "timestamp": "2026-03-08T02:52:00.000Z"}

@app.get("/api/dev-swarm/shutdown")
async def get_dev_swarm_shutdown():
    return {"shutdown": False, "timestamp": None}

# WebSocket endpoints already exist above
from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/trades")
async def trades_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(data)
    except WebSocketDisconnect:
        pass

@app.websocket("/ws/risk")
async def risk_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(data)
    except WebSocketDisconnect:
        pass

@app.websocket("/ws/prediction")
async def prediction_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(data)
    except WebSocketDisconnect:
        pass

# POST endpoints for actions
@app.post("/api/v1/risk/kill-switch/enable")
async def enable_kill_switch():
    return {"success": True, "status": "enabled", "timestamp": "2026-03-08T02:55:00.000Z"}

@app.post("/api/v1/risk/kill-switch/disable")
async def disable_kill_switch():
    return {"success": True, "status": "disabled", "timestamp": "2026-03-08T02:55:00.000Z"}

@app.post("/api/v1/kalshi/catalog/refresh")
async def refresh_kalshi_catalog():
    return {"success": True, "refreshed_at": "2026-03-08T02:55:00.000Z"}

# Additional missing endpoints
@app.get("/api/v1/kalshi/favorites")
async def get_kalshi_favorites():
    return {"favorites": [], "total": 0}

@app.get("/api/v1/kalshi/order-errors")
async def get_kalshi_order_errors():
    return {"errors": [], "total": 0, "last_error": None}

@app.get("/api/v1/kalshi/edge")
async def get_kalshi_edge():
    return {"edge": 0.0, "confidence": 0.0, "markets": []}

@app.get("/api/v1/kalshi/sizing-metrics")
async def get_kalshi_sizing_metrics():
    return {"metrics": {}, "total_size": 0.0, "utilization": 0.0}

@app.get("/api/v1/kalshi/consensus-signals")
async def get_kalshi_consensus_signals():
    return {"signals": [], "total": 0, "last_signal": None}

@app.get("/api/v1/kalshi/news-signals")
async def get_kalshi_news_signals():
    return {"signals": [], "total": 0, "last_signal": None}

@app.get("/api/v1/kalshi/universe/coverage")
async def get_kalshi_universe_coverage():
    return {"coverage": 0.0, "total_markets": 0, "covered_markets": 0}

@app.get("/api/v1/kalshi/universe/pool")
async def get_kalshi_universe_pool():
    return {"pool": [], "total": 0, "liquidity": 0.0}

@app.get("/api/v1/kalshi/universe/category-caps")
async def get_kalshi_universe_category_caps():
    return {"caps": {}, "categories": []}

@app.get("/api/v1/kalshi/universe/agents")
async def get_kalshi_universe_agents():
    return {"agents": [], "total": 0, "active": 0}

@app.get("/api/v1/kalshi-grid/crypto/edge")
async def get_kalshi_grid_crypto_edge():
    return {"edge": 0.0, "markets": [], "timestamp": "2026-03-08T02:55:00.000Z"}

@app.get("/api/v1/kalshi-grid/performance/btc-15m")
async def get_kalshi_grid_performance_btc_15m():
    return {"performance": {"pnl": 0.0, "sharpe": 0.0, "trades": 0}}

@app.get("/api/v1/kalshi-grid/performance/blocked-reasons/btc_15m_regime")
async def get_kalshi_grid_performance_blocked_reasons():
    return {"reasons": [], "blocked": False, "timestamp": "2026-03-08T02:55:00.000Z"}

@app.get("/debates/alerts")
async def get_debates_alerts():
    return {"alerts": [], "total": 0, "days_back": 1}

@app.get("/api/v1/kalshi/correlation/matrix")
async def get_kalshi_correlation_matrix():
    return {"matrix": [], "assets": [], "correlations": {}}

@app.get("/api/v1/kalshi/correlation/clusters")
async def get_kalshi_correlation_clusters():
    return {"clusters": [], "total": 0, "hierarchy": []}

@app.get("/api/v1/kalshi/metrics/forecasters")
async def get_kalshi_metrics_forecasters():
    return {"forecasters": [], "total": 0, "accuracy": 0.0}

@app.get("/api/v1/kalshi/metrics/resolver")
async def get_kalshi_metrics_resolver():
    return {"resolver": {"accuracy": 0.0, "resolved": 0, "pending": 0}}

@app.get("/api/v1/kalshi/swarm/recalibration")
async def get_kalshi_swarm_recalibration():
    return {"status": "idle", "last_recalibration": None, "next_recalibration": None}

@app.get("/api/v1/kalshi/swarm/critic/history")
async def get_kalshi_swarm_critic_history():
    return {"history": [], "total": 0, "last_critic": None}

@app.get("/api/v1/kalshi/swarm/execution/stats")
async def get_kalshi_swarm_execution_stats():
    return {"stats": {"total_executions": 0, "success_rate": 0.0, "avg_latency": 0.0}}

@app.get("/api/v1/xtf/signals")
async def get_xtf_signals():
    return {"signals": [], "total": 0, "last_signal": None}

@app.get("/api/v1/kalshi/deployment/status")
async def get_kalshi_deployment_status():
    return {"status": "inactive", "version": "1.0.0", "deployed_at": None}

@app.get("/api/v1/kalshi/deployment/auto-promoter/status")
async def get_kalshi_deployment_auto_promoter_status():
    return {"status": "disabled", "last_promotion": None, "promotions": 0}

@app.get("/api/v1/kalshi/sentiment/lane-snapshot")
async def get_kalshi_sentiment_lane_snapshot():
    return {"snapshot": {}, "lanes": [], "timestamp": "2026-03-08T02:55:00.000Z"}

@app.get("/api/v1/kalshi-grid/sentiment")
async def get_kalshi_grid_sentiment():
    return {"sentiment": 0.0, "confidence": 0.0, "sources": []}

@app.get("/api/v1/sentiment/assets")
async def get_sentiment_assets():
    return {"assets": [], "total": 0, "sentiment_distribution": {}}

@app.get("/api/v1/sentiment/hashtags/signals")
async def get_sentiment_hashtags_signals():
    return {"signals": [], "hashtags": [], "total": 0}

@app.get("/api/v1/sentiment/monitor/status")
async def get_sentiment_monitor_status():
    return {"status": "active", "monitoring": [], "last_update": "2026-03-08T02:55:00.000Z"}

@app.get("/api/v1/kalshi/ai-insights")
async def get_kalshi_ai_insights():
    return {"insights": [], "total": 0, "last_insight": None}

@app.get("/api/v1/kalshi/publish-pipeline")
async def get_kalshi_publish_pipeline():
    return {"status": "idle", "queue": [], "published": 0}

@app.get("/api/v1/kalshi/volume-alerts")
async def get_kalshi_volume_alerts():
    return {"alerts": [], "total": 0, "last_alert": None}

@app.get("/api/v1/kalshi/liquidity-alerts")
async def get_kalshi_liquidity_alerts():
    return {"alerts": [], "total": 0, "last_alert": None}

@app.get("/api/v1/kalshi/pnl-history")
async def get_kalshi_pnl_history():
    return {"history": [], "total_pnl": 0.0, "daily_pnl": []}

@app.get("/api/v1/kalshi/volume-changes")
async def get_kalshi_volume_changes():
    return {"changes": [], "total_volume": 0.0, "significant_changes": []}

@app.get("/api/v1/kalshi/volume-anomalies")
async def get_kalshi_volume_anomalies():
    return {"anomalies": [], "total": 0, "severity": "low"}

@app.get("/api/v1/kalshi/errors/recent")
async def get_kalshi_errors_recent():
    return {"errors": [], "total": 0, "last_error": None}

@app.get("/api/v1/kalshi/categories")
async def get_kalshi_categories():
    return {"categories": [], "total": 0, "active": 0}

@app.get("/api/v1/kalshi/debate-stats")
async def get_kalshi_debate_stats():
    return {"stats": {"total_debates": 0, "active_debates": 0, "resolution_rate": 0.0}}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
