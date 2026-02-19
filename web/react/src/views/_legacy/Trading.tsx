import React, { useState, useCallback, useMemo } from "react";
import { useApiData } from "../hooks/useApiData";
import { useMeridSocket } from "../hooks/useMeridSocket";
import { API_ENDPOINTS, WS_EVENTS, DEFAULTS } from "../config/constants";
import { formatCurrency, formatPercent, formatDateTime, formatNumber } from "../utils/formatters";
import { validateOrderTicket } from "../utils/validators";
import DataTableEnhanced from "../components/DataTableEnhanced";
import StatusIndicator from "../components/StatusIndicator";
import PriceTicker from "../components/PriceTicker";
import ArbitragePanel from "../components/ArbitragePanel";
import { OpenOrdersPanel } from "./OpenOrdersPanel";
import { LiveRiskStrip } from "./LiveRiskStrip";
import StubGate from "../components/StubGate";
import { StubBadge } from "../components/DataGuard";
import { DataAgeBadge } from "../components/DataAgeBadge";
import ConsensusPill from "../components/ConsensusPill";
import { useConsensusSummary } from "../hooks/useConsensusSummary";
import {
  TrendingUp, Send, Wallet, FileText, Zap,
  Shield, RefreshCw, AlertTriangle, CheckCircle2,
} from "lucide-react";

/* ═══════════════════════════════════════════════════════
   Types
   ═══════════════════════════════════════════════════════ */
interface TradingPosition {
  id: string;
  symbol: string;
  side: string;
  size: number;
  entryPrice: number;
  currentPrice: number;
  pnl: number;
  pnlPercent: number;
  venue: string;
  timestamp: string;
}

interface TradingOrder {
  id: string;
  symbol: string;
  side: string;
  orderType: string;
  size: number;
  price?: number;
  venue: string;
  status: string;
  timestamp: string;
}

interface Fill {
  id: string;
  orderId: string;
  symbol: string;
  side: string;
  size: number;
  price: number;
  venue: string;
  timestamp: string;
}

type TabId = "ticket" | "positions" | "orders" | "fills" | "arb" | "risk";

const TABS: Array<{ id: TabId; label: string; icon: React.ComponentType }> = [
  { id: "ticket", label: "TradingOrder Ticket", icon: Send },
  { id: "positions", label: "Positions", icon: Wallet },
  { id: "orders", label: "Orders", icon: FileText },
  { id: "fills", label: "Fills", icon: CheckCircle2 },
  { id: "arb", label: "Arb Ops", icon: Zap },
  { id: "risk", label: "Risk", icon: Shield },
];

/* ═══════════════════════════════════════════════════════
   Main Component
   ═══════════════════════════════════════════════════════ */
