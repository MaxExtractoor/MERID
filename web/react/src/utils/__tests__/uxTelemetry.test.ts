/**
 * Tests for UX Telemetry utility.
 */

import { logUxEvent, getUxEvents, clearUxEvents, getUxStats } from '../uxTelemetry';

describe('uxTelemetry', () => {
  beforeEach(() => {
    clearUxEvents();
  });

  it('logs events into the buffer', () => {
    logUxEvent('tab_change', 'crypto-hourly');
    logUxEvent('favorite_toggle', 'KXBTC-123');
    const events = getUxEvents();
    expect(events.length).toBe(2);
    expect(events[0].action).toBe('tab_change');
    expect(events[0].target).toBe('crypto-hourly');
    expect(events[1].action).toBe('favorite_toggle');
  });

  it('includes timestamps', () => {
    const before = Date.now();
    logUxEvent('ticket_open', 'KXETH-456');
    const after = Date.now();
    const events = getUxEvents();
    expect(events[0].ts).toBeGreaterThanOrEqual(before);
    expect(events[0].ts).toBeLessThanOrEqual(after);
  });

  it('stores optional meta', () => {
    logUxEvent('risk_action', 'downsize', { asset: 'BTC', factor: 0.5 });
    const events = getUxEvents();
    expect(events[0].meta).toEqual({ asset: 'BTC', factor: 0.5 });
  });

  it('clears events', () => {
    logUxEvent('test', 'a');
    logUxEvent('test', 'b');
    clearUxEvents();
    expect(getUxEvents().length).toBe(0);
  });

  it('returns stats by action', () => {
    logUxEvent('tab_change', 'all');
    logUxEvent('tab_change', 'crypto-hourly');
    logUxEvent('favorite_toggle', 'XYZ');
    const stats = getUxStats();
    expect(stats.total).toBe(3);
    expect(stats.byAction['tab_change']).toBe(2);
    expect(stats.byAction['favorite_toggle']).toBe(1);
    expect(stats.lastEvent).toBeGreaterThan(0);
  });
});
