/**
 * PublishPipelinePanel — Kalshi → MERID consensus → News/X publishing status.
 *
 * Shows:
 *   - Pipeline running state + tracked tickers
 *   - Per-category emission counts
 *   - Recent published insights (ticker, category, action, Telegram ✓, tweet ID)
 *   - Twitter + Telegram channel status
 *   - Manual trigger input for operator testing
 */

import React, { useState } from 'react';
import {
  Radio, Twitter, MessageCircle,
  XCircle, RefreshCw, Zap,
  ChevronDown, ChevronUp,
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';

// ── Types ────────────────────────────────────────────────────────────────────

interface RecentPost {
  ticker: string;
  category: string;
  action: string;
  telegram: boolean;
  tweet_id: string | null;
  preview: string;
  ts: string;
}

interface PipelineData {
  pipeline: {
    running: boolean;
    consumers: number;
    tracked_tickers: number;
    total_emitted: number;
    by_category: Record<string, number>;
    by_action: Record<string, number>;
    errors: number;
    started_at: string | null;
  };
  news_agent: {
    total_processed: number;
    total_telegram: number;
    total_x: number;
    skipped_cooldown: number;
    errors: number;
    recent_posts: RecentPost[];
    category_cooldowns: Record<string, number>;
  };
  twitter: {
    enabled: boolean;
    recent_tweets: number;
    last_post_time: number;
  };
  telegram: {
    enabled: boolean;
    recent_messages: number;
  };
}

const ACTION_LABEL: Record<string, string> = {
  new_market: 'New',
  prob_cross: 'Cross',
  swing: 'Swing',
  resolution: 'Settled',
  update: 'Update',
};

const ACTION_COLOR: Record<string, string> = {
  new_market: 'text-blue-400 bg-blue-500/10',
  prob_cross: 'text-green-400 bg-green-500/10',
  swing: 'text-yellow-400 bg-yellow-500/10',
  resolution: 'text-purple-400 bg-purple-500/10',
  update: 'text-gray-400 bg-slate-700',
};

const CATEGORY_EMOJI: Record<string, string> = {
  Trending: '🔥', Politics: '🏛️', Sports: '🏆', Culture: '🎭',
  Crypto: '₿', Climate: '🌍', Economics: '📊', Mentions: '📰',
  Companies: '🏢', Financials: '💹', 'Tech & Science': '🔬',
};

// ── Component ────────────────────────────────────────────────────────────────

const PublishPipelinePanel: React.FC = () => {
  const { data, loading, refetch } = useApiData<PipelineData>(
    API_ENDPOINTS.KALSHI_PUBLISH_PIPELINE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );

  const [showCooldowns, setShowCooldowns] = useState(false);
  const [triggerTicker, setTriggerTicker] = useState('');
  const [triggerCategory, setTriggerCategory] = useState('Trending');
  const [triggering, setTriggering] = useState(false);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);

  const pipeline  = data?.pipeline;
  const newsAgent = data?.news_agent;
  const twitter   = data?.twitter;
  const telegram  = data?.telegram;

  const handleTrigger = async () => {
    if (!triggerTicker.trim()) return;
    setTriggering(true);
    setTriggerMsg(null);
    try {
      const token = localStorage.getItem('merid-access');
      const res = await fetch(
        `${API_BASE_URL}${API_ENDPOINTS.KALSHI_PUBLISH_PIPELINE_TRIGGER}?ticker=${encodeURIComponent(triggerTicker)}&category=${encodeURIComponent(triggerCategory)}`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        },
      );
      const json = await res.json().catch(() => ({}));
      if (res.ok) {
        setTriggerMsg(`✓ Triggered ${triggerTicker}`);
        refetch();
      } else {
        setTriggerMsg(`Error: ${(json as { detail?: string }).detail ?? res.statusText}`);
      }
    } catch {
      setTriggerMsg('Network error');
    } finally {
      setTriggering(false);
    }
  };

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
        <div className="animate-pulse space-y-3">
          <div className="h-4 bg-slate-700 rounded w-1/3" />
          <div className="h-24 bg-slate-700 rounded" />
        </div>
      </div>
    );
  }

  const isRunning = pipeline?.running ?? false;
  const topCategories = Object.entries(pipeline?.by_category ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800">
        <Radio className={`w-4 h-4 ${isRunning ? 'text-green-400 animate-pulse' : 'text-gray-500'}`} />
        <h3 className="text-sm font-medium text-gray-300">Publish Pipeline</h3>
        <span className="text-[10px] text-gray-500">Kalshi → Consensus → News/X</span>
        <div className="ml-auto flex items-center gap-2">
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${
            isRunning ? 'bg-green-500/20 text-green-400' : 'bg-slate-700 text-gray-500'
          }`}>
            {isRunning ? 'LIVE' : 'STOPPED'}
          </span>
          <button
            type="button"
            onClick={refetch}
            aria-label="Refresh pipeline status"
            className="p-1 rounded text-gray-500 hover:text-gray-300 hover:bg-slate-800"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Channel status row */}
      <div className="flex items-center gap-4 px-4 py-2 border-b border-slate-800/50 text-[10px]">
        <div className="flex items-center gap-1.5">
          <MessageCircle className={`w-3 h-3 ${telegram?.enabled ? 'text-blue-400' : 'text-gray-600'}`} />
          <span className={telegram?.enabled ? 'text-blue-400' : 'text-gray-600'}>
            Telegram {telegram?.enabled ? `(${telegram.recent_messages} sent)` : 'disabled'}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Twitter className={`w-3 h-3 ${twitter?.enabled ? 'text-sky-400' : 'text-gray-600'}`} />
          <span className={twitter?.enabled ? 'text-sky-400' : 'text-gray-600'}>
            X/Twitter {twitter?.enabled ? `(${twitter.recent_tweets} posted)` : 'disabled'}
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-gray-500">
          <span>{pipeline?.tracked_tickers ?? 0} tickers tracked</span>
          <span>{pipeline?.total_emitted ?? 0} emitted</span>
          <span>{newsAgent?.skipped_cooldown ?? 0} throttled</span>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 divide-x divide-slate-800 border-b border-slate-800">
        {[
          { label: 'Processed', value: newsAgent?.total_processed ?? 0, color: 'text-white' },
          { label: 'Telegram', value: newsAgent?.total_telegram ?? 0, color: 'text-blue-400' },
          { label: 'X Posts', value: newsAgent?.total_x ?? 0, color: 'text-sky-400' },
          { label: 'Errors', value: (pipeline?.errors ?? 0) + (newsAgent?.errors ?? 0), color: (pipeline?.errors ?? 0) + (newsAgent?.errors ?? 0) > 0 ? 'text-red-400' : 'text-gray-500' },
        ].map(s => (
          <div key={s.label} className="px-3 py-2 text-center">
            <div className={`text-lg font-bold font-mono ${s.color}`}>{s.value}</div>
            <div className="text-[10px] text-gray-500">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Category breakdown */}
      {topCategories.length > 0 && (
        <div className="px-4 py-2 border-b border-slate-800/50">
          <div className="text-[10px] text-gray-500 mb-1.5 uppercase tracking-wider">By Category</div>
          <div className="flex flex-wrap gap-1.5">
            {topCategories.map(([cat, count]) => (
              <span key={cat} className="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 text-[10px] text-gray-300">
                {CATEGORY_EMOJI[cat] ?? '📌'} {cat}
                <span className="font-mono text-orange-400 ml-0.5">{count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Recent posts */}
      <div className="max-h-[220px] overflow-y-auto divide-y divide-slate-800/50">
        {(newsAgent?.recent_posts ?? []).length === 0 ? (
          <div className="px-4 py-6 text-center text-xs text-gray-500">
            No posts yet — pipeline will publish when markets move
          </div>
        ) : (
          [...(newsAgent?.recent_posts ?? [])].reverse().map((post, i) => (
            <div key={i} className="px-4 py-2 flex items-start gap-2">
              <span className="text-[11px] shrink-0">{CATEGORY_EMOJI[post.category] ?? '📌'}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className="text-[10px] font-mono text-white truncate">{post.ticker}</span>
                  <span className={`text-[9px] px-1 py-0.5 rounded font-medium ${ACTION_COLOR[post.action] ?? 'text-gray-400 bg-slate-700'}`}>
                    {ACTION_LABEL[post.action] ?? post.action}
                  </span>
                  {post.telegram && (
                    <MessageCircle className="w-2.5 h-2.5 text-blue-400 shrink-0" />
                  )}
                  {post.tweet_id ? (
                    <a
                      href={`https://x.com/i/web/status/${post.tweet_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`View tweet ${post.tweet_id} on X`}
                      className="flex items-center gap-0.5"
                    >
                      <Twitter className="w-2.5 h-2.5 text-sky-400 shrink-0" />
                    </a>
                  ) : (
                    <XCircle className="w-2.5 h-2.5 text-gray-600 shrink-0" />
                  )}
                </div>
                <p className="text-[10px] text-gray-500 truncate">{post.preview}</p>
              </div>
              <span className="text-[9px] text-gray-600 shrink-0">
                {new Date(post.ts).toLocaleTimeString()}
              </span>
            </div>
          ))
        )}
      </div>

      {/* Category cooldowns (collapsible) */}
      {Object.keys(newsAgent?.category_cooldowns ?? {}).length > 0 && (
        <div className="border-t border-slate-800/50">
          <button
            type="button"
            onClick={() => setShowCooldowns(v => !v)}
            className="w-full flex items-center gap-2 px-4 py-2 text-[10px] text-gray-500 hover:text-gray-300"
          >
            {showCooldowns ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            Category cooldowns
          </button>
          {showCooldowns && (
            <div className="px-4 pb-2 grid grid-cols-2 gap-1">
              {Object.entries(newsAgent?.category_cooldowns ?? {}).map(([cat, secs]) => (
                <div key={cat} className="flex items-center justify-between text-[10px]">
                  <span className="text-gray-400">{CATEGORY_EMOJI[cat]} {cat}</span>
                  <span className={`font-mono ${secs > 0 ? 'text-yellow-400' : 'text-green-400'}`}>
                    {secs > 0 ? `${secs}s` : 'ready'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Manual trigger */}
      <div className="border-t border-slate-800 px-4 py-3 space-y-2">
        <div className="text-[10px] text-gray-500 uppercase tracking-wider">Manual Trigger</div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={triggerTicker}
            onChange={e => setTriggerTicker(e.target.value.toUpperCase())}
            placeholder="TICKER"
            className="flex-1 px-2 py-1 rounded bg-slate-800 border border-slate-700 text-xs text-white font-mono placeholder-gray-600 focus:outline-none focus:border-orange-500"
          />
          <select
            value={triggerCategory}
            onChange={e => setTriggerCategory(e.target.value)}
            aria-label="Select category for manual trigger"
            className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-xs text-gray-300 focus:outline-none focus:border-orange-500"
          >
            {['Trending','Politics','Sports','Culture','Crypto','Climate','Economics','Mentions','Companies','Financials','Tech & Science'].map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleTrigger}
            disabled={triggering || !triggerTicker.trim()}
            className="flex items-center gap-1 px-3 py-1 rounded bg-orange-500/20 border border-orange-500/30 text-orange-400 text-xs font-medium hover:bg-orange-500/30 disabled:opacity-50"
          >
            <Zap className="w-3 h-3" />
            {triggering ? '…' : 'Fire'}
          </button>
        </div>
        {triggerMsg && (
          <p className={`text-[10px] ${triggerMsg.startsWith('✓') ? 'text-green-400' : 'text-red-400'}`}>
            {triggerMsg}
          </p>
        )}
      </div>
    </div>
  );
};

export default PublishPipelinePanel;