export default function Trading() {
  const [activeTab, setActiveTab] = useState<TabId>("ticket");
  const [orderForm, setOrderForm] = useState({
    symbol: DEFAULTS.SYMBOLS[0] as typeof DEFAULTS.SYMBOLS[number],
    side: "BUY" as "BUY" | "SELL",
    orderType: "MARKET" as typeof DEFAULTS.ORDER_TYPES[number],
    size: "0.1",
    price: "",
    venue: DEFAULTS.VENUES[0] as typeof DEFAULTS.VENUES[number],
  });
  const [orderErrors, setOrderErrors] = useState<string[]>([]);
  const [orderSuccess, setOrderSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Consensus summary for the selected symbol
  const consensusSummary = useConsensusSummary();

  // Fetch data
  const { data: positions, refetch: refetchPositions, rawResponse: positionsRaw, lastUpdated: positionsUpdated, isStub: positionsIsStub } = useApiData<TradingPosition[]>(
    API_ENDPOINTS.POSITIONS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.POSITIONS }
  );

  const { data: orders, refetch: refetchOrders } = useApiData<TradingOrder[]>(
    API_ENDPOINTS.ORDERS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.ORDERS }
  );

  const { data: fills, refetch: refetchFills } = useApiData<Fill[]>(
    API_ENDPOINTS.FILLS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.ORDERS }
  );

  // WebSocket for real-time updates
  const { socket, connected } = useMeridSocket();

  React.useEffect(() => {
    if (socket && connected) {
      const handleOrderUpdate = () => { refetchOrders(); refetchPositions(); };
      const handleFillUpdate = () => { refetchFills(); refetchPositions(); };

      socket.on(WS_EVENTS.ORDER_UPDATE, handleOrderUpdate);
      socket.on(WS_EVENTS.FILL_UPDATE, handleFillUpdate);

      return () => {
        socket.off(WS_EVENTS.ORDER_UPDATE, handleOrderUpdate);
        socket.off(WS_EVENTS.FILL_UPDATE, handleFillUpdate);
      };
    }
  }, [socket, connected, refetchOrders, refetchFills, refetchPositions]);

  const handleOrderSubmit = useCallback(async (side?: "BUY" | "SELL") => {
    const formToSubmit = side ? { ...orderForm, side } : orderForm;
    const validation = validateOrderTicket(formToSubmit);
    if (!validation.valid) {
      setOrderErrors([validation.message || "Invalid order"]);
      return;
    }

    setOrderErrors([]);
    setOrderSuccess(null);
    setSubmitting(true);

    try {
      const response = await fetch(API_ENDPOINTS.SUBMIT_ORDER, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formToSubmit),
      });

      const result = await response.json();

      if (!response.ok || result.success === false) {
        throw new Error(result.error || result.detail || "TradingOrder submission failed");
      }

      setOrderSuccess(`${formToSubmit.side} ${formToSubmit.size} ${formToSubmit.symbol} — ${result.status || "submitted"}`);
      setOrderForm({ ...orderForm, size: "0.1", price: "" });

      // Refresh data
      setTimeout(() => { refetchOrders(); refetchPositions(); refetchFills(); }, DEFAULTS.TIMEOUTS.UI_FEEDBACK);
    } catch (error: unknown) {
      setOrderErrors([error.message || "Failed to submit order"]);
    } finally {
      setSubmitting(false);
    }
  }, [orderForm, refetchOrders, refetchPositions, refetchFills]);

  // Computed stats
  const totalPnl = useMemo(() =>
    (positions || []).reduce((s, p) => s + p.pnl, 0), [positions]
  );
  const posCount = (positions || []).length;
  const openOrderCount = (orders || []).filter(o => o.status !== "filled").length;

  /* ── Column Definitions ──────────────────────────── */
  const positionColumns = useMemo(() => [
    { key: "symbol" as keyof TradingPosition, label: "Symbol", sortable: true },
    {
      key: "side" as keyof TradingPosition, label: "Side",
      render: (value: string) => (
        <span className={`px-2 py-1 rounded text-xs font-bold ${value === "BUY" ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}`}>
          {value}
        </span>
      ),
    },
    { key: "size" as keyof TradingPosition, label: "Size", sortable: true, render: (v: number) => formatNumber(v, 4) },
    { key: "entryPrice" as keyof TradingPosition, label: "Entry", render: (v: number) => formatCurrency(v) },
    { key: "currentPrice" as keyof TradingPosition, label: "Current", render: (v: number) => formatCurrency(v) },
    {
      key: "pnl" as keyof TradingPosition, label: "P&L", sortable: true,
      render: (value: number, row: TradingPosition) => (
        <span className={value >= 0 ? "text-emerald-400" : "text-red-400"}>
          {formatCurrency(value)} ({formatPercent(row.pnlPercent / 100)})
        </span>
      ),
    },
    { key: "venue" as keyof TradingPosition, label: "Venue" },
  ], []);


  const fillColumns = useMemo(() => [
    { key: "timestamp" as keyof Fill, label: "Time", sortable: true, render: (v: string) => formatDateTime(v) },
    { key: "symbol" as keyof Fill, label: "Symbol" },
    {
      key: "side" as keyof Fill, label: "Side",
      render: (value: string) => (
        <span className={`px-2 py-1 rounded text-xs font-bold ${value === "BUY" ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}`}>
          {value}
        </span>
      ),
    },
    { key: "size" as keyof Fill, label: "Size", sortable: true, render: (v: number) => formatNumber(v, 4) },
    { key: "price" as keyof Fill, label: "Price", render: (v: number) => formatCurrency(v) },
    { key: "venue" as keyof Fill, label: "Venue" },
  ], []);

  return (
    <div className="space-y-5">
      {/* ─── Header ─────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-emerald-500/20 rounded-lg">
            <TrendingUp className="w-6 h-6 text-emerald-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Live Trading</h1>
            <div className="flex items-center gap-2 mt-0.5">
              <p className="text-sm text-slate-400">Paper trading · Real-time prices · Multi-venue</p>
              <ConsensusPill symbol={orderForm.symbol} summary={consensusSummary} />
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {positionsIsStub && <StubBadge data={positionsRaw} />}
          <DataAgeBadge lastUpdated={positionsUpdated} />
          <StatusIndicator status={connected ? "ONLINE" : "OFFLINE"} showText />
          <button type="button"
            onClick={() => { refetchPositions(); refetchOrders(); refetchFills(); }}
            className="p-2 rounded-lg hover:bg-slate-800 transition-colors"
            title="Refresh all"
          >
            <RefreshCw className="w-4 h-4 text-slate-400" />
          </button>
        </div>
      </div>

      {/* ─── Price Tickers ──────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        {DEFAULTS.SYMBOLS.slice(0, 4).map((symbol) => (
          <PriceTicker key={symbol} symbol={symbol} showVolume />
        ))}
      </div>

      {/* ─── Stats Strip ────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
          <div className="text-xs text-slate-500 mb-1">Total P&L</div>
          <div className={`text-xl font-bold ${totalPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {totalPnl >= 0 ? "+" : ""}{formatCurrency(totalPnl)}
          </div>
        </div>
        <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
          <div className="text-xs text-slate-500 mb-1">Positions</div>
          <div className="text-xl font-bold text-white">{posCount}</div>
        </div>
        <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
          <div className="text-xs text-slate-500 mb-1">Open Orders</div>
          <div className="text-xl font-bold text-white">{openOrderCount}</div>
        </div>
        <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
          <div className="text-xs text-slate-500 mb-1">Recent Fills</div>
          <div className="text-xl font-bold text-white">{(fills || []).length}</div>
        </div>
      </div>

      {/* ─── Tab Navigation ─────────────────────── */}
      <nav className="flex items-center gap-1 bg-slate-900/60 rounded-xl p-1 border border-slate-800 overflow-x-auto">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          const badge =
            tab.id === "positions" ? posCount :
            tab.id === "orders" ? openOrderCount :
            tab.id === "fills" ? (fills || []).length :
            undefined;
          return (
            <button type="button"
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium whitespace-nowrap transition-all ${
                isActive
                  ? "bg-emerald-600/20 text-emerald-400 border border-emerald-500/30"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent"
              }`}
            >
              <Icon className="w-4 h-4" />
              <span>{tab.label}</span>
              {badge !== undefined && badge > 0 && (
                <span className="bg-emerald-500/30 text-emerald-300 text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                  {badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* ─── Tab Content ────────────────────────── */}
      <div className="min-h-[500px]">

        {/* ═══ ORDER TICKET ═══ */}
        {activeTab === "ticket" && (
          <div className="space-y-6">
            {/* TradingOrder Form */}
            <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-6">
              <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                <Send className="w-5 h-5 text-emerald-400" />
                TradingOrder Ticket
              </h2>

              {/* Error / Success messages */}
              {orderErrors.length > 0 && (
                <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
                  <div>{orderErrors.map((e, i) => <p key={i} className="text-red-400 text-sm">{e}</p>)}</div>
                </div>
              )}
              {orderSuccess && (
                <div className="mb-4 p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                  <p className="text-emerald-400 text-sm">{orderSuccess}</p>
                </div>
              )}

              <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                <div>
                  <label htmlFor="order-symbol" className="block text-xs font-medium text-slate-500 mb-1">Symbol</label>
                  <select aria-label="Symbol"
                    id="order-symbol"
                    name="symbol"
                    title="Symbol"
                    value={orderForm.symbol}
                    onChange={(e) => setOrderForm({ ...orderForm, symbol: e.target.value as typeof DEFAULTS.SYMBOLS[number] })}
                    className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-emerald-500"
                  >
                    {DEFAULTS.SYMBOLS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>

                <div>
                  <label htmlFor="order-type" className="block text-xs font-medium text-slate-500 mb-1">TradingOrder Type</label>
                  <select aria-label="TradingOrder Type"
                    id="order-type"
                    name="orderType"
                    title="TradingOrder Type"
                    value={orderForm.orderType}
                    onChange={(e) => setOrderForm({ ...orderForm, orderType: e.target.value as typeof DEFAULTS.ORDER_TYPES[number] })}
                    className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-emerald-500"
                  >
                    {DEFAULTS.ORDER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>

                <div>
                  <label htmlFor="order-size" className="block text-xs font-medium text-slate-500 mb-1">Size</label>
                  <input aria-label="Size"
                    id="order-size"
                    name="orderSize"
                    type="number"
                    title="Size"
                    value={orderForm.size}
                    onChange={(e) => setOrderForm({ ...orderForm, size: e.target.value })}
                    step="0.01"
                    min="0.01"
                    placeholder="0.1"
                    className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-emerald-500"
                  />
                </div>

                {orderForm.orderType !== "MARKET" && (
                  <div>
                    <label htmlFor="order-price" className="block text-xs font-medium text-slate-500 mb-1">Price</label>
                    <input aria-label="Price"
                      id="order-price"
                      name="orderPrice"
                      type="number"
                      title="Limit Price"
                      value={orderForm.price}
                      onChange={(e) => setOrderForm({ ...orderForm, price: e.target.value })}
                      step="0.01"
                      min="0.01"
                      placeholder="Limit price"
                      className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                )}

                <div>
                  <label htmlFor="order-venue" className="block text-xs font-medium text-slate-500 mb-1">Venue</label>
                  <select aria-label="Venue"
                    id="order-venue"
                    name="venue"
                    title="Venue"
                    value={orderForm.venue}
                    onChange={(e) => setOrderForm({ ...orderForm, venue: e.target.value as typeof DEFAULTS.VENUES[number] })}
                    className="w-full px-3 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-emerald-500"
                  >
                    {DEFAULTS.VENUES.map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
              </div>

              {/* Buy / Sell Buttons — gated by StubGate when backend serves stub data */}
              <StubGate data={positionsRaw} label="Simulation only — orders disabled">
                <div className="flex gap-3 mt-5">
                  <button type="button"
                    onClick={() => handleOrderSubmit("BUY")}
                    disabled={submitting}
                    className="flex-1 py-3 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg font-bold text-sm transition-colors"
                  >
                    {submitting && orderForm.side === "BUY" ? "Submitting..." : "BUY"}
                  </button>
                  <button type="button"
                    onClick={() => handleOrderSubmit("SELL")}
                    disabled={submitting}
                    className="flex-1 py-3 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white rounded-lg font-bold text-sm transition-colors"
                  >
                    {submitting && orderForm.side === "SELL" ? "Submitting..." : "SELL"}
                  </button>
                </div>
              </StubGate>
            </div>

            {/* Live Risk Strip */}
            <LiveRiskStrip />
          </div>
        )}

        {/* ═══ POSITIONS ═══ */}
        {activeTab === "positions" && (
          <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                <Wallet className="w-5 h-5 text-blue-400" />
                Open Positions
              </h2>
              <span className={`text-sm font-bold ${totalPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                Total P&L: {totalPnl >= 0 ? "+" : ""}{formatCurrency(totalPnl)}
              </span>
            </div>
            <DataTableEnhanced
              data={positions || []}
              columns={positionColumns}
              pageSize={15}
              showPagination
              showFilter
            />
          </div>
        )}

        {/* ═══ ORDERS ═══ */}
        {activeTab === "orders" && <OpenOrdersPanel />}

        {/* ═══ FILLS ═══ */}
        {activeTab === "fills" && (
          <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-6">
            <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
              Recent Fills
            </h2>
            <DataTableEnhanced
              data={fills || []}
              columns={fillColumns}
              pageSize={15}
              showPagination
              showFilter
            />
          </div>
        )}

        {/* ═══ ARB OPS ═══ */}
        {activeTab === "arb" && <ArbitragePanel />}

        {/* ═══ RISK ═══ */}
        {activeTab === "risk" && <LiveRiskStrip />}
      </div>
    </div>
  );
}
