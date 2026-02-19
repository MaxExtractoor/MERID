/**
 * LightweightPriceChart — TradingView Lightweight Charts stub for MERID.
 *
 * Upgrade path for candlestick/OHLCV price views. Pairs with dxFeed
 * WebSocket feed via /ws/market/{symbol} once credentials are available.
 *
 * Dependencies (install when activating):
 *   npm install lightweight-charts
 *
 * Usage:
 *   <LightweightPriceChart symbol="BTC/USDT" />
 */

import React, { useEffect, useRef, useState } from 'react';
import { logUiError } from '../../utils/logger';

// ── Types ────────────────────────────────────────────────────────────

interface CandleData {
  time: number; // Unix seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface LightweightPriceChartProps {
  symbol: string;
  wsUrl?: string;       // e.g. "ws://<host>/ws/market/BTC-USDT"
  pollUrl?: string;     // fallback: "/api/market/snapshot"
  pollIntervalMs?: number;
  height?: number;
}

// ── Stub / Fallback ──────────────────────────────────────────────────
//
// When lightweight-charts is not installed, this component renders a
// placeholder with the last price and a message to install the package.
// Once installed, replace the fallback with the real implementation below.

const LightweightPriceChart: React.FC<LightweightPriceChartProps> = ({
  symbol,
  wsUrl,
  pollUrl = '/api/market/snapshot',
  pollIntervalMs = 5000,
  height = 400,
}) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [lastCandle, setLastCandle] = useState<CandleData | null>(null);
  const [mode, setMode] = useState<'ws' | 'poll' | 'disconnected'>('disconnected');

  // ── WebSocket mode ───────────────────────────────────────────────
  useEffect(() => {
    if (!wsUrl) return;

    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(wsUrl);
      ws.onopen = () => setMode('ws');
      ws.onmessage = (event) => {
        try {
          const msg: CandleData = JSON.parse(event.data);
          setLastCandle(msg);
          // When lightweight-charts is installed, call:
          // candlestickSeries.update(msg);
        } catch (err) { logUiError('LightweightPriceChart', 'WS message parse failed', err); }
      };
      ws.onclose = () => setMode('disconnected');
      ws.onerror = () => setMode('disconnected');
    } catch (err) {
      logUiError('LightweightPriceChart', 'WS connect failed', err);
      setMode('disconnected');
    }

    return () => {
      ws?.close();
    };
  }, [wsUrl]);

  // ── Polling fallback ─────────────────────────────────────────────
  useEffect(() => {
    if (wsUrl) return; // prefer WebSocket

    setMode('poll');
    const fetchCandle = async () => {
      try {
        const res = await fetch(`${pollUrl}?symbols=${encodeURIComponent(symbol)}`);
        if (!res.ok) return;
        const data = await res.json();
        const quote = data.quotes?.[0];
        if (quote) {
          setLastCandle({
            time: Math.floor(Date.now() / 1000),
            open: quote.bid ?? 0,
            high: quote.ask ?? quote.bid ?? 0,
            low: quote.bid ?? 0,
            close: quote.last ?? quote.ask ?? 0,
            volume: quote.volume_24h,
          });
        }
      } catch (err) { logUiError('LightweightPriceChart', 'REST fetch failed', err); }
    };

    fetchCandle();
    const id = setInterval(fetchCandle, pollIntervalMs);
    return () => clearInterval(id);
  }, [wsUrl, pollUrl, symbol, pollIntervalMs]);

  // ── Render ───────────────────────────────────────────────────────
  //
  // STUB: When lightweight-charts is installed, replace this with:
  //
  //   import { createChart } from 'lightweight-charts';
  //   const chart = createChart(containerRef.current!, { width, height });
  //   const series = chart.addCandlestickSeries();
  //   // then call series.update(candle) on each WS message
  //
  // For now, render a placeholder card with last price info.

  const priceColor =
    lastCandle && lastCandle.close >= lastCandle.open
      ? 'text-green-400'
      : 'text-red-400';

  return (
    <div
      ref={containerRef}
      className="bg-gray-900 border border-gray-700 rounded-lg p-4"
      style={{ height }}
    >
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-300">
          {symbol} — Price Chart
        </h3>
        <span
          className={`text-xs px-2 py-0.5 rounded ${
            mode === 'ws'
              ? 'bg-green-900 text-green-300'
              : mode === 'poll'
              ? 'bg-yellow-900 text-yellow-300'
              : 'bg-gray-800 text-gray-500'
          }`}
        >
          {mode === 'ws' ? 'WebSocket' : mode === 'poll' ? 'Polling' : 'Disconnected'}
        </span>
      </div>

      {lastCandle ? (
        <div className="flex flex-col items-center justify-center h-3/4 space-y-2">
          <span className={`text-4xl font-mono font-bold ${priceColor}`}>
            {lastCandle.close.toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 6,
            })}
          </span>
          <div className="text-xs text-gray-500 space-x-4">
            <span>O {lastCandle.open.toFixed(2)}</span>
            <span>H {lastCandle.high.toFixed(2)}</span>
            <span>L {lastCandle.low.toFixed(2)}</span>
            <span>C {lastCandle.close.toFixed(2)}</span>
            {lastCandle.volume != null && (
              <span>Vol {lastCandle.volume.toLocaleString()}</span>
            )}
          </div>
          <p className="text-xs text-gray-600 mt-4">
            Install <code className="text-blue-400">lightweight-charts</code> to
            render full candlestick view
          </p>
        </div>
      ) : (
        <div className="flex items-center justify-center h-3/4 text-gray-600 text-sm">
          Waiting for data…
        </div>
      )}
    </div>
  );
};

export default LightweightPriceChart;
