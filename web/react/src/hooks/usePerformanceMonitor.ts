/**
 * Performance monitoring hooks for tracking render times, API call latency, and user interactions
 */

import { useEffect, useRef, useCallback } from 'react';
import React from 'react';
import { logUxEvent } from '../utils/uxTelemetry';

interface PerformanceMetrics {
  renderCount: number;
  renderTime: number;
  lastRender: number;
  apiLatency: number[];
  errors: number;
}

// Type definitions for Performance API
interface LayoutShift extends PerformanceEntry {
  hadRecentInput: boolean;
  value: number;
}

/**
 * Hook to monitor component render performance
 * Logs warnings when renders take too long or happen too frequently
 */
export function usePerformanceMonitor(componentName: string, options: {
  renderThresholdMs?: number;
  maxRendersPerSecond?: number;
  enableLogging?: boolean;
} = {}) {
  const { renderThresholdMs = 16, maxRendersPerSecond = 30, enableLogging = true } = options;
  
  const metricsRef = useRef<PerformanceMetrics>({
    renderCount: 0,
    renderTime: 0,
    lastRender: 0,
    apiLatency: [],
    errors: 0,
  });
  
  const renderStartRef = useRef<number>(0);
  const rendersInLastSecondRef = useRef<number[]>([]);

  useEffect(() => {
    if (!enableLogging) return;
    
    const now = performance.now();
    const renderTime = now - renderStartRef.current;
    
    metricsRef.current.renderCount++;
    metricsRef.current.renderTime = renderTime;
    metricsRef.current.lastRender = now;
    
    // Track renders in last second
    rendersInLastSecondRef.current = rendersInLastSecondRef.current
      .filter((t) => now - t < 1000)
      .concat(now);
    
    // Warn on slow renders
    if (renderTime > renderThresholdMs) {
      logUxEvent('performance', 'slow_render', {
        component: componentName,
        renderTime,
        threshold: renderThresholdMs,
      });
    }
    
    // Warn on excessive renders
    if (rendersInLastSecondRef.current.length > maxRendersPerSecond) {
      logUxEvent('performance', 'excessive_renders', {
        component: componentName,
        rendersPerSecond: rendersInLastSecondRef.current.length,
        threshold: maxRendersPerSecond,
      });
    }
  });

  // Mark render start
  renderStartRef.current = performance.now();

  const trackApiLatency = useCallback((latencyMs: number) => {
    metricsRef.current.apiLatency.push(latencyMs);
    
    // Keep only last 100 measurements
    if (metricsRef.current.apiLatency.length > 100) {
      metricsRef.current.apiLatency.shift();
    }
    
    // Log slow API calls
    if (latencyMs > 1000) {
      logUxEvent('performance', 'slow_api_call', {
        component: componentName,
        latencyMs,
      });
    }
  }, [componentName]);

  const trackError = useCallback(() => {
    metricsRef.current.errors++;
  }, []);

  const getMetrics = useCallback(() => ({
    ...metricsRef.current,
    averageRenderTime: metricsRef.current.renderCount > 0 
      ? metricsRef.current.renderTime / metricsRef.current.renderCount 
      : 0,
    averageApiLatency: metricsRef.current.apiLatency.length > 0
      ? metricsRef.current.apiLatency.reduce((a, b) => a + b, 0) / metricsRef.current.apiLatency.length
      : 0,
    rendersPerSecond: rendersInLastSecondRef.current.length,
  }), []);

  return {
    trackApiLatency,
    trackError,
    getMetrics,
  };
}

/**
 * Hook to measure API call performance with automatic logging
 */
