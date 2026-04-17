/**
 * LightweightPriceChart - Real-time price chart using lightweight-charts with WebSocket data feed.
 *
 * Connects to the MERID WebSocket market data stream and renders a live candlestick/line chart.
 */

import React, { useEffect, useRef, useState } from "react";

interface LightweightPriceChartProps {
  symbol: string;
  wsUrl?: string;
  height?: number;
}

interface PricePoint {
  time: number;
  value: number;
}

export const LightweightPriceChart: React.FC<LightweightPriceChartProps> = ({
  symbol,
  wsUrl,
  height = 300,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastPrice, setLastPrice] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const defaultWsUrl = wsUrl ?? `ws://localhost:8011/ws/market/${symbol}`;

  useEffect(() => {
    // Dynamically load lightweight-charts to avoid SSR issues
    let chart: any = null;
    let lineSeries: any = null;

    const initChart = async () => {
      try {
        // lightweight-charts integration
        const { createChart } = await import("lightweight-charts");
        if (!chartContainerRef.current) return;

        chart = createChart(chartContainerRef.current, {
          width: chartContainerRef.current.clientWidth,
          height,
          layout: {
            background: { color: "#1a1a2e" },
            textColor: "#d1d4dc",
          },
          grid: {
            vertLines: { color: "#2a2a3e" },
            horzLines: { color: "#2a2a3e" },
          },
          crosshair: { mode: 1 },
          rightPriceScale: { borderColor: "#485c7b" },
          timeScale: { borderColor: "#485c7b" },
        });

        lineSeries = chart.addLineSeries({
          color: "#00d8ff",
          lineWidth: 2,
        });
      } catch (err) {
        setError("Chart library not available");
      }
    };

    initChart();

    // WebSocket connection for real-time price data
    const connectWebSocket = () => {
      try {
        const ws = new WebSocket(defaultWsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          setConnected(true);
          setError(null);
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            const price = data.price ?? data.last_price ?? data.value;
            if (price != null && lineSeries) {
              const point: PricePoint = {
                time: Math.floor(Date.now() / 1000),
                value: Number(price),
              };
              lineSeries.update(point);
              setLastPrice(Number(price));
            }
          } catch {
            // Ignore malformed messages
          }
        };

        ws.onerror = () => {
          setError("WebSocket connection error");
          setConnected(false);
        };

        ws.onclose = () => {
          setConnected(false);
          // Reconnect after 3s
          setTimeout(connectWebSocket, 3000);
        };
      } catch (err) {
        setError("Failed to connect WebSocket");
      }
    };

    connectWebSocket();

    return () => {
      wsRef.current?.close();
      if (chart) {
        chart.remove();
      }
    };
  }, [symbol, defaultWsUrl, height]);

  return (
    <div style={{ position: "relative" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "4px 8px",
          background: "#1a1a2e",
          color: "#d1d4dc",
          fontSize: "12px",
        }}
      >
        <span>{symbol}</span>
        <span style={{ color: connected ? "#00ff88" : "#ff4444" }}>
          {connected ? "LIVE" : "OFFLINE"}
        </span>
        {lastPrice != null && (
          <span style={{ color: "#00d8ff" }}>${lastPrice.toFixed(2)}</span>
        )}
      </div>
      {error && (
        <div style={{ color: "#ff4444", fontSize: "11px", padding: "2px 8px" }}>
          {error}
        </div>
      )}
      <div ref={chartContainerRef} style={{ width: "100%", height }} />
    </div>
  );
};

export default LightweightPriceChart;
