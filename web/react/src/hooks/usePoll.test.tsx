import { StrictMode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { getJson } from '../agents/api';
import { usePoll } from './usePoll';

jest.mock('../agents/api', () => ({ getJson: jest.fn() }));
const get = getJson as jest.Mock;
const deferred = () => {
  let resolve!: (value: unknown) => void;
  const promise = new Promise(resolvePromise => { resolve = resolvePromise; });
  return { promise, resolve };
};

beforeEach(() => { jest.useFakeTimers(); get.mockReset(); });
afterEach(() => { jest.useRealTimers(); });

test('endpoint change discards old results and does not unlock a newer request', async () => {
  const old = deferred();
  const current = deferred();
  get.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
  const { result, rerender } = renderHook(({ path }) => usePoll(path, { ms: 100 }), { initialProps: { path: '/old' } });
  rerender({ path: '/new' });
  expect(get).toHaveBeenCalledTimes(2);
  await act(async () => { old.resolve('old'); });
  act(() => { jest.advanceTimersByTime(100); result.current.refresh(); });
  expect(get).toHaveBeenCalledTimes(2);
  expect(result.current.data).toBeUndefined();
  await act(async () => { current.resolve('new'); });
  expect(result.current.data).toBe('new');
});

test('disabled polling ignores pending results and manual refresh', async () => {
  const pending = deferred();
  get.mockReturnValue(pending.promise);
  const { result, rerender } = renderHook(({ enabled }) => usePoll('/data', { enabled }), { initialProps: { enabled: true } });
  rerender({ enabled: false });
  await act(async () => { pending.resolve('stale'); result.current.refresh(); });
  expect(result.current.data).toBeUndefined();
  expect(result.current.lastOk).toBeUndefined();
  expect(get).toHaveBeenCalledTimes(1);
});

test('StrictMode replay ignores the first effect request', async () => {
  const old = deferred();
  const current = deferred();
  get.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
  const { result } = renderHook(() => usePoll('/data', { ms: 0 }), { wrapper: ({ children }) => <StrictMode>{children}</StrictMode> });
  await act(async () => { current.resolve('current'); });
  await act(async () => { old.resolve('stale'); });
  expect(result.current.data).toBe('current');
});

test('failed refresh preserves last good data and timestamp', async () => {
  get.mockResolvedValueOnce('good').mockRejectedValueOnce(new Error('offline'));
  const { result } = renderHook(() => usePoll('/data', { ms: 0 }));
  await act(async () => { await Promise.resolve(); });
  const lastOk = result.current.lastOk;
  await act(async () => { result.current.refresh(); });
  expect(result.current.data).toBe('good');
  expect(result.current.lastOk).toBe(lastOk);
  expect(result.current.error).toBe('offline');
});
