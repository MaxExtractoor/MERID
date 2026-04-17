"""Deployment readiness checker — finds everything blocking 100% deployability."""
import sys, os, importlib, json
sys.path.insert(0, os.getcwd())

findings = {"critical": [], "high": [], "medium": [], "info": []}

def add(sev, msg):
    findings[sev].append(msg)
    print(f"  [{sev.upper()}] {msg}")

print("=" * 60)
print("DEPLOYMENT READINESS CHECK")
print("=" * 60)

# 1. Trade mode defaults to PAPER (not LIVE)
print("\n[1] Trade mode safety...")
try:
    from trading.trade_mode import get_trade_mode, TradeMode
    mode = get_trade_mode()
    if mode == TradeMode.LIVE:
        add("critical", "Trade mode is LIVE on startup! Must default to PAPER")
    else:
        add("info", f"Trade mode: {mode.value} (safe)")
except Exception as e:
    add("critical", f"Trade mode import failed: {e}")

# 2. MERID_ALLOW_LIVE_TRADES is not set
print("\n[2] Live trades gate...")
allow_live = os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower()
if allow_live in ("1", "true", "yes", "on"):
    add("critical", "MERID_ALLOW_LIVE_TRADES is enabled! Agents can place real orders")
else:
    add("info", f"MERID_ALLOW_LIVE_TRADES={allow_live} (safe)")

# 3. VenueGate defaults to simulated fills
print("\n[3] VenueGate mode...")
try:
    from merid.prediction.venue_gate import get_venue_gate
    gate = get_venue_gate()
    if gate.is_live:
        add("critical", "VenueGate is in LIVE mode! Orders will be real")
    elif not gate.should_simulate_fill():
        add("high", f"VenueGate mode={gate.mode.value} but simulate={gate.should_simulate_fill()}")
    else:
        add("info", f"VenueGate: mode={gate.mode.value}, simulate={gate.should_simulate_fill()}")
except Exception as e:
    add("high", f"VenueGate check failed: {e}")

# 4. Kill switch defaults
print("\n[4] Kill switch defaults...")
try:
    from merid.risk.kill_switches import risk_controller
    rc = risk_controller
    add("info", f"Kill switch: armed={rc._global_kill}, daily_loss_limit=${rc.daily_loss_limit}")
    if rc.daily_loss_limit > 1000:
        add("high", f"Daily loss limit is ${rc.daily_loss_limit} — consider lowering for paper mode")
    if rc.max_position_value > 50000:
        add("high", f"Max position value is ${rc.max_position_value} — consider lowering for paper mode")
except Exception as e:
    add("high", f"Kill switch check failed: {e}")

# 5. Execution guard
print("\n[5] Execution guard...")
try:
    from merid.execution_guard import get_execution_guard
    guard = get_execution_guard()
    add("info", f"Execution guard: kill_active={guard.kill_switch_active}")
except Exception as e:
    add("high", f"Execution guard check failed: {e}")

# 6. Agent grid config - check order limits
print("\n[6] Agent grid config...")
try:
    from merid.prediction.agent_grid_config import get_agent_grid_config
    cfg = get_agent_grid_config()
    for agent_cfg in cfg.agents:
        if agent_cfg.enabled:
            limits = agent_cfg.risk_limits
            if limits.max_notional_usd > 500:
                add("high", f"Agent {agent_cfg.name}: max_notional_usd={limits.max_notional_usd} (>$500)")
            if limits.max_orders_per_window > 20:
                add("medium", f"Agent {agent_cfg.name}: max_orders_per_window={limits.max_orders_per_window}")
    add("info", f"Agent grid: {len(cfg.agents)} agents configured, {sum(1 for a in cfg.agents if a.enabled)} enabled")
except Exception as e:
    add("high", f"Agent grid config check failed: {e}")

# 7. Settings validation
print("\n[7] Settings...")
try:
    from merid.settings import settings
    add("info", f"KALSHI_USE_DEMO={getattr(settings, 'KALSHI_USE_DEMO', 'NOT SET')}")
    if hasattr(settings, 'KALSHI_USE_DEMO') and not settings.KALSHI_USE_DEMO:
        add("critical", "KALSHI_USE_DEMO is False — will use PRODUCTION Kalshi API!")
    max_daily = getattr(settings, 'MERID_MAX_DAILY_LOSS_USD', None)
    max_pos = getattr(settings, 'MERID_MAX_POSITION_SIZE_USD', None)
    add("info", f"Max daily loss: ${max_daily}, Max position: ${max_pos}")
except Exception as e:
    add("medium", f"Settings check failed: {e}")

# 8. Key Python syntax check on recently modified files
print("\n[8] Syntax verification...")
import py_compile
key_files = [
    "merid/loop.py", "merid/prediction/trading_agent.py",
    "merid/prediction/kalshi_tools.py", "merid/prediction/agent_grid.py",
    "merid/prediction/venue_gate.py", "merid/execution_guard.py",
    "merid/risk/kill_switches.py", "trading/trade_mode.py",
    "web/main.py", "agents/reflection/__init__.py",
]
syntax_errors = 0
for fp in key_files:
    fp = fp.replace("/", os.sep)
    if os.path.exists(fp):
        try:
            py_compile.compile(fp, doraise=True)
        except py_compile.PyCompileError as e:
            add("critical", f"Syntax error in {fp}: {e}")
            syntax_errors += 1
add("info", f"Syntax check: {len(key_files)} files, {syntax_errors} errors")

# 9. Check for hardcoded live API keys in env
print("\n[9] Credential safety...")
env_path = ".env"
if os.path.exists(env_path):
    with open(env_path, 'r', errors='ignore') as f:
        env_content = f.read()
    if "KALSHI_ENV=live" in env_content:
        add("critical", ".env has KALSHI_ENV=live — will use production Kalshi!")
    if "MERID_TRADE_MODE=live" in env_content:
        add("critical", ".env has MERID_TRADE_MODE=live!")
    if "MERID_ALLOW_LIVE_TRADES=true" in env_content.lower():
        add("critical", ".env has MERID_ALLOW_LIVE_TRADES=true!")
    add("info", f".env file exists ({len(env_content)} bytes)")
else:
    add("info", "No .env file found")

# 10. Check loop config defaults
print("\n[10] Loop config defaults...")
try:
    from merid.loop import LoopConfig
    lc = LoopConfig()
    if lc.enable_execution:
        add("high", "LoopConfig.enable_execution defaults to True — agents can execute on startup")
    else:
        add("info", f"LoopConfig.enable_execution={lc.enable_execution} (safe)")
except Exception as e:
    add("high", f"LoopConfig check failed: {e}")

# Summary
print("\n" + "=" * 60)
total = sum(len(v) for v in findings.values())
print(f"CRITICAL: {len(findings['critical'])}")
print(f"HIGH:     {len(findings['high'])}")
print(f"MEDIUM:   {len(findings['medium'])}")
print(f"INFO:     {len(findings['info'])}")
print(f"TOTAL:    {total}")
print("=" * 60)

if findings["critical"]:
    print("\n*** BLOCKING DEPLOYMENT ***")
    for f in findings["critical"]:
        print(f"  !!! {f}")

with open("data/deploy_readiness.json", "w") as f:
    json.dump(findings, f, indent=2)
