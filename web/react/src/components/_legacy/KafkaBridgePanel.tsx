/**
 * KafkaBridgePanel - Real-time Kafka event stream viewer.
 * 
 * Connects to the WebSocket Kafka bridge to display live trading events.
 */

import { useState, useEffect, useRef } from 'react';
import { useKafkaStream, StreamEvent } from '../hooks/useKafkaStream';
import { Radio, Pause, Play, Trash2, Filter, Download } from 'lucide-react';

interface KafkaBridgePanelProps {
  className?: string;
  defaultTopics?: string[];
  maxEvents?: number;
}

export default function KafkaBridgePanel({ 
  className = '', 
  defaultTopics = ['trades.executed', 'agent.opinions', 'prices.ticks'],
  maxEvents = 100 
}: KafkaBridgePanelProps) {
  const [paused, setPaused] = useState(false);
  const [filterType, setFilterType] = useState<string>('all');
  const [selectedTopics, setSelectedTopics] = useState<string[]>(defaultTopics);
  const eventsRef = useRef<StreamEvent[]>([]);
  
  const { 
    events, 
    connected,
    clear,
  } = useKafkaStream('/ws/kafka', {
    maxEvents,
    autoConnect: true,
    deduplicate: true,
    maxReconnectAttempts: 3,  // Limit reconnect attempts to reduce console noise
    reconnectDelay: 10000,     // 10 second delay between reconnects
  });

  // Store events when not paused
  useEffect(() => {
    if (!paused) {
      eventsRef.current = events;
    }
  }, [events, paused]);

  const displayEvents = paused ? eventsRef.current : events;

  const filteredEvents = displayEvents.filter(event => {
    if (filterType === 'all') return true;
    return event.event_type === filterType;
  });

  const getEventColor = (eventType: string) => {
    if (eventType.includes('trade')) return 'text-emerald-400 bg-emerald-500/10';
    if (eventType.includes('agent')) return 'text-blue-400 bg-blue-500/10';
    if (eventType.includes('price')) return 'text-amber-400 bg-amber-500/10';
    if (eventType.includes('risk')) return 'text-red-400 bg-red-500/10';
    return 'text-slate-400 bg-slate-500/10';
  };

  const handleTopicToggle = (topic: string) => {
    if (selectedTopics.includes(topic)) {
      setSelectedTopics(prev => prev.filter(t => t !== topic));
    } else {
      setSelectedTopics(prev => [...prev, topic]);
    }
  };

  const exportEvents = () => {
    const blob = new Blob([JSON.stringify(filteredEvents, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `kafka-events-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const eventTypes = [...new Set(displayEvents.map(e => e.event_type))];

  return (
    <div className={`bg-slate-900 rounded-xl border border-slate-800 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <Radio className={`w-5 h-5 ${connected ? 'text-emerald-400 animate-pulse' : 'text-red-400'}`} />
          <h2 className="text-lg font-semibold text-white">Kafka Event Stream</h2>
          <span className={`px-2 py-1 rounded text-xs font-medium ${
            connected ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
          }`}>
            {connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
        
        <div className="flex items-center gap-2">
          <button type="button"
            onClick={() => setPaused(!paused)}
            className={`p-2 rounded-lg transition-colors ${
              paused ? 'bg-amber-500/20 text-amber-400' : 'hover:bg-slate-800 text-slate-400'
            }`}
            title={paused ? 'Resume' : 'Pause'}
          >
            {paused ? <Play className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
          </button>
          
          <button type="button"
            onClick={clear}
            className="p-2 hover:bg-slate-800 rounded-lg text-slate-400 transition-colors"
            title="Clear events"
           aria-label="Delete">
            <Trash2 className="w-4 h-4" />
          </button>
          
          <button type="button"
            onClick={exportEvents}
            className="p-2 hover:bg-slate-800 rounded-lg text-slate-400 transition-colors"
            title="Export events"
           aria-label="Download">
            <Download className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4 p-4 border-b border-slate-800 bg-slate-800/30">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-slate-400" />
          <select aria-label="Filter Type"
            id="kafka-event-filter"
            name="eventFilter"
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-sm focus:outline-none focus:border-blue-500"
            title="Filter by event type"
          >
            <option value="all">All Events</option>
            {eventTypes.map(type => (
              <option key={type} value={type}>{type}</option>
            ))}
          </select>
        </div>
        
        <div className="flex flex-wrap gap-2">
          {['trades.executed', 'agent.opinions', 'prices.ticks', 'risk.alerts'].map(topic => (
            <button type="button"
              key={topic}
              onClick={() => handleTopicToggle(topic)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                selectedTopics.includes(topic)
                  ? 'bg-blue-500/20 text-blue-400 border border-blue-500/50'
                  : 'bg-slate-800 text-slate-400 border border-slate-700 hover:border-slate-600'
              }`}
            >
              {topic}
            </button>
          ))}
        </div>
        
        <span className="text-sm text-slate-500 ml-auto">
          {filteredEvents.length} events
        </span>
      </div>

      {/* Events List */}
      <div className="max-h-96 overflow-y-auto">
        {filteredEvents.length === 0 ? (
          <div className="p-8 text-center text-slate-500">
            {connected ? 'Waiting for events...' : 'Connect to see events'}
          </div>
        ) : (
          <div className="divide-y divide-slate-800">
            {filteredEvents.map((event) => (
              <div key={event.event_id} className="p-3 hover:bg-slate-800/50 transition-colors">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${getEventColor(event.event_type)}`}>
                        {event.event_type}
                      </span>
                      <span className="text-xs text-slate-500 font-mono">
                        {event.event_id.slice(0, 12)}...
                      </span>
                    </div>
                    <pre className="text-xs text-slate-300 overflow-hidden text-ellipsis whitespace-nowrap">
                      {JSON.stringify(event.payload).slice(0, 100)}
                      {JSON.stringify(event.payload).length > 100 && '...'}
                    </pre>
                  </div>
                  <div className="text-xs text-slate-500 whitespace-nowrap">
                    {new Date(event.timestamp * 1000).toLocaleTimeString()}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
