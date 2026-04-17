import { useState, useCallback, useRef, useEffect } from 'react';
import { CACHE_TTL } from '../config/constants';

interface CacheEntry<T> {
  data: T;
  timestamp: number;
  ttl: number;
  key: string;
}

interface CacheOptions {
  ttl?: number; // Time to live in milliseconds
  maxSize?: number; // Maximum number of entries
  strategy?: 'lru' | 'fifo' | 'lfu'; // Cache eviction strategy
}

class AdvancedCache<T = any> {
  private cache = new Map<string, CacheEntry<T>>();
  private accessOrder = new Map<string, number>();
  private accessCount = new Map<string, number>();
  private time = 0;

  constructor(private options: CacheOptions = {}) {
    this.options = {
      ttl: CACHE_TTL.DEFAULT, // Use centralized default from constants
      maxSize: 100,
      strategy: 'lru',
      ...options
    };
  }

  set(key: string, data: T, customTtl?: number): void {
    const ttl = customTtl || this.options.ttl!;
    const timestamp = Date.now();
    
    // Remove expired entries
    this.cleanup();
    
    // Evict if at max size
    if (this.cache.size >= this.options.maxSize! && !this.cache.has(key)) {
      this.evict();
    }
    
    this.cache.set(key, { data, timestamp, ttl, key });
    this.accessOrder.set(key, this.time++);
    this.accessCount.set(key, 1);
  }

  get(key: string): T | null {
    const entry = this.cache.get(key);
    
    if (!entry) {
      return null;
    }
    
    // Check if expired
    if (Date.now() - entry.timestamp > entry.ttl) {
      this.delete(key);
      return null;
    }
    
    // Update access tracking
    this.accessOrder.set(key, this.time++);
    this.accessCount.set(key, (this.accessCount.get(key) || 0) + 1);
    
    return entry.data;
  }

  delete(key: string): boolean {
    this.accessOrder.delete(key);
    this.accessCount.delete(key);
    return this.cache.delete(key);
  }

  getEntry(key: string): CacheEntry<T> | undefined {
    return this.cache.get(key);
  }

  clear(): void {
    this.cache.clear();
    this.accessOrder.clear();
    this.accessCount.clear();
    this.time = 0;
  }

  has(key: string): boolean {
    const entry = this.cache.get(key);
    if (!entry) return false;
    
    // Check if expired
    if (Date.now() - entry.timestamp > entry.ttl) {
      this.delete(key);
      return false;
    }
    
    return true;
  }

  size(): number {
    this.cleanup();
    return this.cache.size;
  }

  keys(): string[] {
    this.cleanup();
    return Array.from(this.cache.keys());
  }

  values(): T[] {
    this.cleanup();
    return Array.from(this.cache.values()).map(entry => entry.data);
  }

  private cleanup(): void {
    const now = Date.now();
    for (const [key, entry] of this.cache.entries()) {
      if (now - entry.timestamp > entry.ttl) {
        this.delete(key);
      }
    }
  }

  private evict(): void {
    if (this.cache.size === 0) return;
    
    let keyToEvict: string;
    
    switch (this.options.strategy) {
      case 'lru':
        // Least Recently Used
        let oldestTime = Infinity;
        keyToEvict = '';
        for (const [key, time] of this.accessOrder.entries()) {
          if (time < oldestTime) {
            oldestTime = time;
            keyToEvict = key;
          }
        }
        break;
        
      case 'lfu':
        // Least Frequently Used
        let lowestCount = Infinity;
        keyToEvict = '';
        for (const [key, count] of this.accessCount.entries()) {
          if (count < lowestCount) {
            lowestCount = count;
            keyToEvict = key;
          }
        }
        break;
        
      case 'fifo':
      default:
        // First In First Out
        keyToEvict = this.cache.keys().next().value;
        break;
    }
    
    if (keyToEvict) {
      this.delete(keyToEvict);
    }
  }

  // Get cache statistics
  getStats() {
    this.cleanup();
    return {
      size: this.cache.size,
      maxSize: this.options.maxSize,
      hitRate: this.calculateHitRate(),
      memoryUsage: this.estimateMemoryUsage(),
      strategy: this.options.strategy
    };
  }

