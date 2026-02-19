import { useState, useCallback, useRef, useEffect } from 'react';
import { Send, Bot, User, Loader2, Sparkles, ChevronDown } from 'lucide-react';
import { API_ENDPOINTS } from '../config/constants';

interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  traceId?: string;
  latencyMs?: number;
  sources?: string[];
}

type ContextDomain = 'operator' | 'dev' | 'cognitive' | 'sports';

const CONTEXT_LABELS: Record<ContextDomain, { label: string; color: string }> = {
  operator: { label: 'Operator', color: 'text-blue-400' },
  dev: { label: 'Dev Swarm', color: 'text-purple-400' },
  cognitive: { label: 'Cognitive', color: 'text-cyan-400' },
  sports: { label: 'Sports', color: 'text-amber-400' },
};

const SUGGESTED_QUERIES: Record<ContextDomain, string[]> = {
  operator: [
    'What is the current portfolio status?',
    'Show me risk metrics summary',
    'What pipeline modes are active?',
    'Give me a system health overview',
  ],
  dev: [
    'How many dev swarm tasks are completed?',
    'Is the dev swarm paused?',
    'Show agent performance summary',
  ],
  cognitive: [
    'What is the current regime detection status?',
    'Are there any stuck models?',
  ],
  sports: [
    'What are the active betting events?',
    'Show sports SLO metrics',
  ],
};

interface AssistantPanelProps {
  defaultContext?: ContextDomain;
}

export default function AssistantPanel({ defaultContext = 'operator' }: AssistantPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [context, setContext] = useState<ContextDomain>(defaultContext);
  const [showContextMenu, setShowContextMenu] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendQuery = useCallback(async (query: string) => {
    if (!query.trim() || loading) return;

    const userMsg: Message = {
      role: 'user',
      content: query.trim(),
      timestamp: Date.now() / 1000,
    };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const res = await fetch(API_ENDPOINTS.ASSISTANT_QUERY, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query.trim(),
          context,
          include_system_snapshot: true,
        }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const assistantMsg: Message = {
        role: 'assistant',
        content: data.answer,
        timestamp: Date.now() / 1000,
        traceId: data.trace_id,
        latencyMs: data.latency_ms,
        sources: data.sources,
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (err: unknown) {
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: `Error: ${err.message ?? 'Failed to reach assistant'}. The assistant API may not be running.`,
          timestamp: Date.now() / 1000,
        },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }, [context, loading]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendQuery(input);
  };

  const ctxInfo = CONTEXT_LABELS[context];

  return (
    <div className="flex flex-col h-full bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-yellow-400" />
          <span className="text-sm font-semibold text-white">MERID Assistant</span>
        </div>
        <div className="relative">
          <button type="button"
            onClick={() => setShowContextMenu(!showContextMenu)}
            className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-slate-700/50 hover:bg-slate-700 transition-colors"
          >
            <span className={ctxInfo.color}>{ctxInfo.label}</span>
            <ChevronDown className="w-3 h-3 text-slate-400" />
          </button>
          {showContextMenu && (
            <div className="absolute right-0 top-full mt-1 w-36 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-50 py-1">
              {(Object.entries(CONTEXT_LABELS) as [ContextDomain, { label: string; color: string }][]).map(([key, val]) => (
                <button type="button"
                  key={key}
                  onClick={() => { setContext(key); setShowContextMenu(false); }}
                  className={`w-full text-left px-3 py-1.5 text-xs hover:bg-slate-700/50 transition-colors ${
                    context === key ? 'bg-slate-700/30' : ''
                  }`}
                >
                  <span className={val.color}>{val.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 min-h-[200px] max-h-[400px]">
        {messages.length === 0 && (
          <div className="text-center py-6">
            <Bot className="w-8 h-8 text-slate-600 mx-auto mb-2" />
            <p className="text-xs text-slate-500 mb-3">
              Ask about portfolio, risk, pipeline, agents, or system health
            </p>
            <div className="flex flex-wrap gap-1.5 justify-center">
              {SUGGESTED_QUERIES[context].map((q, i) => (
                <button type="button"
                  key={i}
                  onClick={() => sendQuery(q)}
                  className="text-[10px] px-2 py-1 bg-slate-700/40 hover:bg-slate-700/70 text-slate-400 hover:text-slate-200 rounded-full transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-2 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {msg.role === 'assistant' && (
              <div className="w-6 h-6 rounded-full bg-blue-500/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                <Bot className="w-3.5 h-3.5 text-blue-400" />
              </div>
            )}
            <div className={`max-w-[85%] rounded-lg px-3 py-2 ${
              msg.role === 'user'
                ? 'bg-blue-600/20 border border-blue-500/30 text-blue-100'
                : 'bg-slate-700/40 border border-slate-600/30 text-slate-200'
            }`}>
              <p className="text-xs leading-relaxed whitespace-pre-wrap">{msg.content}</p>
              {msg.role === 'assistant' && (msg.traceId || msg.latencyMs) && (
                <div className="flex items-center gap-2 mt-1.5 pt-1.5 border-t border-slate-600/30">
                  {msg.traceId && (
                    <span className="text-[9px] text-slate-500 font-mono">{msg.traceId}</span>
                  )}
                  {msg.latencyMs != null && (
                    <span className="text-[9px] text-slate-500">{msg.latencyMs.toFixed(0)}ms</span>
                  )}
                  {msg.sources && msg.sources.length > 0 && (
                    <span className="text-[9px] text-slate-500">{msg.sources.length} sources</span>
                  )}
                </div>
              )}
            </div>
            {msg.role === 'user' && (
              <div className="w-6 h-6 rounded-full bg-slate-600/40 flex items-center justify-center flex-shrink-0 mt-0.5">
                <User className="w-3.5 h-3.5 text-slate-400" />
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex gap-2">
            <div className="w-6 h-6 rounded-full bg-blue-500/20 flex items-center justify-center flex-shrink-0">
              <Loader2 className="w-3.5 h-3.5 text-blue-400 animate-spin" />
            </div>
            <div className="bg-slate-700/40 border border-slate-600/30 rounded-lg px-3 py-2">
              <p className="text-xs text-slate-400">Thinking…</p>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="px-4 py-3 border-t border-slate-700/50">
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            aria-label="Assistant query input"
            placeholder={`Ask the ${ctxInfo.label} assistant…`}
            className="flex-1 bg-slate-700/50 border border-slate-600/50 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20"
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            title="Send query"
            className="px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg transition-colors"
           aria-label="Send">
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      </form>
    </div>
  );
}
