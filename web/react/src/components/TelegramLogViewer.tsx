import { useState } from 'react';
import {
  MessageSquare, RefreshCw, Send
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface TelegramMessage {
  id: string;
  timestamp: string;
  direction: 'outbound' | 'inbound';
  type: 'alert' | 'status' | 'trade' | 'system' | 'command';
  text: string;
  chatId: string;
  delivered: boolean;
}

const TYPE_COLORS: Record<string, string> = {
  alert: 'bg-red-500/20 text-red-400',
  status: 'bg-blue-500/20 text-blue-400',
  trade: 'bg-green-500/20 text-green-400',
  system: 'bg-gray-500/20 text-gray-400',
  command: 'bg-purple-500/20 text-purple-400',
};

export default function TelegramLogViewer() {
  const [typeFilter, setTypeFilter] = useState<string>('all');

  const { data: rawData, loading, error: fetchError, refetch } = useApiData<{ messages: TelegramMessage[] }>(
    API_ENDPOINTS.NOTIFICATIONS_TELEGRAM_LOG,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.MEDIUM },
  );

  if (fetchError && !rawData) {
    return <ErrorBar label="Telegram log" error={fetchError} onRetry={refetch} />;
  }
  const messages = rawData?.messages ?? [];

  const filtered = typeFilter === 'all' ? messages : messages.filter(m => m.type === typeFilter);

  const formatTime = (ts: string) => {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading Telegram log...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-5 h-5 text-sky-400" />
          <h3 className="text-lg font-bold text-white">Telegram Log</h3>
          <span className="text-sm text-gray-400">{messages.length} messages</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {['all', 'alert', 'trade', 'status', 'system', 'command'].map(f => (
              <button type="button"
                key={f}
                onClick={() => setTypeFilter(f)}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  typeFilter === f ? 'bg-sky-600 text-white' : 'bg-slate-700 text-gray-400 hover:text-white'
                }`}
              >
                {f === 'all' ? 'All' : f}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => refetch()} className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white" title="Refresh" aria-label="Refresh">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 max-h-[400px] overflow-y-auto">
        <div className="space-y-1 p-2">
          {filtered.map(msg => (
            <div
              key={msg.id}
              className={`flex items-start gap-2 p-2 rounded-lg ${
                msg.direction === 'inbound' ? 'bg-purple-500/5 ml-8' : 'bg-slate-900/50 mr-4'
              }`}
            >
              <div className="flex-shrink-0 mt-0.5">
                {msg.direction === 'inbound'
                  ? <MessageSquare className="w-3.5 h-3.5 text-purple-400" />
                  : <Send className="w-3.5 h-3.5 text-sky-400" />
                }
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${TYPE_COLORS[msg.type]}`}>
                    {msg.type}
                  </span>
                  <span className="text-[10px] text-gray-500 font-mono">{formatTime(msg.timestamp)}</span>
                  {!msg.delivered && (
                    <span className="text-[10px] text-red-400">⚠ not delivered</span>
                  )}
                </div>
                <p className="text-xs text-gray-300 whitespace-pre-wrap break-words">{msg.text}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