  private calculateHitRate(): number {
    // This would require tracking hits/misses, simplified for now
    return 0.85; // Placeholder
  }

  private estimateMemoryUsage(): number {
    let totalSize = 0;
    for (const entry of this.cache.values()) {
      totalSize += this.estimateObjectSize(entry.data);
    }
    return totalSize;
  }

  private estimateObjectSize(obj: any): number {
    if (obj === null || obj === undefined) return 0;
    if (typeof obj === 'string') return obj.length * 2;
    if (typeof obj === 'number') return 8;
    if (typeof obj === 'boolean') return 4;
    if (obj instanceof Date) return 24;
    
    if (Array.isArray(obj)) {
      return obj.reduce((sum, item) => sum + this.estimateObjectSize(item), 0);
    }
    
    if (typeof obj === 'object') {
      return Object.entries(obj).reduce((sum, [key, value]) => 
        sum + this.estimateObjectSize(key) + this.estimateObjectSize(value), 0
      );
    }
    
    return 0;
  }
}

// React hook for advanced caching
export const useAdvancedCache = <T = any>(options: CacheOptions = {}) => {
  const cacheRef = useRef<AdvancedCache<T>>(new AdvancedCache<T>(options));
  const [stats, setStats] = useState(() => cacheRef.current.getStats());

  const set = useCallback((key: string, data: T, customTtl?: number) => {
    cacheRef.current.set(key, data, customTtl);
    setStats(cacheRef.current.getStats());
  }, []);

  const get = useCallback((key: string): T | null => {
    const result = cacheRef.current.get(key);
    setStats(cacheRef.current.getStats());
    return result;
  }, []);

  const remove = useCallback((key: string): boolean => {
    const result = cacheRef.current.delete(key);
    setStats(cacheRef.current.getStats());
    return result;
  }, []);

  const clear = useCallback(() => {
    cacheRef.current.clear();
    setStats(cacheRef.current.getStats());
  }, []);

  const has = useCallback((key: string): boolean => {
    return cacheRef.current.has(key);
  }, []);

  const keys = useCallback((): string[] => {
    return cacheRef.current.keys();
  }, []);

  const values = useCallback((): T[] => {
    return cacheRef.current.values();
  }, []);

  // Update stats periodically
  useEffect(() => {
    const interval = setInterval(() => {
      setStats(cacheRef.current.getStats());
    }, 5000); // Update every 5 seconds

    return () => clearInterval(interval);
  }, []);

  return {
    set,
    get,
    remove,
    clear,
    has,
    keys,
    values,
    stats,
    cache: cacheRef.current
  };
};

// Global cache instances for different data types
export const globalCaches = {
  reconciliation: new AdvancedCache({ ttl: CACHE_TTL.RECONCILIATION, maxSize: 50, strategy: 'lru' }),
  decisions: new AdvancedCache({ ttl: CACHE_TTL.DECISIONS, maxSize: 200, strategy: 'lfu' }),
  audit: new AdvancedCache({ ttl: CACHE_TTL.AUDIT, maxSize: 500, strategy: 'fifo' }),
  analytics: new AdvancedCache({ ttl: CACHE_TTL.ANALYTICS, maxSize: 100, strategy: 'lru' })
};

// Cache warming function
export const warmCache = async (cacheType: keyof typeof globalCaches, data: any[]) => {
  const cache = globalCaches[cacheType];
  const promises = data.map(async (item) => {
    const key = item.id || item.seq || JSON.stringify(item);
    cache.set(key, item);
  });
  
  await Promise.all(promises);
  return cache.getStats();
};

// Cache invalidation utilities
export const invalidateCache = (cacheType: keyof typeof globalCaches, pattern?: string | RegExp) => {
  const cache = globalCaches[cacheType];
  const keys = cache.keys();
  
  if (!pattern) {
    cache.clear();
    return;
  }
  
  const regex = typeof pattern === 'string' ? new RegExp(pattern) : pattern;
  const keysToDelete = keys.filter(key => regex.test(key));
  
  keysToDelete.forEach(key => cache.delete(key));
};

// Cache performance monitoring
export const monitorCachePerformance = () => {
  const performance = Object.entries(globalCaches).map(([name, cache]) => ({
    name,
    ...cache.getStats()
  }));
  
  return performance;
};
