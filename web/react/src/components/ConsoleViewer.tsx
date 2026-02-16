import { useState, useEffect, useRef, useCallback } from 'react';
import { Play, PauseCircle, Trash, Copy, RefreshCw, Terminal } from 'lucide-react';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface ConsoleMessage {
  id: string;
  timestamp: Date;
  type: 'api' | 'ws' | 'log' | 'error';
  source: string;
  data: unknown;
}

export default function ConsoleViewer() {
  const [messages, setMessages] = useState<ConsoleMessage[]>([]);
  const [isPaused, setIsPaused] = useState(false);
  type ConsoleMode = 'prime' | 'orders' | 'risk' | 'logs';
  const [selectedMode, setSelectedMode] = useState<ConsoleMode>('prime');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Auto-scroll to bottom only when not paused and user is near bottom
  useEffect(() => {
    if (!isPaused && messagesEndRef.current) {
      const container = messagesEndRef.current.parentElement;
      if (container) {
        const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
        if (isNearBottom) {
          messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
      }
    }
  }, [messages, isPaused]);

  // Add message to console
  const addMessage = useCallback((type: ConsoleMessage['type'], source: string, data: unknown) => {
    if (isPaused) return;
    
    const newMessage: ConsoleMessage = {
      id: Math.random().toString(36).substr(2, 9),
      timestamp: new Date(),
      type,
      source,
      data
    };
    
    setMessages(prev => [...prev.slice(-99), newMessage]); // Keep last 100
  }, [isPaused]);

  // Fetch Prime API data
  const fetchPrimeData = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch(API_ENDPOINTS.PRIME_STATUS);
      if (response.ok) {
        const data = await response.json();
        addMessage('api', 'Prime API', data);
      }
    } catch {
      addMessage('error', 'Prime API', { error: 'Failed to fetch' });
    }
    setIsLoading(false);
  }, [addMessage]);

  // WebSocket connection for real-time data
  useEffect(() => {
    if (selectedMode === 'orders' || selectedMode === 'risk') {
      const wsUrl = `ws://${window.location.host}/ws/${selectedMode}`;
      wsRef.current = new WebSocket(wsUrl);
      
      wsRef.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          addMessage('ws', selectedMode.toUpperCase(), data);
        } catch {
          addMessage('ws', selectedMode.toUpperCase(), { raw: event.data });
        }
      };

      wsRef.current.onerror = () => {
        addMessage('error', 'WebSocket', { error: 'Connection failed' });
      };

      return () => {
        wsRef.current?.close();
      };
    }
  }, [selectedMode, addMessage]);

  // Polling for Prime and Logs modes - reduced frequency
  useEffect(() => {
    if (selectedMode === 'prime') {
      fetchPrimeData();
      const interval = setInterval(fetchPrimeData, DEFAULTS.POLLING_INTERVALS.BACKGROUND); // Poll every 30s instead of 5s
      return () => clearInterval(interval);
    }
  }, [selectedMode, fetchPrimeData]);

  const clearConsole = () => setMessages([]);
  
  const copyToClipboard = () => {
    const text = messages.map(m => `[${m.timestamp.toISOString()}] ${m.source}: ${JSON.stringify(m.data, null, 2)}`).join('\n');
    navigator.clipboard.writeText(text);
  };

  const formatTimestamp = (date: Date) => {
    const time = date.toLocaleTimeString('en-US', { 
      hour12: false, 
      hour: '2-digit', 
      minute: '2-digit', 
      second: '2-digit'
    });
    const ms = date.getMilliseconds().toString().padStart(3, '0');
    return `${time}.${ms}`;
  };

  const getTypeColor = (type: ConsoleMessage['type']) => {
    switch (type) {
      case 'api': return 'text-blue-400';
      case 'ws': return 'text-purple-400';
      case 'log': return 'text-slate-400';
      case 'error': return 'text-rose-400';
      default: return 'text-slate-400';
    }
  };

  const renderJSON = (data: unknown, level = 0): JSX.Element => {
    if (data === null) return <span className="text-slate-500">null</span>;
    if (typeof data === 'boolean') return <span className="text-amber-400">{data.toString()}</span>;
    if (typeof data === 'number') return <span className="text-cyan-400">{data}</span>;
    if (typeof data === 'string') return <span className="text-emerald-400">"{data}"</span>;
    
    if (Array.isArray(data)) {
      return (
        <span>
          <span className="text-slate-300">[</span>
          <div className="ml-4">
            {data.map((item, i) => (
              <div key={i}>{renderJSON(item, level + 1)}{i < data.length - 1 && <span className="text-slate-300">,</span>}</div>
            ))}
          </div>
          <span className="text-slate-300">]</span>
        </span>
      );
    }
    
    if (typeof data === 'object') {
      return (
        <span>
          <span className="text-slate-300">{'{'}</span>
          <div className="ml-4">
            {Object.entries(data).map(([key, value], i, arr) => (
              <div key={key}>
                <span className="text-purple-400">"{key}"</span>
                <span className="text-slate-300">: </span>
                {renderJSON(value, level + 1)}
                {i < arr.length - 1 && <span className="text-slate-300">,</span>}
              </div>
            ))}
          </div>
          <span className="text-slate-300">{'}'}</span>
        </span>
      );
    }
    
    return <span>{String(data)}</span>;
  };

  return (
    <div className="bg-slate-950 rounded-lg border border-slate-800 flex flex-col h-96">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-800 bg-slate-900/50">
        <div className="flex items-center gap-3">
          <Terminal className="w-4 h-4 text-slate-400" />
          <span className="text-sm font-medium text-slate-300">Console</span>
          
          <select aria-label="Console"
            id="console-mode"
            name="consoleMode"
            title="Select console mode"
            value={selectedMode}
            onChange={(e) => {
              setSelectedMode(e.target.value as ConsoleMode);
              clearConsole();
            }}
            className="ml-4 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-slate-300 focus:outline-none focus:border-blue-500"
          >
            <option value="prime">Prime API</option>
            <option value="orders">Order Events</option>
            <option value="risk">Risk Events</option>
            <option value="logs">System Logs</option>
          </select>
          
          <button type="button"
            title="Refresh console data"
            onClick={() => {
              if (selectedMode === 'prime') fetchPrimeData();
            }}
            disabled={isLoading || selectedMode !== 'prime'}
            className="ml-2 p-1 rounded hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 text-slate-400 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
        
        <div className="flex items-center gap-2">
          <button type="button"
            onClick={() => setIsPaused(!isPaused)}
            className={`p-1.5 rounded transition-colors ${isPaused ? 'bg-amber-500/20 text-amber-400' : 'hover:bg-slate-800 text-slate-400'}`}
            title={isPaused ? 'Resume' : 'Pause'}
          >
            {isPaused ? <Play className="w-4 h-4" /> : <PauseCircle className="w-4 h-4" />}
          </button>
          
          <button type="button"
            onClick={copyToClipboard}
            className="p-1.5 rounded hover:bg-slate-800 text-slate-400 transition-colors"
            title="Copy to clipboard"
           aria-label="Copy">
            <Copy className="w-4 h-4" />
          </button>
          
          <button type="button"
            onClick={clearConsole}
            className="p-1.5 rounded hover:bg-slate-800 text-slate-400 transition-colors"
            title="Clear console"
           aria-label="Delete">
            <Trash className="w-4 h-4" />
          </button>
        </div>
      </div>
      
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 font-mono text-xs">
        {messages.length === 0 ? (
          <div className="text-slate-600 text-center py-8">
            Waiting for {selectedMode} data...
          </div>
        ) : (
          messages.map((msg) => (
            <div key={msg.id} className="mb-2">
              <div className="flex items-start gap-2">
                <span className="text-slate-600 shrink-0">[{formatTimestamp(msg.timestamp)}]</span>
                <span className={getTypeColor(msg.type)}>{msg.source}</span>
              </div>
              <div className="ml-24 mt-1 overflow-x-auto">
                {renderJSON(msg.data)}
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>
      
      {/* Status bar */}
      <div className="px-4 py-1.5 border-t border-slate-800 bg-slate-900/30 text-xs text-slate-500 flex justify-between">
        <span>{messages.length} messages</span>
        <span>{isPaused ? 'Paused' : selectedMode === 'orders' || selectedMode === 'risk' ? 'WebSocket Connected' : 'Polling every 5s'}</span>
      </div>
    </div>
  );
}
