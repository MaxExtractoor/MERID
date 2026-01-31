import React, { useState } from "react";
import { useApiData } from "../hooks/useApiData";
import { useMeridSocket } from "../hooks/useMeridSocket";
import { API_ENDPOINTS, WS_EVENTS, DEFAULTS } from "../config/constants";
import { formatCurrency, formatPercent, formatDateTime, formatNumber } from "../utils/formatters";
import { validateOrderTicket } from "../utils/validators";
import DataTableEnhanced from "../components/DataTableEnhanced";
import StatusIndicator from "../components/StatusIndicator";
import PriceTicker from "../components/PriceTicker";
import { OpenOrdersPanel } from "./OpenOrdersPanel";

interface Position {
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

interface Order {
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

export default function Trading() {
  const [orderForm, setOrderForm] = useState({
    symbol: DEFAULTS.SYMBOLS[0] as typeof DEFAULTS.SYMBOLS[number],
    side: "BUY" as "BUY" | "SELL",
    orderType: "MARKET" as typeof DEFAULTS.ORDER_TYPES[number],
    size: "0.1",
    price: "",
    venue: DEFAULTS.VENUES[0] as typeof DEFAULTS.VENUES[number],
  });
  const [orderErrors, setOrderErrors] = useState<string[]>([]);
  const [selectedSymbol] = useState<string | null>(null);

  // Fetch data
  const { data: positions } = useApiData<Position[]>(
    API_ENDPOINTS.POSITIONS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.POSITIONS }
  );

  const { data: orders } = useApiData<Order[]>(
    API_ENDPOINTS.ORDERS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.ORDERS }
  );

