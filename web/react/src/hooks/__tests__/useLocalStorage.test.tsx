import { renderHook, act } from '@testing-library/react';
import { useLocalStorage } from '../useLocalStorage';

// Mock localStorage
const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
  length: 0,
  key: jest.fn(),
};

Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
});

describe('useLocalStorage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('returns initial value when no stored value exists', () => {
    localStorageMock.getItem.mockReturnValue(null);

    const { result } = renderHook(() => 
      useLocalStorage('test-key', 'default-value')
    );

    expect(result.current[0]).toBe('default-value');
    expect(localStorageMock.getItem).toHaveBeenCalledWith('test-key');
  });

  it('returns stored value when it exists', () => {
    localStorageMock.getItem.mockReturnValue(JSON.stringify('stored-value'));

    const { result } = renderHook(() => 
      useLocalStorage('test-key', 'default-value')
    );

    expect(result.current[0]).toBe('stored-value');
  });

  it('updates localStorage when value changes', () => {
    localStorageMock.getItem.mockReturnValue(null);

    const { result } = renderHook(() => 
      useLocalStorage('test-key', 'default-value')
    );

    const [, setValue] = result.current;

    act(() => {
      setValue('new-value');
    });

    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      'test-key',
      JSON.stringify('new-value')
    );
  });

  it('handles complex objects', () => {
    const testObject = { name: 'Test', count: 42 };
    localStorageMock.getItem.mockReturnValue(JSON.stringify(testObject));

    const { result } = renderHook(() => 
      useLocalStorage('test-object', { name: 'Default', count: 0 })
    );

    expect(result.current[0]).toEqual(testObject);
  });

  it('handles arrays', () => {
    const testArray = [1, 2, 3];
    localStorageMock.getItem.mockReturnValue(JSON.stringify(testArray));

    const { result } = renderHook(() => 
      useLocalStorage('test-array', [])
    );

    expect(result.current[0]).toEqual(testArray);
  });

  it('handles invalid JSON gracefully', () => {
    localStorageMock.getItem.mockReturnValue('invalid-json');

    const { result } = renderHook(() => 
      useLocalStorage('test-key', 'default-value')
    );

    expect(result.current[0]).toBe('default-value');
  });

  it('supports custom serializer', () => {
    const customSerializer = {
      read: (value: string) => value.toUpperCase(),
      write: (value: string) => value.toLowerCase(),
    };

    localStorageMock.getItem.mockReturnValue('test-value');

    const { result } = renderHook(() => 
      useLocalStorage('test-key', 'default', { serializer: customSerializer })
    );

    expect(result.current[0]).toBe('TEST-VALUE');

    const [, setValue] = result.current;
    act(() => {
      setValue('NEW-VALUE');
    });

    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      'test-key',
      'new-value'
    );
  });

  it('removes item when value is set to null', () => {
    localStorageMock.getItem.mockReturnValue(JSON.stringify('stored-value'));

    const { result } = renderHook(() => 
      useLocalStorage('test-key', 'default-value')
    );

    const [, setValue] = result.current;

    act(() => {
      setValue(null as unknown as string);
    });

    expect(localStorageMock.removeItem).toHaveBeenCalledWith('test-key');
  });

  it('supports functional updates', () => {
    localStorageMock.getItem.mockReturnValue(JSON.stringify(5));

    const { result } = renderHook(() => 
      useLocalStorage('counter', 0)
    );

    const [, setValue] = result.current;

    act(() => {
      setValue(prev => prev + 1);
    });

    expect(result.current[0]).toBe(6);
    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      'counter',
      JSON.stringify(6)
    );
  });

  it('handles storage events from other tabs', () => {
    localStorageMock.getItem.mockReturnValue(null);

    const { result } = renderHook(() => 
      useLocalStorage('test-key', 'initial')
    );

    // Simulate storage event from another tab
    const storageEvent = new StorageEvent('storage', {
      key: 'test-key',
      newValue: JSON.stringify('updated-from-other-tab'),
    });

    act(() => {
      window.dispatchEvent(storageEvent);
    });

    expect(result.current[0]).toBe('updated-from-other-tab');
  });

  it('ignores storage events for different keys', () => {
    localStorageMock.getItem.mockReturnValue(null);

    const { result } = renderHook(() => 
      useLocalStorage('test-key', 'initial')
    );

    const storageEvent = new StorageEvent('storage', {
      key: 'different-key',
      newValue: JSON.stringify('should-not-update'),
    });

    act(() => {
      window.dispatchEvent(storageEvent);
    });

    expect(result.current[0]).toBe('initial');
  });

  it('handles null newValue in storage event (item removed)', () => {
    localStorageMock.getItem.mockReturnValue(JSON.stringify('stored-value'));

    const { result } = renderHook(() => 
      useLocalStorage('test-key', 'default-value')
    );

    const storageEvent = new StorageEvent('storage', {
      key: 'test-key',
      newValue: null,
    });

    act(() => {
      window.dispatchEvent(storageEvent);
    });

    expect(result.current[0]).toBe('default-value');
  });

  it('cleans up event listeners on unmount', () => {
    const addEventListenerSpy = jest.spyOn(window, 'addEventListener');
    const removeEventListenerSpy = jest.spyOn(window, 'removeEventListener');

    const { unmount } = renderHook(() => 
      useLocalStorage('test-key', 'default-value')
    );

    expect(addEventListenerSpy).toHaveBeenCalledWith('storage', expect.any(Function));

    unmount();

    expect(removeEventListenerSpy).toHaveBeenCalledWith('storage', expect.any(Function));

    addEventListenerSpy.mockRestore();
    removeEventListenerSpy.mockRestore();
  });

  it('supports sync across tabs option', () => {
    const addEventListenerSpy = jest.spyOn(window, 'addEventListener');

    renderHook(() => 
      useLocalStorage('test-key', 'default-value', { syncAcrossTabs: false })
    );

    expect(addEventListenerSpy).not.toHaveBeenCalledWith('storage', expect.any(Function));

    addEventListenerSpy.mockRestore();
  });

  it('handles errors in JSON parsing gracefully', () => {
    localStorageMock.getItem.mockReturnValue('{"incomplete": json');

    const { result } = renderHook(() => 
      useLocalStorage('test-key', 'default-value')
    );

    expect(result.current[0]).toBe('default-value');
  });
});
