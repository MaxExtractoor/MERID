import { useState, useEffect, useCallback } from 'react';
import { 
  TrendingUp, TrendingDown, Minus, Twitter, Newspaper, 
  MessageCircle, RefreshCw, AlertTriangle 
} from 'lucide-react';

interface SentimentEvent {
  id: string;
  timestamp: string;
  source: 'x' | 'telegram' | 'news' | 'rss';
  ticker: string;
  polarity: number;
  magnitude: number;
  relevance: number;
  headline: string;
  isSpike: boolean;
}

interface SentimentWindow {
  ticker: string;
  polarity: number;
  magnitude: number;
  eventCount: number;
  sourceBreakdown: { x: number; news: number; telegram: number };
}

interface SentimentTimelineProps {
  ticker?: string;
}

const SOURCE_ICONS = {
  x: Twitter,
  telegram: MessageCircle,
  news: Newspaper,
  rss: Newspaper,
};

const SOURCE_COLORS = {
  x: 'text-sky-400',
  telegram: 'text-blue-400',
  news: 'text-amber-400',
  rss: 'text-gray-400',
};

export default function SentimentTimeline({ ticker }: SentimentTimelineProps) {
  const [events, setEvents] = useState<SentimentEvent[]>([]);
  const [windows, setWindows] = useState<SentimentWindow[]>([]);
  const [selectedTicker, setSelectedTicker] = useState(ticker || '');
  const [loading, setLoading] = useState(true);

  const fetchSentiment = useCallback(async () => {
    try {
      const url = selectedTicker
        ? `/api/v1/signals/sentiment/${selectedTicker}`
        : '/api/v1/signals/sentiment';
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        if (data.events) setEvents(data.events);
        if (data.windows) setWindows(data.windows);
        return;
      }
    } catch {
      // fallback
    }

    const now = Date.now();
    setEvents([
      { id: '1', timestamp: new Date(now - 120000).toISOString(), source: 'x', ticker: 'BTC', polarity: 0.8, magnitude: 0.9, relevance: 0.95, headline: 'Bitcoin breaks $105K resistance with massive volume', isSpike: true },
      { id: '2', timestamp: new Date(now - 300000).toISOString(), source: 'news', ticker: 'BTC', polarity: 0.6, magnitude: 0.7, relevance: 0.8, headline: 'Institutional inflows hit record high for Bitcoin ETFs', isSpike: false },
      { id: '3', timestamp: new Date(now - 600000).toISOString(), source: 'x', ticker: 'ETH', polarity: -0.4, magnitude: 0.5, relevance: 0.7, headline: 'Ethereum gas fees spike amid NFT mint frenzy', isSpike: false },
      { id: '4', timestamp: new Date(now - 900000).toISOString(), source: 'telegram', ticker: 'SOL', polarity: 0.7, magnitude: 0.8, relevance: 0.85, headline: 'Solana DEX volume surpasses Ethereum for third day', isSpike: false },
      { id: '5', timestamp: new Date(now - 1200000).toISOString(), source: 'news', ticker: 'BTC', polarity: -0.6, magnitude: 0.8, relevance: 0.9, headline: 'SEC delays spot Bitcoin ETF decision again', isSpike: true },
    ]);
    setWindows([
      { ticker: 'BTC', polarity: 0.45, magnitude: 0.72, eventCount: 24, sourceBreakdown: { x: 15, news: 7, telegram: 2 } },
      { ticker: 'ETH', polarity: -0.12, magnitude: 0.45, eventCount: 12, sourceBreakdown: { x: 8, news: 3, telegram: 1 } },
      { ticker: 'SOL', polarity: 0.62, magnitude: 0.68, eventCount: 8, sourceBreakdown: { x: 5, news: 2, telegram: 1 } },
    ]);
    setLoading(false);
  }, [selectedTicker]);

  useEffect(() => {
    fetchSentiment();
    const interval = setInterval(fetchSentiment, 15000);
    return () => clearInterval(interval);
  }, [fetchSentiment]);

  const getPolarityColor = (p: number) => {
    if (p > 0.3) return 'text-green-400';
    if (p < -0.3) return 'text-red-400';
    return 'text-gray-400';
  };

  const getPolarityIcon = (p: number) => {
    if (p > 0.3) return TrendingUp;
    if (p < -0.3) return TrendingDown;
    return Minus;
  };

  const getPolarityBar = (p: number) => {
    const pct = ((p + 1) / 2) * 100;
    return pct;
  };

  const formatTime = (ts: string) => {
    const ms = Date.now() - new Date(ts).getTime();
    if (ms < 60000) return `${Math.floor(ms / 1000)}s ago`;
    if (ms < 3600000) return `${Math.floor(ms / 60000)}m ago`;
    return `${Math.floor(ms / 3600000)}h ago`;
  };

  const tickers = [...new Set(events.map(e => e.ticker))];

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading sentiment data...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-5 h-5 text-green-400" />
          <h3 className="text-lg font-bold text-white">Sentiment</h3>
        </div>
        <div className="flex items-center gap-2">
          {/* Ticker filter */}
          <div className="flex gap-1">
            <button
              onClick={() => setSelectedTicker('')}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                !selectedTicker ? 'bg-blue-600 text-white' : 'bg-slate-700 text-gray-400 hover:text-white'
              }`}
            >
              All
            </button>
            {tickers.map(t => (
              <button
                key={t}
                onClick={() => setSelectedTicker(t)}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  selectedTicker === t ? 'bg-blue-600 text-white' : 'bg-slate-700 text-gray-400 hover:text-white'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
          <button
            onClick={fetchSentiment}
            className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
            title="Refresh sentiment"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Sentiment Windows (per-ticker summary) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {windows
          .filter(w => !selectedTicker || w.ticker === selectedTicker)
          .map(w => {
            const PIcon = getPolarityIcon(w.polarity);
            return (
              <div key={w.ticker} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-semibold text-white">{w.ticker}</span>
                  <div className="flex items-center gap-1">
                    <PIcon className={`w-4 h-4 ${getPolarityColor(w.polarity)}`} />
                    <span className={`text-sm font-medium ${getPolarityColor(w.polarity)}`}>
                      {w.polarity > 0 ? '+' : ''}{w.polarity.toFixed(2)}
                    </span>
                  </div>
                </div>
                {/* Polarity bar */}
                <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden mb-2">
                  <div className="h-full flex">
                    <div className="bg-red-500/40 h-full" style={{ width: `${50}%` }} />
                    <div
                      className={`h-full ${w.polarity >= 0 ? 'bg-green-500' : 'bg-red-500'}`}
                      style={{
                        width: `${Math.abs(w.polarity) * 50}%`,
                        marginLeft: w.polarity >= 0 ? '0' : undefined,
                        marginRight: w.polarity < 0 ? '0' : undefined,
                      }}
                    />
                  </div>
                </div>
                <div className="flex items-center justify-between text-xs text-gray-400">
                  <span>{w.eventCount} events</span>
                  <span>
                    <span className="text-sky-400">{w.sourceBreakdown.x}x</span>
                    {' · '}
                    <span className="text-amber-400">{w.sourceBreakdown.news}n</span>
                    {' · '}
                    <span className="text-blue-400">{w.sourceBreakdown.telegram}t</span>
                  </span>
                </div>
              </div>
            );
          })}
      </div>

      {/* Event Timeline */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 overflow-hidden">
        <div className="px-4 py-2 border-b border-slate-700/50">
          <span className="text-sm font-medium text-gray-400">Recent Events</span>
        </div>
        <div className="divide-y divide-slate-700/30">
          {events
            .filter(e => !selectedTicker || e.ticker === selectedTicker)
            .map(event => {
              const SourceIcon = SOURCE_ICONS[event.source];
              const PIcon = getPolarityIcon(event.polarity);

              return (
                <div
                  key={event.id}
                  className={`px-4 py-3 flex items-start gap-3 ${
                    event.isSpike ? 'bg-amber-500/5 border-l-2 border-l-amber-500' : ''
                  }`}
                >
                  <SourceIcon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${SOURCE_COLORS[event.source]}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-xs font-medium text-white bg-slate-700 px-1.5 py-0.5 rounded">
                        {event.ticker}
                      </span>
                      {event.isSpike && (
                        <span className="flex items-center gap-1 text-xs text-amber-400">
                          <AlertTriangle className="w-3 h-3" />
                          Spike
                        </span>
                      )}
                      <span className="text-xs text-gray-500">{formatTime(event.timestamp)}</span>
                    </div>
                    <p className="text-sm text-gray-300 truncate">{event.headline}</p>
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <PIcon className={`w-3.5 h-3.5 ${getPolarityColor(event.polarity)}`} />
                    <span className={`text-xs font-mono ${getPolarityColor(event.polarity)}`}>
                      {event.polarity > 0 ? '+' : ''}{event.polarity.toFixed(1)}
                    </span>
                  </div>
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
}