  const { data: fills } = useApiData<Fill[]>(
    API_ENDPOINTS.FILLS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.ORDERS }
  );

  // WebSocket for real-time updates
  const { socket, connected } = useMeridSocket();

  React.useEffect(() => {
    if (socket && connected) {
      socket.emit(WS_EVENTS.SUBSCRIBE_PRICES, [selectedSymbol]);
      
      const handlePriceTick = (data: any) => {
        // Update position prices based on price ticks
        if (data.symbol === selectedSymbol) {
          // This would trigger a refetch of positions
        }
      };

      const handleOrderUpdate = () => {
        // This would trigger a refetch of orders
      };

      const handleFillUpdate = () => {
        // This would trigger a refetch of fills
      };

      socket.on(WS_EVENTS.PRICE_TICK, handlePriceTick);
      socket.on(WS_EVENTS.ORDER_UPDATE, handleOrderUpdate);
      socket.on(WS_EVENTS.FILL_UPDATE, handleFillUpdate);

      return () => {
        socket.off(WS_EVENTS.PRICE_TICK, handlePriceTick);
        socket.off(WS_EVENTS.ORDER_UPDATE, handleOrderUpdate);
        socket.off(WS_EVENTS.FILL_UPDATE, handleFillUpdate);
      };
    }
  }, [socket, connected, selectedSymbol]);

  const handleOrderSubmit = async () => {
    const validation = validateOrderTicket(orderForm);
    if (!validation.valid) {
      setOrderErrors([validation.message || "Invalid order"]);
      return;
    }

    setOrderErrors([]);

    try {
      const response = await fetch(`${API_ENDPOINTS.SUBMIT_ORDER}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("merid-access")}`,
        },
        body: JSON.stringify(orderForm),
      });

      if (!response.ok) {
        throw new Error("Order submission failed");
      }

      // Reset form
      setOrderForm({
        ...orderForm,
        size: "0.1",
        price: "",
      });

      // Refetch orders
      // This would be handled by the polling hook
    } catch (error) {
      setOrderErrors(["Failed to submit order"]);
    }
  };

  const positionColumns = [
    {
      key: "symbol" as keyof Position,
      label: "Symbol",
      sortable: true,
    },
    {
      key: "side" as keyof Position,
      label: "Side",
      render: (value: string) => (
        <span className={`px-2 py-1 rounded text-xs font-medium ${
          value === "BUY" ? "bg-green-500/20 text-green-500" : "bg-red-500/20 text-red-500"
        }`}>
          {value}
        </span>
      ),
    },
    {
      key: "size" as keyof Position,
      label: "Size",
      sortable: true,
    },
    {
      key: "entryPrice" as keyof Position,
      label: "Entry",
      render: (value: number) => formatCurrency(value),
    },
    {
      key: "currentPrice" as keyof Position,
      label: "Current",
      render: (value: number) => formatCurrency(value),
    },
    {
      key: "pnl" as keyof Position,
      label: "P&L",
      sortable: true,
      render: (value: number, row: Position) => (
        <span className={value >= 0 ? "text-green-500" : "text-red-500"}>
          {formatCurrency(value)} ({formatPercent(row.pnlPercent)})
        </span>
      ),
    },
    {
      key: "venue" as keyof Position,
      label: "Venue",
    },
  ];

  const orderColumns = [
    {
      key: "symbol" as keyof Order,
      label: "Symbol",
      sortable: true,
    },
    {
      key: "side" as keyof Order,
      label: "Side",
      render: (value: string) => (
        <span className={`px-2 py-1 rounded text-xs font-medium ${
          value === "BUY" ? "bg-green-500/20 text-green-500" : "bg-red-500/20 text-red-500"
        }`}>
          {value}
        </span>
      ),
    },
    {
      key: "orderType" as keyof Order,
      label: "Type",
    },
    {
      key: "size" as keyof Order,
      label: "Size",
      sortable: true,
    },
    {
      key: "price" as keyof Order,
      label: "Price",
      render: (value?: number) => value ? formatCurrency(value) : "Market",
    },
    {
      key: "venue" as keyof Order,
      label: "Venue",
    },
    {
      key: "status" as keyof Order,
      label: "Status",
      render: (value: string) => (
        <StatusIndicator 
          status={value === "filled" ? "GOOD" : value === "cancelled" ? "BAD" : "WARNING"}
          showText 
        />
      ),
    },
  ];

  const fillColumns = [
    {
      key: "timestamp" as keyof Fill,
      label: "Time",
      sortable: true,
      render: (value: string) => formatDateTime(value),
    },
    {
      key: "symbol" as keyof Fill,
      label: "Symbol",
    },
    {
      key: "side" as keyof Fill,
      label: "Side",
      render: (value: string) => (
        <span className={`px-2 py-1 rounded text-xs font-medium ${
          value === "BUY" ? "bg-green-500/20 text-green-500" : "bg-red-500/20 text-red-500"
        }`}>
          {value}
        </span>
      ),
    },
    {
      key: "size" as keyof Fill,
      label: "Size",
      sortable: true,
      render: (value: number) => formatNumber(value),
    },
    {
      key: "price" as keyof Fill,
      label: "Price",
      render: (value: number) => formatCurrency(value),
    },
    {
      key: "venue" as keyof Fill,
      label: "Venue",
    },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Live Trading</h1>
        <div className="flex items-center gap-2">
          <StatusIndicator status={connected ? "ONLINE" : "OFFLINE"} showText />
          <span className="text-sm text-slate-400">WebSocket</span>
        </div>
      </div>

      {/* Price Ticker */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {DEFAULTS.SYMBOLS.slice(0, 3).map((symbol) => (
          <PriceTicker
            key={symbol}
            symbol={symbol}
            showVolume
          />
        ))}
      </div>

      {/* Order Ticket */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Order Ticket</h2>
        
        {orderErrors.length > 0 && (
          <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
            {orderErrors.map((error, index) => (
              <p key={index} className="text-red-500 text-sm">{error}</p>
            ))}
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-400 mb-1">Symbol</label>
            <select
              title="Select trading symbol"
              value={orderForm.symbol}
              onChange={(e) => setOrderForm({ ...orderForm, symbol: e.target.value as typeof DEFAULTS.SYMBOLS[number] })}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            >
              {DEFAULTS.SYMBOLS.map((symbol) => (
                <option key={symbol} value={symbol}>{symbol}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-400 mb-1">Side</label>
            <select
              title="Select order side"
              value={orderForm.side}
              onChange={(e) => setOrderForm({ ...orderForm, side: e.target.value as "BUY" | "SELL" })}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            >
              {DEFAULTS.SIDES.map((side) => (
                <option key={side} value={side}>{side}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-400 mb-1">Order Type</label>
            <select
              title="Select order type"
              value={orderForm.orderType}
              onChange={(e) => setOrderForm({ ...orderForm, orderType: e.target.value as typeof DEFAULTS.ORDER_TYPES[number] })}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            >
              {DEFAULTS.ORDER_TYPES.map((type) => (
                <option key={type} value={type}>{type}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-400 mb-1">Size</label>
            <input
              type="number"
              title="Enter order size"
              placeholder="Order size"
              value={orderForm.size}
              onChange={(e) => setOrderForm({ ...orderForm, size: e.target.value })}
              step="0.01"
              min="0.01"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          {orderForm.orderType !== "MARKET" && (
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">Price</label>
              <input
                type="number"
                title="Enter limit price"
                value={orderForm.price}
                onChange={(e) => setOrderForm({ ...orderForm, price: e.target.value })}
                step="0.01"
                min="0.01"
                placeholder="Limit price"
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-slate-400 mb-1">Venue</label>
            <select
              title="Select trading venue"
              value={orderForm.venue}
              onChange={(e) => setOrderForm({ ...orderForm, venue: e.target.value as typeof DEFAULTS.VENUES[number] })}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            >
              {DEFAULTS.VENUES.map((venue) => (
                <option key={venue} value={venue}>{venue}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex gap-2 mt-4">
          <button
            onClick={handleOrderSubmit}
            className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg font-medium transition-colors"
          >
            Buy
          </button>
          <button
            onClick={() => setOrderForm({ ...orderForm, side: "SELL" })}
            className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg font-medium transition-colors"
          >
            Sell
          </button>
        </div>
      </div>

      {/* Positions */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Open Positions</h2>
        <DataTableEnhanced
          data={positions || []}
          columns={positionColumns}
          pageSize={10}
          showPagination
          showFilter
        />
      </div>

      {/* Open Orders */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Open Orders</h2>
        <DataTableEnhanced
          data={orders?.filter(o => o.status !== "filled") || []}
          columns={orderColumns}
          pageSize={10}
          showPagination
          showFilter
        />
      </div>

      {/* Open Orders Panel */}
      <OpenOrdersPanel />

      {/* Recent Fills */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Recent Fills</h2>
        <DataTableEnhanced
          data={fills || []}
          columns={fillColumns}
