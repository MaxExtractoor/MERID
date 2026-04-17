import React, { useState, useCallback, useMemo } from 'react';
import { Icon } from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { formatDateTime } from '../utils/formatters';

interface AuditEntry {
  seq: number;
  timestamp: string;
  event_type: string;
  source: string;
  details: Record<string, any>;
  hash: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
}

interface AuditAnalytics {
  total_events: number;
  event_frequency: Record<string, number>;
  source_distribution: Record<string, number>;
  severity_distribution: Record<string, number>;
  hourly_volume: Array<{
    hour: string;
    count: number;
  }>;
  recent_patterns: Array<{
    pattern: string;
    count: number;
    trend: 'increasing' | 'decreasing' | 'stable';
  }>;
}

const EnhancedAuditTrail: React.FC = () => {
  const [selectedSource, setSelectedSource] = useState<string>('all');
  const [selectedSeverity, setSelectedSeverity] = useState<string>('all');
  const [selectedEventType, setSelectedEventType] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [timeRange, setTimeRange] = useState<'1h' | '6h' | '24h' | '7d'>('24h');
  const [expandedEntries, setExpandedEntries] = useState<Set<number>>(new Set());
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [showAnalytics, setShowAnalytics] = useState(false);

  // Fetch audit data
  const { data: auditData, loading: auditLoading, error: auditError, refetch: refetchAudit } = useApiData<{
    entries: AuditEntry[];
    analytics: AuditAnalytics;
  }>(
    API_ENDPOINTS.AUDIT_TRAIL_ENTRIES,
    { 
      pollingInterval: autoRefresh ? DEFAULTS.POLLING_INTERVALS.MEDIUM : 0,
      query: { 
        time_range: timeRange,
        source: selectedSource !== 'all' ? selectedSource : undefined,
        severity: selectedSeverity !== 'all' ? selectedSeverity : undefined
      }
    }
  );

  // Filter entries based on search and filters
  const filteredEntries = useMemo(() => {
    if (!auditData?.entries) return [];
    
    return auditData.entries.filter(entry => {
      // Search filter
      if (searchTerm && !entry.event_type.toLowerCase().includes(searchTerm.toLowerCase()) &&
          !entry.source.toLowerCase().includes(searchTerm.toLowerCase())) {
        return false;
      }
      
      // Event type filter
      if (selectedEventType !== 'all' && entry.event_type !== selectedEventType) {
        return false;
      }
      
      return true;
    });
  }, [auditData?.entries, searchTerm, selectedEventType]);

  // Get unique sources, event types, and severities for filters
  const filterOptions = useMemo(() => {
    if (!auditData?.entries) return { sources: [], eventTypes: [], severities: [] };
    
    const sources = [...new Set(auditData.entries.map(e => e.source))];
    const eventTypes = [...new Set(auditData.entries.map(e => e.event_type))];
    const severities = [...new Set(auditData.entries.map(e => e.severity))];
    
    return { sources, eventTypes, severities };
  }, [auditData?.entries]);

  const toggleEntryExpansion = useCallback((seq: number) => {
    setExpandedEntries(prev => {
      const newSet = new Set(prev);
      if (newSet.has(seq)) {
        newSet.delete(seq);
      } else {
        newSet.add(seq);
      }
      return newSet;
    });
  }, []);

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical': return 'text-red-400 bg-red-500/20 border-red-500';
      case 'high': return 'text-orange-400 bg-orange-500/20 border-orange-500';
      case 'medium': return 'text-amber-400 bg-amber-500/20 border-amber-500';
      case 'low': return 'text-blue-400 bg-blue-500/20 border-blue-500';
      default: return 'text-slate-400 bg-slate-500/20 border-slate-500';
    }
  };

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'critical': return 'alertOctagon';
      case 'high': return 'alertTriangle';
      case 'medium': return 'alert';
      case 'low': return 'info';
      default: return 'helpCircle';
    }
  };

  const exportAuditData = useCallback(() => {
    if (!filteredEntries.length) return;
    
    const csv = [
      ['Seq', 'Timestamp', 'Event Type', 'Source', 'Severity', 'Hash'],
      ...filteredEntries.map(entry => [
        entry.seq,
        entry.timestamp,
        entry.event_type,
        entry.source,
        entry.severity,
        entry.hash
      ])
    ].map(row => row.join(',')).join('\n');
    
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `audit-trail-${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [filteredEntries]);

  if (auditLoading && !auditData) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-6">
        <div className="flex items-center gap-2 text-slate-500">
          <Icon name="loading" size={20} className="w-5 h-5 animate-spin" />
          <span>Loading audit trail...</span>
        </div>
      </div>
    );
  }

  if (auditError) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-red-800/50 p-6">
        <div className="flex items-center gap-2 text-red-400">
          <Icon name="alert" size={20} className="w-5 h-5" />
          <span>Failed to load audit data</span>
        </div>
      </div>
    );
  }

  const analytics = auditData?.analytics;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon name="fileText" size={20} className="w-5 h-5 text-blue-400" />
          <h2 className="text-lg font-bold text-white">Enhanced Audit Trail</h2>
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
          
          {/* Analytics Toggle */}
          <button
            onClick={() => setShowAnalytics(!showAnalytics)}
            className={`flex items-center gap-1.5 px-2 py-1 text-xs rounded transition-colors ${
              showAnalytics 
                ? 'bg-purple-600 text-white' 
                : 'bg-slate-700 text-slate-400'
            }`}
            title="Toggle analytics view"
          >
            <Icon name="barChart" size={12} className="w-3 h-3" />
            Analytics
          </button>
          
          {/* Export Button */}
          <button
            onClick={exportAuditData}
            disabled={!filteredEntries.length}
            className="flex items-center gap-1.5 px-2 py-1 text-xs bg-green-600 hover:bg-green-700 disabled:bg-slate-600 disabled:opacity-50 text-white rounded transition-colors"
            title="Export to CSV"
          >
            <Icon name="download" size={12} className="w-3 h-3" />
            Export
          </button>
          
          <button
            onClick={() => refetchAudit()}
            className="flex items-center gap-1.5 px-2 py-1 text-xs bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
            title="Refresh data"
          >
            <Icon name="refresh" size={12} className="w-3 h-3" />
            Refresh
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        {/* Search */}
        <div className="relative">
          <Icon name="search" size={14} className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search events..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-7 pr-2 py-1 text-xs bg-slate-700 border border-slate-600 rounded text-white placeholder-slate-500 w-32 focus:outline-none focus:border-blue-500"
          />
        </div>
        
        {/* Time Range */}
        <select
          value={timeRange}
          onChange={(e) => setTimeRange(e.target.value as '1h' | '6h' | '24h' | '7d')}
          className="text-xs bg-slate-700 border border-slate-600 rounded px-2 py-1 text-white"
          title="Select time range"
        >
          <option value="1h">Last hour</option>
          <option value="6h">Last 6 hours</option>
          <option value="24h">Last 24h</option>
          <option value="7d">Last 7 days</option>
        </select>
        
        {/* Source Filter */}
        <select
          value={selectedSource}
          onChange={(e) => setSelectedSource(e.target.value)}
          className="text-xs bg-slate-700 border border-slate-600 rounded px-2 py-1 text-white"
          title="Filter by source"
        >
          <option value="all">All Sources</option>
          {filterOptions.sources.map(source => (
            <option key={source} value={source}>{source}</option>
          ))}
        </select>
        
        {/* Severity Filter */}
        <select
          value={selectedSeverity}
          onChange={(e) => setSelectedSeverity(e.target.value)}
          className="text-xs bg-slate-700 border border-slate-600 rounded px-2 py-1 text-white"
          title="Filter by severity"
        >
          <option value="all">All Severities</option>
          {filterOptions.severities.map(severity => (
            <option key={severity} value={severity}>{severity}</option>
          ))}
        </select>
        
        {/* Event Type Filter */}
        <select
          value={selectedEventType}
          onChange={(e) => setSelectedEventType(e.target.value)}
          className="text-xs bg-slate-700 border border-slate-600 rounded px-2 py-1 text-white"
          title="Filter by event type"
        >
          <option value="all">All Event Types</option>
          {filterOptions.eventTypes.map(eventType => (
            <option key={eventType} value={eventType}>{eventType}</option>
          ))}
        </select>
      </div>

      {/* Analytics View */}
      {showAnalytics && analytics && (
        <div className="space-y-4">
          {/* Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
              <div className="text-[10px] text-slate-500 uppercase tracking-wide">Total Events</div>
              <div className="text-lg font-bold text-white">{analytics.total_events}</div>
            </div>
            
            <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
              <div className="text-[10px] text-slate-500 uppercase tracking-wide">Event Types</div>
              <div className="text-lg font-bold text-blue-400">{Object.keys(analytics.event_frequency).length}</div>
            </div>
            
            <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
              <div className="text-[10px] text-slate-500 uppercase tracking-wide">Sources</div>
              <div className="text-lg font-bold text-purple-400">{Object.keys(analytics.source_distribution).length}</div>
            </div>
            
            <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
              <div className="text-[10px] text-slate-500 uppercase tracking-wide">Critical Events</div>
              <div className="text-lg font-bold text-red-400">{analytics.severity_distribution.critical || 0}</div>
            </div>
          </div>

          {/* Event Frequency */}
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
            <h3 className="text-sm font-semibold text-slate-300 mb-2">Event Frequency</h3>
            <div className="space-y-1">
              {Object.entries(analytics.event_frequency ?? {}).map(([eventType, count]) => (
                <div key={eventType} className="flex items-center justify-between text-xs">
                  <span className="text-slate-300">{eventType}</span>
                  <span className="text-slate-400 font-mono">{count}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Recent Patterns */}
          {(analytics.recent_patterns ?? []).length > 0 && (
            <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
              <h3 className="text-sm font-semibold text-slate-300 mb-2">Recent Patterns</h3>
              <div className="space-y-1">
                {(analytics.recent_patterns ?? []).map((pattern, index) => (
                  <div key={index} className="flex items-center justify-between text-xs">
                    <span className="text-slate-300">{pattern.pattern}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-slate-400 font-mono">{pattern.count}x</span>
                      <Icon 
                        name={pattern.trend === 'increasing' ? 'trendingUp' : pattern.trend === 'decreasing' ? 'trendingDown' : 'minus'} 
                        size={12} 
                        className={`w-3 h-3 ${
                          pattern.trend === 'increasing' ? 'text-red-400' : 
                          pattern.trend === 'decreasing' ? 'text-green-400' : 'text-slate-400'
                        }`} 
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Audit Entries */}
      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-slate-300">
          Audit Entries ({filteredEntries.length})
        </h3>
        
        {filteredEntries.length === 0 ? (
          <div className="text-center py-8 text-slate-500 text-sm">
            No audit entries match the selected filters
          </div>
        ) : (
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {filteredEntries.map((entry) => (
              <div
                key={entry.seq}
                className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3"
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Icon 
                      name={getSeverityIcon(entry.severity)} 
                      size={16} 
                      className={`w-4 h-4 ${getSeverityColor(entry.severity).split(' ')[0]}`} 
                    />
                    <span className="text-sm text-white">{entry.event_type}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded border ${getSeverityColor(entry.severity)}`}>
                      {entry.severity}
                    </span>
                  </div>
                  
                  <div className="flex items-center gap-3 text-xs">
                    <span className="text-slate-400">{entry.source}</span>
                    <span className="text-slate-600 font-mono">#{entry.seq}</span>
                    <button
                      onClick={() => toggleEntryExpansion(entry.seq)}
                      className="flex items-center gap-1 text-slate-400 hover:text-white transition-colors"
                      title="Toggle details"
                    >
                      <Icon 
                        name="chevronDown" 
                        size={12} 
                        className={`w-3 h-3 transition-transform ${
                          expandedEntries.has(entry.seq) ? 'rotate-180' : ''
                        }`} 
                      />
                    </button>
                  </div>
                </div>
                
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>{formatDateTime(entry.timestamp)}</span>
                  <span className="font-mono">{entry.hash.slice(0, 12)}</span>
                </div>
                
                {/* Expanded Details */}
                {expandedEntries.has(entry.seq) && (
                  <div className="mt-3 pt-3 border-t border-slate-700/50">
                    <div className="bg-slate-900/50 rounded p-2">
                      <div className="text-xs font-medium text-gray-400 mb-1">Event Details</div>
                      <div className="space-y-1">
                        {Object.entries(entry.details ?? {}).map(([key, value]) => (
                          <div key={key} className="flex items-start gap-2 text-xs">
                            <span className="text-gray-500 min-w-20">{key}:</span>
                            <span className="text-gray-300 font-mono break-all">
                              {typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default EnhancedAuditTrail;
