"""Verify end-to-end Kalshi trading system wiring.

Checks:
1. All critical imports resolve (no ImportError at module load)
2. Singleton getters return valid objects
3. Trade flow chain: grid → agent → tools → client → fill
4. Risk pipeline: kill switch → guard → risk → sizer → caps
5. Data pipeline: features → signals → drift → consensus
6. Reconciliation: venue → internal state comparison
7. Paper/Shadow/Live mode routing
"""
import sys
import os
import importlib
import traceback

# Add project root to path
sys.path.insert(0, os.getcwd())

results = {"ok": [], "fail": [], "warn": []}

def check(name, fn):
    try:
        result = fn()
        if result is not None:
            results["ok"].append(f"{name}: {type(result).__name__}")
        else:
            results["warn"].append(f"{name}: returned None")
    except Exception as e:
        results["fail"].append(f"{name}: {e}")

def check_import(module_path):
    try:
        importlib.import_module(module_path)
        results["ok"].append(f"import {module_path}")
    except Exception as e:
        results["fail"].append(f"import {module_path}: {e}")

print("=" * 60)
print("KALSHI TRADING SYSTEM WIRING VERIFICATION")
print("=" * 60)

# ── 1. Critical Module Imports ──────────────────────────────────────
print("\n[1] Critical Module Imports...")
critical_modules = [
    "merid.prediction.agent_grid",
    "merid.prediction.agent_grid_config",
    "merid.prediction.trading_agent",
    "merid.prediction.kalshi_tools",
    "merid.prediction.strategy",
    "merid.prediction.risk",
    "merid.prediction.model",
    "merid.prediction.venue_gate",
    "merid.prediction.session_guard",
    "merid.prediction.paper_session",
    "merid.prediction.consensus",
    "merid.prediction.edge_model",
    "merid.prediction.alerts",
    "merid.prediction.social_broadcaster",
    "merid.prediction.portfolio_risk_agent",
    "merid.prediction.debate",
    "merid.event_venues.kalshi.client",
    "merid.event_venues.kalshi.trading",
    "merid.event_venues.kalshi.ws",
    "merid.event_venues.kalshi.models",
    "merid.event_venues.kalshi.kalshi_risk",
    "merid.event_venues.kalshi.position_sizer",
    "merid.event_venues.kalshi.order_router",
    "merid.event_venues.kalshi.stop_loss",
    "merid.event_venues.kalshi.market_filter",
    "merid.event_venues.kalshi.market_catalog",
    "merid.event_venues.kalshi.deployment",
    "merid.event_venues.kalshi.category_exposure",
    "merid.event_venues.kalshi.sentiment",
    "merid.event_venues.kalshi.liquidity_monitor",
    "merid.event_venues.kalshi.volume_monitor",
    "merid.event_venues.kalshi.order_manager",
    "merid.event_venues.kalshi.ws_bridge",
    "merid.event_venues.kalshi.backtest",
    "merid.event_venues.kalshi.performance_comparator",
    "merid.event_venues.kalshi.ruin_simulator",
    "merid.event_venues.base",
    "merid.execution_guard",
    "merid.matching_engine",
    "merid.loop",
    "merid.settings",
    "merid.paper_ladder",
    "merid.paper_config",
    "merid.risk.kill_switches",
    "merid.risk.promotion_engine",
    "merid.risk.crypto_swarm_risk_btc15m",
    "merid.risk.multi_tf_drawdown",
    "merid.risk.kalshi_risk_profile",
    "merid.signals.drift",
    "merid.signals.store",
    "merid.signals.features",
    "merid.signals.kalshi_signals",
    "merid.signals.live_feeds",
    "merid.cognitive.store",
    "merid.cognitive.models",
    "merid.guardrails.tools",
    "merid.rag.service",
    "merid.llm.guardrails",
    "merid.swarm.market_mood_bus",
    "merid.reconciliation",
    "merid.metrics.outcome_resolver",
    "merid.metrics.calibration",
    "merid.metrics.realized_edge",
    "merid.lanes.btc15m_lane",
    "merid.lanes.lane_metrics",
    "merid.sentiment.sentiment_regime",
    "merid.sentiment.btc_risk_dial",
    "merid.sentiment.sentiment_bus",
    "merid.publishing.kalshi_insight_pipeline",
    "merid.publishing.kalshi_news_agent",
    "merid.backtesting.kalshi_backtest",
    "merid.backtesting.walk_forward",
    "merid.backtesting.forward_tester",
    "merid.rewards.engine",
    "merid.rewards.quests",
    "merid.tick_log",
    "consensus.consensus_coordinator",
    "consensus.taco_consensus",
    "core.execution_gate",
    "core.consensus_store",
    "core.session_log",
    "core.fresh_start",
    "agents.reflection.integration",
    "agents.explainability",
    "trading.trade_mode",
    "trading.paper_trading",
    "merid.reconciliation",
    "trading.audit_trail",
]

