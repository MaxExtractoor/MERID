/**
 * OpinionFeed - Live Stream of Agent Opinions
 * 
 * Shows real-time strategy opinions grouped by symbol with:
 * - Agent consensus/dissent visualization
 * - Confidence levels
 * - Consensus formation status
 */

import { useState, useEffect } from 'react';
import { useMeridSocket } from '../hooks/useMeridSocket';

interface Opinion {
  opinion_id: string;
  agent_id: string;
  agent_role: string;
  symbol: string;
  direction: 'long' | 'short' | 'flat' | 'reduce' | 'close';
  confidence: number;
  timestamp: number;
  rationale_summary: string;
  signal_strength: number;
}

interface SymbolOpinions {
  symbol: string;
  opinions: Opinion[];
  consensus_pending: boolean;
  consensus_formed: boolean;
  consensus_direction?: string;
  last_update: number;
}

export function OpinionFeed() {
  const [opinionsBySymbol, setOpinionsBySymbol] = useState<Map<string, SymbolOpinions>>(new Map());
  const { socket } = useMeridSocket();

  useEffect(() => {
    if (!socket) return;

    // Subscribe to opinion events
    const handleOpinion = (opinion: Opinion) => {
      setOpinionsBySymbol(prev => {
        const newMap = new Map(prev);
        const existing = newMap.get(opinion.symbol) || {
          symbol: opinion.symbol,
          opinions: [],
          consensus_pending: true,
          consensus_formed: false,
          last_update: Date.now(),
        };
        
        // Add new opinion and keep last 10
        const updatedOpinions = [opinion, ...existing.opinions].slice(0, 10);
        
        newMap.set(opinion.symbol, {
          ...existing,
          opinions: updatedOpinions,
          last_update: Date.now(),
        });
        
        return newMap;
      });
    };

    // Subscribe to consensus events
    const handleConsensus = (data: any) => {
      setOpinionsBySymbol(prev => {
        const newMap = new Map(prev);
        const existing = newMap.get(data.symbol);
        
        if (existing) {
          newMap.set(data.symbol, {
            ...existing,
            consensus_pending: false,
            consensus_formed: true,
            consensus_direction: data.decision,
            last_update: Date.now(),
          });
          
          // Reset after 5 seconds
          setTimeout(() => {
            setOpinionsBySymbol(current => {
              const resetMap = new Map(current);
              const item = resetMap.get(data.symbol);
              if (item) {
                resetMap.set(data.symbol, {
                  ...item,
                  consensus_formed: false,
                  consensus_pending: false,
                });
              }
              return resetMap;
            });
          }, 5000);
        }
        
        return newMap;
      });
    };

    socket.on('strategy_opinion', handleOpinion);
    socket.on('consensus_decision', handleConsensus);

    return () => {
      socket.off('strategy_opinion', handleOpinion);
      socket.off('consensus_decision', handleConsensus);
    };
  }, [socket]);

  const getDirectionColor = (direction: string) => {
    switch (direction) {
      case 'long': return 'text-green-400 bg-green-900/30';
      case 'short': return 'text-red-400 bg-red-900/30';
      case 'flat': return 'text-slate-400 bg-slate-800/30';
      case 'reduce': return 'text-yellow-400 bg-yellow-900/30';
      case 'close': return 'text-orange-400 bg-orange-900/30';
      default: return 'text-slate-400 bg-slate-800/30';
    }
  };

  const getDirectionSymbol = (direction: string) => {
    switch (direction) {
      case 'long': return '↑';
      case 'short': return '↓';
      case 'flat': return '→';
      case 'reduce': return '↘';
      case 'close': return '✕';
      default: return '•';
    }
  };

  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString('en-US', { 
      hour: '2-digit', 
      minute: '2-digit', 
      second: '2-digit' 
    });
  };

  const symbolsArray = Array.from(opinionsBySymbol.values())
    .sort((a, b) => b.last_update - a.last_update);

  return (
    <div className="bg-slate-800 rounded-lg p-4">
      <h3 className="text-lg font-semibold mb-4">Opinion Feed</h3>
      
      <div className="space-y-4">
        {symbolsArray.map(symbolData => (
          <div key={symbolData.symbol} className="bg-slate-900/50 rounded-lg p-3">
            {/* Symbol header with consensus status */}
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-white">{symbolData.symbol}</span>
                {symbolData.consensus_formed && (
                  <span className={`text-xs px-2 py-1 rounded ${getDirectionColor(symbolData.consensus_direction || 'flat')}`}>
                    Consensus: {symbolData.consensus_direction?.toUpperCase()}
                  </span>
                )}
                {symbolData.consensus_pending && !symbolData.consensus_formed && (
                  <span className="text-xs px-2 py-1 rounded bg-blue-900/30 text-blue-300 animate-pulse">
                    Pending Consensus
                  </span>
                )}
              </div>
              <span className="text-xs text-slate-400">
                {symbolData.opinions.length} opinion{symbolData.opinions.length !== 1 ? 's' : ''}
              </span>
            </div>

            {/* Opinion list */}
            <div className="space-y-2">
              {symbolData.opinions.map(opinion => (
                <div 
                  key={opinion.opinion_id}
                  className="flex items-start gap-3 text-sm bg-slate-800/50 rounded p-2"
                >
                  {/* Direction indicator */}
                  <div className={`px-2 py-1 rounded font-bold ${getDirectionColor(opinion.direction)}`}>
                    {getDirectionSymbol(opinion.direction)}
                  </div>

                  {/* Opinion details */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-xs text-slate-300">{opinion.agent_id}</span>
                      <span className="text-xs text-slate-500">({opinion.agent_role})</span>
                      <span className="text-xs text-slate-400">{formatTime(opinion.timestamp)}</span>
                    </div>
                    
                    {/* Confidence bar */}
                    <div className="flex items-center gap-2 mb-1">
                      <div className="flex-1 bg-slate-700 rounded-full h-2 overflow-hidden">
                        <div 
                          className="bg-blue-500 h-full transition-all"
                          style={{ width: `${opinion.confidence * 100}%` }}
                        />
                      </div>
                      <span className="text-xs text-slate-400 w-12 text-right">
                        {(opinion.confidence * 100).toFixed(0)}%
                      </span>
                    </div>

                    {/* Rationale */}
                    {opinion.rationale_summary && (
                      <div className="text-xs text-slate-400 truncate">
                        {opinion.rationale_summary}
                      </div>
                    )}
                  </div>

                  {/* Signal strength */}
                  <div className="text-xs text-right">
                    <div className="text-slate-500">Signal</div>
                    <div className={`font-bold ${
                      Math.abs(opinion.signal_strength) > 0.7 ? 'text-green-400' :
                      Math.abs(opinion.signal_strength) > 0.3 ? 'text-yellow-400' :
                      'text-slate-400'
                    }`}>
                      {opinion.signal_strength.toFixed(2)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}

        {symbolsArray.length === 0 && (
          <div className="text-center py-8 text-slate-400">
            No opinions yet...
          </div>
        )}
      </div>
    </div>
  );
}
