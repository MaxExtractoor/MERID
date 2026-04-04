import { useState, useEffect, useCallback, useMemo } from "react";

interface UseLocalStorageOptions<T> {
  serializer?: {
    read: (value: string) => T;
    write: (value: T) => string;
  };
  syncAcrossTabs?: boolean;
}

export function useLocalStorage<T>(
  key: string,
  initialValue: T,
  options?: UseLocalStorageOptions<T>
): [T, (value: T | ((prev: T) => T)) => void, () => void] {
  const serializer = useMemo(() => {
    return options?.serializer ?? {
      read: (value: string) => {
        try {
          return JSON.parse(value);
        } catch {
          // Re-throw so readValue catches it and returns initialValue
          throw new Error('Failed to parse stored value');
        }
      },
      write: (value: T) => JSON.stringify(value),
    };
  }, [options?.serializer]);

  // Get from local storage then parse stored json or return initialValue
  const readValue = useCallback((): T => {
    try {
      const item = window.localStorage.getItem(key);
      if (!item) return initialValue;
      return serializer.read(item);
    } catch (error) {
      console.warn(`Error reading localStorage key "${key}":`, error);
      return initialValue;
    }
  }, [key, initialValue, serializer]);

  const [storedValue, setStoredValue] = useState<T>(readValue);

  // Return a wrapped version of useState's setter function that 
  // ... persists the new value to localStorage.
  const setValue = useCallback(
    (value: T | ((prev: T) => T) | null) => {
      try {
        // Allow value to be a function so we have the same API as useState
        const valueToStore =
          typeof value === 'function'
            ? (value as (prev: T) => T)(storedValue)
            : value;
        
        // Handle null - remove from localStorage
        if (valueToStore === null) {
          window.localStorage.removeItem(key);
          setStoredValue(initialValue);
          return;
        }
        
        // Save state
        setStoredValue(valueToStore);
        
        // Save to local storage
        if (typeof window !== "undefined") {
          window.localStorage.setItem(key, serializer.write(valueToStore));
        }
      } catch (error) {
        console.warn(`Error setting localStorage key "${key}":`, error);
      }
    },
    [key, storedValue, serializer, initialValue]
  );

  // Remove the key from localStorage
  const removeValue = useCallback(() => {
    try {
      if (typeof window !== "undefined") {
        window.localStorage.removeItem(key);
      }
      setStoredValue(initialValue);
    } catch (error) {
      console.warn(`Error removing localStorage key "${key}":`, error);
    }
  }, [key, initialValue]);

  // Listen for changes to local storage from other tabs
  useEffect(() => {
    // Skip if syncAcrossTabs is disabled
    if (options?.syncAcrossTabs === false) return;

    const handleStorageChange = (e: StorageEvent) => {
      if (e.key !== key) return;
      
      // Handle item removal (newValue is null)
      if (e.newValue === null) {
        setStoredValue(initialValue);
        return;
      }
      
      // Handle item update
      try {
        setStoredValue(serializer.read(e.newValue));
      } catch (error) {
        console.warn(`Error parsing localStorage change for key "${key}":`, error);
        // Reset to initialValue on parse error to prevent stale state
        setStoredValue(initialValue);
      }
    };

    // Add event listener
    if (typeof window !== "undefined") {
      window.addEventListener("storage", handleStorageChange);
    }

    // Remove event listener on cleanup
    return () => {
      if (typeof window !== "undefined") {
        window.removeEventListener("storage", handleStorageChange);
      }
    };
  }, [key, initialValue, serializer, options?.syncAcrossTabs]);

  return [storedValue, setValue, removeValue];
}
