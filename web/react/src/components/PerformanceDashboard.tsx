import React, { useState, useEffect } from 'react';
import { Icon } from '../ui/icons';
import { usePerformanceMonitor, globalCaches, cleanupExpiredCache } from '../hooks/useOptimizedData';

interface PerformanceMetrics {
  timestamp: number;
  cacheStats: Array<{
    name: string;
    size: number;
    maxSize?: number;
    hitRate: number;
    memoryUsage: number;
    strategy?: string;
  }>;
  networkStats: {
    totalRequests: number;
    failedRequests: number;
    avgResponseTime: number;
  };
  systemStats: {
    memoryUsed: number;
    memoryTotal: number;
    cpuUsage: number;
  };
}

const PerformanceDashboard: React.FC = () => {
  const [metrics, setMetrics] = useState<PerformanceMetrics | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selectedCache, setSelectedCache] = useState<string>('all');
  const [showDetails, setShowDetails] = useState(false);

  const performance = usePerformanceMonitor();

  useEffect(() => {
    if (autoRefresh) {
      const interval = setInterval(() => {
        const systemStats = getSystemStats();
        setMetrics({
          timestamp: Date.now(),
          cacheStats: performance.cacheStats,
          networkStats: performance.networkStats,
          systemStats
        });
      }, 2000);

      return () => clearInterval(interval);
    }
  }, [autoRefresh, performance]);

  const getSystemStats = () => {
    // Simulated system stats - in production, this would come from a monitoring API
    const memoryUsed = performance.cacheStats.reduce((sum, cache) => sum + cache.memoryUsage, 0);
    return {
      memoryUsed: memoryUsed / 1024 / 1024, // Convert to MB
      memoryTotal: 512, // Simulated total memory in MB
      cpuUsage: Math.random() * 20 + 10 // Simulated CPU usage 10-30%
    };
  };

  const handleCleanup = () => {
    cleanupExpiredCache();
    // Force refresh of metrics
    setTimeout(() => {
      const systemStats = getSystemStats();
      setMetrics({
        timestamp: Date.now(),
        cacheStats: performance.cacheStats,
        networkStats: performance.networkStats,
        systemStats
      });
    }, 100);
  };

  const handleClearCache = (cacheName: string) => {
    if (cacheName === 'all') {
      Object.values(globalCaches).forEach(cache => cache.clear());
    } else {
      const cache = globalCaches[cacheName as keyof typeof globalCaches];
      if (cache) cache.clear();
    }
    handleCleanup();
  };

  const getCacheHealthColor = (cache: any) => {
    const utilization = cache.size / cache.maxSize;
    if (utilization > 0.9) return 'text-red-400';
    if (utilization > 0.7) return 'text-amber-400';
    return 'text-green-400';
  };

  const getMemoryColor = (usage: number, total: number) => {
    const utilization = usage / total;
    if (utilization > 0.9) return 'text-red-400';
    if (utilization > 0.7) return 'text-amber-400';
    return 'text-green-400';
  };

  if (!metrics) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-6">
        <div className="flex items-center gap-2 text-slate-500">
          <Icon name="loading" size={20} className="w-5 h-5 animate-spin" />
          <span>Loading performance metrics...</span>
        </div>
      </div>
    );
  }

  const filteredCacheStats = selectedCache === 'all' 
    ? metrics.cacheStats 
    : metrics.cacheStats.filter(cache => cache.name === selectedCache);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon name="activity" size={20} className="w-5 h-5 text-green-400" />
          <h2 className="text-lg font-bold text-white">Performance Dashboard</h2>
        </div>
        
        <div className="flex items-center gap-3">
          {/* Auto Refresh Toggle */}
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`flex items-center gap-1.5 px-2 py-1 text-xs rounded transition-colors ${
              autoRefresh 
                ? 'bg-green-600 text-white' 
                : 'bg-slate-700 text-slate-400'
            }`}
            title="Toggle auto refresh"
          >
            <Icon name="refresh" size={12} className="w-3 h-3" />
            Auto
          </button>
          
          {/* Details Toggle */}
          <button
            onClick={() => setShowDetails(!showDetails)}
            className={`flex items-center gap-1.5 px-2 py-1 text-xs rounded transition-colors ${
              showDetails 
                ? 'bg-purple-600 text-white' 
                : 'bg-slate-700 text-slate-400'
            }`}
            title="Toggle detailed view"
          >
            <Icon name="settings" size={12} className="w-3 h-3" />
            Details
          </button>
          
          {/* Cleanup Button */}
          <button
            onClick={handleCleanup}
            className="flex items-center gap-1.5 px-2 py-1 text-xs bg-amber-600 hover:bg-amber-700 text-white rounded transition-colors"
            title="Cleanup expired cache entries"
          >
            <Icon name="trash" size={12} className="w-3 h-3" />
            Cleanup
          </button>
        </div>
      </div>

      {/* System Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Memory Usage</div>
          <div className={`text-lg font-bold ${getMemoryColor(metrics.systemStats.memoryUsed, metrics.systemStats.memoryTotal)}`}>
            {(metrics.systemStats.memoryUsed ?? 0).toFixed(1)}MB / {metrics.systemStats.memoryTotal ?? 0}MB
          </div>
          <div className="text-xs text-slate-400 mt-1">
            {(((metrics.systemStats.memoryUsed ?? 0) / (metrics.systemStats.memoryTotal || 1)) * 100).toFixed(1)}% utilized
          </div>
        </div>
        
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">CPU Usage</div>
          <div className={`text-lg font-bold ${
            metrics.systemStats.cpuUsage > 80 ? 'text-red-400' : 
            metrics.systemStats.cpuUsage > 60 ? 'text-amber-400' : 'text-green-400'
          }`}>
            {(metrics.systemStats.cpuUsage ?? 0).toFixed(1)}%
          </div>
          <div className="text-xs text-slate-400 mt-1">
            {metrics.systemStats.cpuUsage > 80 ? 'High load' : metrics.systemStats.cpuUsage > 60 ? 'Moderate load' : 'Normal'}
          </div>
        </div>
        
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Network Requests</div>
          <div className="text-lg font-bold text-blue-400">
            {metrics.networkStats.totalRequests}
          </div>
          <div className="text-xs text-slate-400 mt-1">
            {metrics.networkStats.failedRequests ?? 0} failed • {(metrics.networkStats.avgResponseTime ?? 0).toFixed(0)}ms avg
          </div>
        </div>
      </div>

      {/* Cache Filter */}
      <div className="flex items-center gap-3">
        <select
          value={selectedCache}
          onChange={(e) => setSelectedCache(e.target.value)}
          className="text-xs bg-slate-700 border border-slate-600 rounded px-2 py-1 text-white"
          title="Filter by cache"
        >
          <option value="all">All Caches</option>
          {metrics.cacheStats.map(cache => (
            <option key={cache.name} value={cache.name}>{cache.name}</option>
          ))}
        </select>
        
        <button
          onClick={() => handleClearCache(selectedCache)}
          className="flex items-center gap-1.5 px-2 py-1 text-xs bg-red-600 hover:bg-red-700 text-white rounded transition-colors"
          title={`Clear ${selectedCache} cache`}
        >
          <Icon name="x" size={12} className="w-3 h-3" />
          Clear {selectedCache === 'all' ? 'All' : selectedCache}
        </button>
      </div>

      {/* Cache Statistics */}
      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-slate-300">Cache Performance</h3>
        
        <div className="space-y-2">
          {filteredCacheStats.map((cache) => (
            <div key={cache.name} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-white">{cache.name}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${getCacheHealthColor(cache)}`}>
                    {cache.strategy}
                  </span>
                </div>
                
                <div className="flex items-center gap-3 text-xs">
                  <span className={getCacheHealthColor(cache)}>
                    {cache.size}/{cache.maxSize}
                  </span>
                  <span className="text-slate-400">
                    {cache.hitRate > 0 ? (cache.hitRate * 100).toFixed(1) : '0'}% hit rate
                  </span>
                  <span className="text-slate-400">
                    {(cache.memoryUsage / 1024).toFixed(1)}KB
                  </span>
                </div>
              </div>
              
              {/* Progress Bar */}
              <div className="w-full bg-slate-700 rounded-full h-2">
                <div 
                  className={`h-2 rounded-full transition-all ${
                    cache.size / (cache.maxSize ?? 1) > 0.9 ? 'bg-red-500' :
                    cache.size / (cache.maxSize ?? 1) > 0.7 ? 'bg-amber-500' : 'bg-green-500'
                  }`}
                  style={{ width: `${(cache.size / (cache.maxSize ?? 1)) * 100}%` }}
                />
              </div>
              
              {/* Detailed Stats */}
              {showDetails && (
                <div className="mt-3 pt-3 border-t border-slate-700/50 grid grid-cols-3 gap-4 text-xs">
                  <div>
                    <span className="text-slate-400">Utilization:</span>
                    <span className="ml-2 text-white">
                      {((cache.size / (cache.maxSize ?? 1)) * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400">Memory:</span>
                    <span className="ml-2 text-white">
                      {(cache.memoryUsage / 1024).toFixed(1)}KB
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400">Hit Rate:</span>
                    <span className="ml-2 text-white">
                      {cache.hitRate > 0 ? (cache.hitRate * 100).toFixed(1) : '0'}%
                    </span>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Performance Recommendations */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
        <h3 className="text-sm font-semibold text-slate-300 mb-2">Performance Recommendations</h3>
        <div className="space-y-1 text-xs">
          {metrics.systemStats.memoryUsed / metrics.systemStats.memoryTotal > 0.8 && (
            <div className="flex items-center gap-2 text-amber-400">
              <Icon name="alertTriangle" size={12} className="w-3 h-3" />
              <span>High memory usage - consider clearing unused cache entries</span>
            </div>
          )}
          
          {metrics.cacheStats.some(cache => cache.size / (cache.maxSize ?? 1) > 0.9) && (
            <div className="flex items-center gap-2 text-amber-400">
              <Icon name="alertTriangle" size={12} className="w-3 h-3" />
              <span>Some caches are near capacity - increase max size or clear expired entries</span>
            </div>
          )}
          
          {metrics.networkStats.failedRequests / metrics.networkStats.totalRequests > 0.1 && (
            <div className="flex items-center gap-2 text-amber-400">
              <Icon name="alertTriangle" size={12} className="w-3 h-3" />
              <span>High network failure rate - check API endpoints and connectivity</span>
            </div>
          )}
          
          {metrics.systemStats.cpuUsage > 80 && (
            <div className="flex items-center gap-2 text-amber-400">
              <Icon name="alertTriangle" size={12} className="w-3 h-3" />
              <span>High CPU usage - consider optimizing data processing or reducing polling frequency</span>
            </div>
          )}
          
          {!(metrics.systemStats.memoryUsed / metrics.systemStats.memoryTotal > 0.8) &&
           !metrics.cacheStats.some(cache => cache.size / (cache.maxSize ?? 1) > 0.9) &&
           !(metrics.networkStats.failedRequests / metrics.networkStats.totalRequests > 0.1) &&
           metrics.systemStats.cpuUsage <= 80 && (
            <div className="flex items-center gap-2 text-green-400">
              <Icon name="checkCircle" size={12} className="w-3 h-3" />
              <span>System performance is optimal</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default PerformanceDashboard;
