"""Scan for live vs paper mode gaps — round 2."""
from pathlib import Path, PurePath
import re

skip = {'__pycache__', '.git', 'node_modules', '_legacy', '.venv', 'venv', '.claude', 'worktrees', 'flutter', 'scripts'}

def scan(pattern, label, limit=20, include=None):
    results = []
    for p in Path('.').rglob('*.py'):
        parts = set(PurePath(p).parts)
        if parts & skip:
            continue
        if include and not any(str(p).startswith(i) for i in include):
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

# 1. Places that call place_order / submit_order WITHOUT checking VenueGate or DeploymentController
scan(r'place_order\(|submit_order\(', 'Direct order calls (not in kalshi_tools)', limit=30)

# 2. Paper session record_fill — is it called consistently on all fill paths?
scan(r'record_fill|record_error|record_win|record_loss', 'PaperSession record calls')

# 3. Reconciliation — does it distinguish live vs paper fills?
scan(r'reconcil|settlement|_fire_settlement', 'Reconciliation paths')

# 4. PnL tracking — are paper PnL and live PnL tracked separately?
scan(r'paper_pnl|live_pnl|simulated.*pnl|pnl.*simulated', 'PnL separation')

# 5. Position tracking — are paper positions kept separate from live?
scan(r'paper_position|live_position|simulated.*position', 'Position separation')

# 6. Balance / equity — does paper use a fake balance, live uses real?
scan(r'PAPER_STARTING_BALANCE|paper_balance|paper_equity|fake_balance|starting_balance', 'Paper balance')

# 7. Order manager — does it handle both paper and live fills?
scan(r'OrderManager|order_manager', 'OrderManager usage', limit=15)

# 8. KalshiTrader — does it have a paper mode?
scan(r'class KalshiTrader|KalshiTrader\(', 'KalshiTrader instantiation')

# 9. Promotion engine — what triggers paper->live promotion?
scan(r'PromotionEngine|promotion_engine|promote_to_live|check_readiness', 'Promotion engine')

# 10. Paper session check_readiness — is it called before promotion?
scan(r'check_readiness|readiness_verdict|is_ready', 'Readiness checks')
