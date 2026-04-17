from pathlib import Path

flags = [
    'MERID_TRADING_MODE',
    'MERID_LIVE_TRADING_UNLOCKED',
    'MERID_PM_TRADING_MODE',
    'MERID_PM_LIVE_ENABLED',
    'MERID_ENABLE_REAL_PREDICTION_MARKETS',
    'KALSHI_ONLY',
    'KALSHI_USE_DEMO',
    'KALSHI_API_KEY_ID',
    'KALSHI_PRIVATE_KEY_PATH',
    'MERID_ENABLE_LIVE_PRICE_FEEDS',
    'MERID_ENABLE_REAL_SOLANA_WS',
    'MERID_ENABLE_REAL_NEWS'
]
print('Flag usages:')
for flag in flags:
    print('\n', flag)
    matches = []
    for path in Path('.').rglob('*'):
        if path.is_file() and path.suffix in {'.py', '.ts', '.tsx', '.env'}:
            try:
                text = path.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            if flag in text:
                matches.append(str(path))
                if len(matches) >= 3:
                    break
    print('  sample paths:', matches if matches else ['(none)'])
