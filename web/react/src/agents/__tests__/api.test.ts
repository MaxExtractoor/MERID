/**
 * Tests for agents/api.ts normalizers — the contract layer between the
 * FastAPI surface and the seven-view UI.  These pin the verified backend
 * shapes so a silent schema drift fails loudly here, not as 'n/a' tiles.
 */

import {
  toMarketStateList, toAssetAgent, fetchGridSummary,
} from '../api';
import type { ServerAgent } from '../api';

describe('toMarketStateList', () => {
  it('maps the live /market-states row (cents-suffixed BBO + trust fields)', () => {
    const raw = {
      count: 1,
      states: {
        'KXBTC15M-TEST': {
          book_initialized: true,
          yes_bid_cents: 61,
          yes_ask_cents: 64,
          no_bid_cents: 36,
          no_ask_cents: 39,
          mid_cents: 62.5,
          spread_cents: 3,
          depth_10c: 1500,
          volume_24h: 42000,
          open_interest: 9000,
          seconds_to_expiry: 512.4,
          status: 'open',
          underlying: 'BTC',
          strike_price: 97000.5,
          floor_strike: 97000.0,
          external_spot: 97012.3,
          last_price_cents: 63,
          book_health: 'LIVE',
          executable: true,
          data_source: 'WS_LIVE',
          quote_owner: 'WS_FRESH_VERIFIED',
          data_quality: 'GOOD',
          book_age_ms: 420,
          last_update_ts: '2026-11-14T05:00:00+00:00',
          source: 'market_state_store',
        },
      },
      timestamp: 1730000000,
    };
    const [m] = toMarketStateList(raw);
    expect(m.ticker).toBe('KXBTC15M-TEST');
    expect(m.initialized).toBe(true);
    expect(m.yes_bid_c).toBe(61);
    expect(m.yes_ask_c).toBe(64);
    expect(m.no_bid_c).toBe(36);
    expect(m.no_ask_c).toBe(39);
    expect(m.mid_c).toBe(62.5);
    expect(m.spread_c).toBe(3);
    expect(m.depth_contracts).toBe(1500);
    expect(m.volume).toBe(42000);
    expect(m.open_interest).toBe(9000);
    expect(m.secs_to_expiry).toBeCloseTo(512.4);
    expect(m.status).toBe('open');
    expect(m.underlying).toBe('BTC');
    expect(m.strike).toBe(97000.5); // strike_price wins over floor_strike
    expect(m.external_spot).toBeCloseTo(97012.3);
    expect(m.last_price_c).toBe(63);
    expect(m.book_health).toBe('LIVE');
    expect(m.executable).toBe(true);
    expect(m.data_source).toBe('WS_LIVE');
    expect(m.quote_owner).toBe('WS_FRESH_VERIFIED');
    expect(m.data_quality).toBe('GOOD');
    expect(m.book_age_ms).toBe(420);
    expect(m.last_update_ts).toBe('2026-11-14T05:00:00+00:00');
  });

  it('handles array, {markets:[...]}, and bare ticker-keyed shapes', () => {
    const row = { ticker: 'KXX', book_initialized: true, mid_cents: 50 };
    expect(toMarketStateList([row])).toHaveLength(1);
    expect(toMarketStateList({ markets: [row] })).toHaveLength(1);
    expect(toMarketStateList({ states: [row] })).toHaveLength(1);
    expect(toMarketStateList({ KXX: row })[0].ticker).toBe('KXX');
    expect(toMarketStateList(null)).toEqual([]);
    expect(toMarketStateList('nope')).toEqual([]);
  });

  it('leaves missing fields undefined rather than fabricating zeroes', () => {
    const [m] = toMarketStateList([{ ticker: 'KXETH15M-X', book_initialized: false }]);
    expect(m.yes_bid_c).toBeUndefined();
    expect(m.mid_c).toBeUndefined();
    expect(m.book_age_ms).toBeUndefined();
    expect(m.executable).toBeUndefined();
  });
});