export function useApiPerformance(endpoint: string) {
  const timingsRef = useRef<number[]>([]);

  const measure = useCallback(async <T>(operation: () => Promise<T>): Promise<T> => {
    const start = performance.now();
    
    try {
      const result = await operation();
      const duration = performance.now() - start;
      
      timingsRef.current.push(duration);
      if (timingsRef.current.length > 50) {
        timingsRef.current.shift();
      }
      
      // Log slow calls
      if (duration > 1000) {
        logUxEvent('performance', 'slow_api_response', {
          endpoint,
          durationMs: duration,
        });
      }
      
      return result;
    } catch (error) {
      const duration = performance.now() - start;
      logUxEvent('performance', 'api_error', {
        endpoint,
        durationMs: duration,
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      throw error;
    }
  }, [endpoint]);

  const getStats = useCallback(() => {
    const timings = timingsRef.current;
    if (timings.length === 0) return null;
    
    const sorted = [...timings].sort((a, b) => a - b);
    const sum = sorted.reduce((a, b) => a + b, 0);
    
    return {
      count: timings.length,
      average: sum / timings.length,
      min: sorted[0],
      max: sorted[sorted.length - 1],
      p50: sorted[Math.floor(sorted.length * 0.5)],
      p95: sorted[Math.floor(sorted.length * 0.95)],
      p99: sorted[Math.floor(sorted.length * 0.99)],
    };
  }, []);

  return { measure, getStats };
}

/**
 * Hook to track user interaction timing (e.g., time to first interaction)
 */
export function useInteractionTiming(componentName: string) {
  const startTimeRef = useRef<number>(performance.now());
  const hasInteractedRef = useRef<boolean>(false);

  const markInteraction = useCallback(() => {
    if (hasInteractedRef.current) return;
    
    hasInteractedRef.current = true;
    const timeToInteraction = performance.now() - startTimeRef.current;
    
    logUxEvent('performance', 'first_interaction', {
      component: componentName,
      timeToInteraction,
    });
  }, [componentName]);

  return { markInteraction };
}

/**
 * Utility to measure render time of a component
 * Wrap your component with this
 */
export function withPerformanceTracking<P extends object>(
  Component: React.ComponentType<P>,
  componentName: string
): React.FC<P> {
  return function PerformanceTrackedComponent(props: P) {
    const renderStart = performance.now();
    
    useEffect(() => {
      const renderTime = performance.now() - renderStart;
      
      if (renderTime > 16) {
        logUxEvent('performance', 'slow_component_render', {
          component: componentName,
          renderTime,
          props: Object.keys(props),
        });
      }
    });
    
    return React.createElement(Component, props);
  };
}

/**
 * Get Web Vitals metrics
 */
export function getWebVitals(): Promise<{
  lcp?: number;
  fid?: number;
  cls?: number;
  fcp?: number;
  ttfb?: number;
}> {
  return new Promise((resolve) => {
    const metrics: Record<string, number> = {};
    
    // Check if PerformanceObserver is available
    if (typeof PerformanceObserver === 'undefined') {
      resolve(metrics);
      return;
    }
    
    try {
      // Largest Contentful Paint
      const lcpObserver = new PerformanceObserver((list) => {
        const entries = list.getEntries();
        const lastEntry = entries[entries.length - 1];
        metrics.lcp = lastEntry.startTime;
        lcpObserver.disconnect();
      });
      lcpObserver.observe({ entryTypes: ['largest-contentful-paint'] });
      
      // First Input Delay
      const fidObserver = new PerformanceObserver((list) => {
        const firstEntry = list.getEntries()[0] as PerformanceEventTiming;
        metrics.fid = firstEntry.processingStart - firstEntry.startTime;
        fidObserver.disconnect();
      });
      fidObserver.observe({ entryTypes: ['first-input'] });
      
      // Cumulative Layout Shift
      const clsObserver = new PerformanceObserver((list) => {
        let clsValue = 0;
        for (const entry of list.getEntries()) {
          const layoutShift = entry as LayoutShift;
          if (!layoutShift.hadRecentInput) {
            clsValue += layoutShift.value;
          }
        }
        metrics.cls = clsValue;
      });
      clsObserver.observe({ entryTypes: ['layout-shift'] });
      
      // First Contentful Paint & TTFB
      setTimeout(() => {
        const paintEntries = performance.getEntriesByType('paint');
        for (const entry of paintEntries) {
          if (entry.name === 'first-contentful-paint') {
            metrics.fcp = entry.startTime;
          }
        }
        
        const navEntry = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming;
        if (navEntry) {
          metrics.ttfb = navEntry.responseStart - navEntry.startTime;
        }
        
        resolve(metrics);
      }, 5000);
    } catch {
      resolve(metrics);
    }
  });
}
