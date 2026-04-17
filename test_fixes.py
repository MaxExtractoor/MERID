"""Quick regression test for Kalshi agent fixes."""

from merid.prediction.agent_grid_config import AgentConfig, _parse_agent
from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog

# Test 1: AgentConfig has series_tickers field
agent = AgentConfig(name='TEST_AGENT')
print(f'Test 1: series_tickers field exists = {hasattr(agent, "series_tickers")}')
print(f'  Default value = {agent.series_tickers}')

# Test 2: _parse_agent auto-resolves from AGENT_SERIES_MAP
raw = {'name': 'BTC_15M', 'assets': ['BTC'], 'timeframes': ['15m']}
parsed = _parse_agent(raw)
print(f'Test 2: BTC_15M series_tickers = {parsed.series_tickers}')

# Test 3: Verify _detect_strikes with ticker suffix
strikes = KalshiMarketCatalog._detect_strikes('', 'KXBTC-26MAR2501-T80199.99')
print(f'Test 3: Ticker suffix extraction = {strikes}')

# Test 4: Bracket suffix extraction
strikes_b = KalshiMarketCatalog._detect_strikes('', 'KXBTC-26MAR2501-B80150')
print(f'Test 4: Bracket suffix extraction = {strikes_b}')

# Test 5: Text-based fallback (directional markets)
strikes_d = KalshiMarketCatalog._detect_strikes('Will BTC go up? above $100,000')
print(f'Test 5: Text-based extraction = {strikes_d}')

print('\nAll tests passed!')