describe('toAssetAgent', () => {
  const base: ServerAgent = {
    name: 'BTC_15M',
    asset: 'BTC',
    enabled: true,
    running: true,
    state: 'SCANNING',
    market: { ticker: 'KXBTC15M-X', yes_bid_c: 60, yes_ask_c: 63, mid_c: 61.5 },
    lanes: [{ lane: 'settle', status: 'active' }],
  };

  it('passes through the enriched market block', () => {
    const a = toAssetAgent({
      ...base,
      market: {
        ...base.market,
        no_bid_c: 37,
        no_ask_c: 40,
        book_health: 'LIVE',
        executable: true,
        external_spot: 97000,
        last_price_c: 62,
        exchange_index: 2,
      },
    });
    expect(a).not.toBeNull();
    expect(a!.market?.no_bid_c).toBe(37);
    expect(a!.market?.book_health).toBe('LIVE');
    expect(a!.market?.executable).toBe(true);
    expect(a!.market?.exchange_index).toBe(2);
  });

  it('merges rejected_reason into last_decision when cycle lacks it', () => {
    const a = toAssetAgent({
      ...base,
      state: 'VETOED',
      rejected_reason: 'SKIP_MARKET_NOT_READY',
      rejected_detail: 'STALE:age=75s>t60s',
      cycle_decision: { rejection_reason: '' },
    });
    expect(a!.last_decision?.rejection_reason).toBe('SKIP_MARKET_NOT_READY');
    expect(a!.last_decision?.rejection_detail).toBe('STALE:age=75s>t60s');
  });

  it('returns null for unknown assets', () => {
    expect(toAssetAgent({ name: 'UNKNOWN_X', asset: 'XXX' })).toBeNull();
  });
});

describe('fetchGridSummary', () => {
  const realShape = {
    available: true,
    running: true,
    agent_count: 5,
    agents: [
      { name: 'BTC_15M', asset: 'BTC', enabled: true, running: true, rejection_reason: null },
      { name: 'ETH_15M', asset: 'ETH', enabled: true, running: true, rejection_reason: 'X' },
      { name: 'SOL_15M', asset: 'SOL', enabled: false, running: false, rejection_reason: null },
      { name: 'XRP_15M', asset: 'XRP', enabled: true, running: true, rejection_reason: null },
      { name: 'DOGE_15M', asset: 'DOGE', enabled: true, running: true, rejection_reason: null },
    ],
    executed_candidates: ['a', 'b'],
    exchange_positions: 2,
    open_orders: 1,
    loop: { running: true, tick: 42, cycle_count: 4200, cadence_seconds: 5 },
  };

  afterEach(() => jest.restoreAllMocks());

  it('normalizes the real /summary shape into UI fields', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => realShape,
    });
    const s = await fetchGridSummary();
    expect(s.available).toBe(true);
    expect(s.running).toBe(true);
    expect(s.agent_count).toBe(5);
    expect(s.agents_total).toBe(5);
    expect(s.agents_running).toBe(4);
    expect(s.exchange_positions).toBe(2);
    expect(s.open_orders).toBe(1);
    expect(s.loop?.cycle_count).toBe(4200);
  });

  it('leaves agents_running undefined when backend omits per-agent flags', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        available: true, running: true, agent_count: 2,
        agents: [{ name: 'A' }, { name: 'B' }],
      }),
    });
    const s = await fetchGridSummary();
    expect(s.agents_total).toBe(2);
    expect(s.agents_running).toBeUndefined();
  });

  it('handles the unavailable payload', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ available: false, reason: 'grid not initialized', running: false, agent_count: 0, loop: {} }),
    });
    const s = await fetchGridSummary();
    expect(s.available).toBe(false);
    expect(s.running).toBe(false);
    expect(s.agents_total).toBe(0);
    expect(s.agents_running).toBeUndefined();
  });

  it('hits the kalshi-grid endpoint', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => ({}) });
    await fetchGridSummary();
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('kalshi-grid/summary'),
      expect.anything(),
    );
  });
});