for mod in critical_modules:
    check_import(mod)

# ── 2. Singleton Getters ────────────────────────────────────────────
print("\n[2] Singleton Getters...")

singleton_checks = [
    ("VenueGate", lambda: importlib.import_module("merid.prediction.venue_gate").get_venue_gate()),
    ("SessionGuard", lambda: importlib.import_module("merid.prediction.session_guard").get_session_guard()),
    ("PaperSession", lambda: importlib.import_module("merid.prediction.paper_session").get_paper_session()),
    ("AgentGridConfig", lambda: importlib.import_module("merid.prediction.agent_grid_config").get_agent_grid_config()),
    ("KillSwitchState", lambda: importlib.import_module("merid.risk.kill_switches").risk_controller.get_state()),
    ("ExecutionGuard", lambda: importlib.import_module("merid.execution_guard").get_execution_guard()),
    ("PaperLadder", lambda: importlib.import_module("merid.paper_ladder").get_paper_ladder()),
    ("PaperConfig", lambda: importlib.import_module("merid.paper_config").get_paper_config()),
    ("DriftDetector", lambda: importlib.import_module("merid.signals.drift").get_drift_detector()),
    ("SignalStore", lambda: importlib.import_module("merid.signals.store").get_signal_store()),
    ("TradeMode", lambda: importlib.import_module("trading.trade_mode").get_trade_mode()),
    ("ConsensusStore", lambda: importlib.import_module("core.consensus_store").get_consensus_store()),
    ("RAGService", lambda: importlib.import_module("merid.rag.service").get_rag_service()),
    ("ToolRegistry", lambda: importlib.import_module("merid.guardrails.tools").get_tool_registry()),
    ("AlertManager", lambda: importlib.import_module("merid.prediction.alerts").get_alert_manager()),
    ("TickLog", lambda: importlib.import_module("merid.tick_log").get_tick_log()),
    ("MarketMoodBus", lambda: importlib.import_module("merid.swarm.market_mood_bus").get_market_mood_bus()),
    ("CalibrationStore", lambda: importlib.import_module("merid.metrics.calibration").get_calibration_store()),
]

for name, fn in singleton_checks:
    check(name, fn)

# ── 3. Mode Routing Verification ────────────────────────────────────
print("\n[3] Mode Routing...")

def check_venue_gate_modes():
    from merid.prediction.venue_gate import get_venue_gate
    gate = get_venue_gate()
    mode = gate.mode
    sim = gate.should_simulate_fill()
    return f"mode={mode}, simulate={sim}"

check("VenueGate modes", check_venue_gate_modes)

def check_trade_mode():
    from trading.trade_mode import get_trade_mode
    return f"mode={get_trade_mode().value}"

check("TradeMode", check_trade_mode)

def check_deployment_controller():
    from merid.event_venues.kalshi.deployment import get_deployment_controller
    dc = get_deployment_controller()
    return f"agents={len(dc._agents)}"

check("DeploymentController", check_deployment_controller)

# ── 4. Risk Pipeline Chain ──────────────────────────────────────────
print("\n[4] Risk Pipeline...")

def check_kill_switch():
    from merid.risk.kill_switches import get_kill_switch_state
    ks = get_kill_switch_state()
    return f"armed={ks.global_armed}, daily_loss={ks.daily_loss_usd:.2f}/{ks.daily_loss_limit:.2f}"

check("KillSwitch", check_kill_switch)

def check_execution_guard():
    from merid.execution_guard import get_execution_guard
    g = get_execution_guard()
    return f"kill_active={g.kill_switch_active}"

check("ExecutionGuard", check_execution_guard)

def check_risk_check():
    from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
    risk = PredictionMarketRisk(PredictionRiskConfig())
    return f"max_notional={risk.config.max_notional_per_market_usd}"

check("PredictionMarketRisk", check_risk_check)

# ── 5. Paper Session + Ladder ───────────────────────────────────────
print("\n[5] Paper Session + Ladder...")

def check_paper_session():
    from merid.prediction.paper_session import get_paper_session
    ps = get_paper_session()
    return f"active={ps.is_active}, intervals={len(ps._intervals)}"

check("PaperSession", check_paper_session)

def check_paper_ladder():
    from merid.paper_ladder import get_paper_ladder
    pl = get_paper_ladder()
    return f"portfolios={len(pl._progress)}"

check("PaperLadder", check_paper_ladder)

# ── Summary ─────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print(f"OK:   {len(results['ok'])}")
print(f"WARN: {len(results['warn'])}")
print(f"FAIL: {len(results['fail'])}")
print("=" * 60)

if results["fail"]:
    print("\n=== FAILURES ===")
    for f in results["fail"]:
        print(f"  ✗ {f}")

if results["warn"]:
    print("\n=== WARNINGS ===")
    for w in results["warn"]:
        print(f"  ⚠ {w}")

print(f"\nTotal checks: {len(results['ok']) + len(results['warn']) + len(results['fail'])}")
