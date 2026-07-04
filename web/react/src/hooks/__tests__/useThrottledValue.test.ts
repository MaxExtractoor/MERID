/**
 * useThrottledValue unit tests
 */

import { renderHook, act } from '@testing-library/react';
import { useThrottledValue } from '../useThrottledValue';

describe('useThrottledValue', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('returns initial value immediately', () => {
    const { result } = renderHook(() => useThrottledValue('initial', 100));
    expect(result.current).toBe('initial');
  });

  it('throttles value updates', () => {
    const { result, rerender } = renderHook(
      ({ value }) => useThrottledValue(value, 100),
      { initialProps: { value: 'initial' } }
    );

    rerender({ value: 'updated' });
    expect(result.current).toBe('initial'); // Not updated yet

    act(() => {
      jest.advanceTimersByTime(100);
    });

    expect(result.current).toBe('updated');
  });

  it('updates immediately after delay', () => {
    const { result, rerender } = renderHook(
      ({ value }) => useThrottledValue(value, 50),
      { initialProps: { value: 'initial' } }
    );

    rerender({ value: 'updated' });
    
    act(() => {
      jest.advanceTimersByTime(50);
    });

    expect(result.current).toBe('updated');
  });

  it('cleans up timeout on unmount', () => {
    const { result, unmount } = renderHook(() => useThrottledValue('test', 100));
    
    unmount();
    
    act(() => {
      jest.advanceTimersByTime(100);
    });

    // Should not throw error
    expect(result.current).toBe('test');
  });
});
