"""Scan for live vs paper mode gaps."""
from pathlib import Path, PurePath
import re

skip = {'__pycache__', '.git', 'node_modules', '_legacy', '.venv', 'venv', '.claude', 'worktrees', 'flutter'}

def scan(pattern, label, limit=25):
    results = []
    for p in Path('.').rglob('*.py'):
        parts = set(PurePath(p).parts)
        if parts & skip:
            continue
        try:
            text = p.read_text(encoding='utf-8', errors='ignore')
            if re.search(pattern, text):
                for i, line in enumerate(text.splitlines()):
                    if re.search(pattern, line):
                        results.append(f'{p}:{i+1}: {line.strip()}')
        except Exception:
            pass
    print(f'=== {label} ({len(results)}) ===')
    for r in results[:limit]:
        print(r)
    print()

# 1. Hardcoded simulated=True — orders that can NEVER go live
scan(r'simulated.*=.*True|"simulated".*True', 'Hardcoded simulated=True')

# 2. VenueGate — is it checked before every order?
scan(r'VenueGate|get_venue_gate|venue_gate', 'VenueGate usage')

# 3. ExecutionGate — is it checked before every order?
scan(r'ExecutionGate|execution_gate|get_execution_gate', 'ExecutionGate usage')

# 4. PM mode env vars — where are they read?
scan(r'MERID_PM_TRADING_MODE|MERID_PM_LIVE_ENABLED|pm_trading_mode|pm_live_enabled', 'PM mode env vars')

# 5. Live order routing — where does a real Kalshi order actually get placed?
scan(r'place_order_result|place_order\(|submit_order\(', 'Real order placement')

# 6. Kill switch — is it checked everywhere?
scan(r'kill_switch|KillSwitch|kill_switch_active', 'Kill switch checks')

# 7. Mode manager — where is TradingMode set/read?
scan(r'TradingMode\.(LIVE|PAPER|SIM|SIMULATION|HYBRID)', 'TradingMode enum usage')

# 8. Paper session — where is paper_session used?
scan(r'get_paper_session|paper_session|PaperSession', 'Paper session usage')
