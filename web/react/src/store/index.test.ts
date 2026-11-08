import { act, renderHook } from '@testing-library/react';
import { getJson, fetchLiveRuntimeState } from '../agents/api';
import { useKalshiStore } from './index';
import { useExecutionGate } from '../hooks/useExecutionGate';

jest.mock('../agents/api', () => ({
  AGENT_ENDPOINTS: {},
  getJson: jest.fn(),
  fetchLiveRuntimeState: jest.fn(),
}));
const get = getJson as jest.Mock;
const live = fetchLiveRuntimeState as jest.Mock;
const initial = useKalshiStore.getState();

beforeEach(() => {
  useKalshiStore.setState(initial, true);
  get.mockReset().mockResolvedValue({});
  live.mockReset().mockResolvedValue({ state: 'LIVE_ENTRIES_ENABLED', entry_halted: false });
});

test('older refresh cannot overwrite newer halted runtime state', async () => {
  let resolve!: (value: unknown) => void;
  live.mockReturnValueOnce(new Promise(done => { resolve = done; }));
  const old = useKalshiStore.getState().refreshAll();
  live.mockResolvedValueOnce({ state: 'LIVE_ENTRIES_HALTED', entry_halted: true });
  await useKalshiStore.getState().refreshAll();
  resolve({ state: 'LIVE_ENTRIES_ENABLED', entry_halted: false });
  await old;
  expect(useKalshiStore.getState().system.live?.entry_halted).toBe(true);
});

test('reachable backend with failed runtime probe is not safe to trade', async () => {
  await useKalshiStore.getState().refreshAll();
  live.mockRejectedValueOnce(new Error('401 Unauthorized'));
  await useKalshiStore.getState().refreshAll();
  expect(useKalshiStore.getState().connected).toBe(true);
  const { result } = renderHook(() => useExecutionGate());
  expect(result.current.safeToTrade).toBe(false);
  expect(result.current.gateState).toBe('limited');
});

test('gate ages out safety state even without another store update', async () => {
  jest.useFakeTimers();
  try {
    await useKalshiStore.getState().refreshAll();
    const { result, unmount } = renderHook(() => useExecutionGate());
    expect(result.current.safeToTrade).toBe(true);
    act(() => { jest.advanceTimersByTime(61_000); });
    expect(result.current.safeToTrade).toBe(false);
    unmount();
  } finally {
    jest.useRealTimers();
  }
});

test('initial unknown safety state is not clear even if connected', () => {
  useKalshiStore.getState().setConnected(true);
  const { result } = renderHook(() => useExecutionGate());
  expect(result.current.safeToTrade).toBe(false);
});
