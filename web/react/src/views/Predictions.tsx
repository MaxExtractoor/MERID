import React, { useState } from "react";
import { useApiData } from "../hooks/useApiData";
import { useLocalStorage } from "../hooks/useLocalStorage";
import { API_ENDPOINTS, STATUS_TYPES } from "../config/constants";
import { formatCurrency, formatPercent, formatDateTime } from "../utils/formatters";
import MetricCard from "../components/MetricCard";
import StatusIndicator from "../components/StatusIndicator";
import DataTableEnhanced from "../components/DataTableEnhanced";
import { RiskStatus } from "../types/risk";

interface PredictionMarket {
  id: string;
  name: string;
  venue: "polymarket" | "kalshi";
  description: string;
  probability: number;
  volume: number;
  liquidity: number;
  resolutionTime: string;
  category: string;
  status: "active" | "resolved" | "suspended";
  outcome?: string;
}

interface PredictionPosition {
  id: string;
  marketId: string;
  marketName: string;
  venue: string;
  position: "yes" | "no";
  size: number;
  avgPrice: number;
  currentPrice: number;
  pnl: number;
  pnlPercent: number;
  timestamp: string;
}

export default function Predictions() {
  const [favorites, setFavorites] = useLocalStorage<string[]>("prediction-favorites", []);
  const [selectedVenue, setSelectedVenue] = useState<string>("all");
  const [selectedCategory, setSelectedCategory] = useState<string>("all");

  // Fetch markets data
  const { data: markets } = useApiData<PredictionMarket[]>(
    API_ENDPOINTS.PREDICTION_MARKETS,
    { pollingInterval: 30000 }
  );

  // Fetch positions data
  const { data: positions } = useApiData<PredictionPosition[]>(
    API_ENDPOINTS.PREDICTION_POSITIONS,
    { pollingInterval: 15000 }
  );

  const toggleFavorite = (marketId: string) => {
    setFavorites(prev => 
      prev.includes(marketId) 
        ? prev.filter(id => id !== marketId)
        : [...prev, marketId]
    );
  };

  const convertRiskStatus = (status: RiskStatus): keyof typeof STATUS_TYPES => {
    switch (status) {
      case "GOOD":
        return "GOOD";
      case "WARNING":
        return "WARNING";
      case "BAD":
        return "BAD";
      case "UNKNOWN":
      default:
        return "WARNING";
    }
  };

  const getMarketStatus = (status: string): RiskStatus => {
    switch (status) {
      case "active":
        return "GOOD";
      case "resolved":
        return "WARNING";
      case "suspended":
        return "BAD";
      default:
        return "UNKNOWN";
    }
  };

  const getPnLStatus = (pnl: number): RiskStatus => {
    return pnl >= 0 ? "GOOD" : "BAD";
  };

  const filteredMarkets = React.useMemo(() => {
    if (!markets) return [];
    
    return markets.filter(market => {
      const venueMatch = selectedVenue === "all" || market.venue === selectedVenue;
      const categoryMatch = selectedCategory === "all" || market.category === selectedCategory;
      return venueMatch && categoryMatch;
    });
  }, [markets, selectedVenue, selectedCategory]);

  const favoriteMarkets = React.useMemo(() => {
    if (!markets) return [];
    return markets.filter(market => favorites.includes(market.id));
  }, [markets, favorites]);

  const venues = React.useMemo(() => {
    if (!markets) return [];
    return [...new Set(markets.map(m => m.venue))];
  }, [markets]);

  const categories = React.useMemo(() => {
    if (!markets) return [];
    return [...new Set(markets.map(m => m.category))];
  }, [markets]);

  const getVenueColor = (venue: string) => {
    switch (venue) {
      case "polymarket": return "text-purple-500";
      case "kalshi": return "text-blue-500";
      default: return "text-slate-500";
    }
  };

  const getProbabilityColor = (probability: number) => {
    if (probability >= 70) return "text-green-500";
    if (probability >= 40) return "text-amber-500";
    return "text-red-500";
  };

  const getTimeToResolution = (resolutionTime: string) => {
    const now = new Date();
    const resolution = new Date(resolutionTime);
    const diff = resolution.getTime() - now.getTime();
    
    if (diff <= 0) return "Resolved";
    
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h`;
    return "< 1h";
  };

  const marketColumns = [
    {
      key: "name" as keyof PredictionMarket,
      label: "Market",
      sortable: true,
      render: (value: string, row: PredictionMarket) => (
        <div className="max-w-xs">
          <div className="font-medium text-white">{value}</div>
          <div className="text-xs text-slate-400 truncate">{row.description}</div>
        </div>
      ),
    },
    {
      key: "venue" as keyof PredictionMarket,
      label: "Venue",
      sortable: true,
      render: (value: string) => (
        <span className={`px-2 py-1 rounded text-xs font-medium ${getVenueColor(value)}`}>
          {value.toUpperCase()}
        </span>
      ),
    },
    {
      key: "category" as keyof PredictionMarket,
      label: "Category",
      sortable: true,
    },
    {
      key: "probability" as keyof PredictionMarket,
      label: "Probability",
      sortable: true,
      render: (value: number) => (
        <div className="flex items-center gap-2">
          <div className="w-16 bg-slate-700 rounded-full h-2">
            <div
              className={`h-2 rounded-full ${
                value >= 70 ? "bg-green-500" : value >= 40 ? "bg-amber-500" : "bg-red-500"
              }`}
              style={{ width: `${value}%` }}
            />
          </div>
          <span className={`text-sm font-medium ${getProbabilityColor(value)}`}>
            {value}%
          </span>
        </div>
      ),
    },
    {
      key: "volume" as keyof PredictionMarket,
      label: "Volume",
      sortable: true,
      render: (value: number) => formatCurrency(value),
    },
    {
      key: "liquidity" as keyof PredictionMarket,
      label: "Liquidity",
      sortable: true,
      render: (value: number) => formatCurrency(value),
    },
    {
      key: "resolutionTime" as keyof PredictionMarket,
      label: "Time to Resolution",
      sortable: true,
      render: (value: string) => getTimeToResolution(value),
    },
    {
      key: "status" as keyof PredictionMarket,
      label: "Status",
      render: (value: string) => (
        <StatusIndicator 
          status={convertRiskStatus(getMarketStatus(value))}
          showText 
        />
      ),
    },
    {
      key: "actions" as keyof PredictionMarket,
      label: "Actions",
      render: (_value: any, row: PredictionMarket) => (
        <button
          onClick={() => toggleFavorite(row.id)}
          className={`p-1 rounded ${
            favorites.includes(row.id) 
              ? "text-yellow-500 hover:text-yellow-400" 
              : "text-slate-400 hover:text-slate-300"
          }`}
          title={favorites.includes(row.id) ? "Remove from favorites" : "Add to favorites"}
        >
          {favorites.includes(row.id) ? "★" : "☆"}
        </button>
      ),
    },
  ];

  const positionColumns = [
    {
      key: "marketName" as keyof PredictionPosition,
      label: "Market",
      sortable: true,
      render: (value: string) => (
        <div className="max-w-xs truncate" title={value}>
          {value}
        </div>
      ),
    },
    {
      key: "venue" as keyof PredictionPosition,
      label: "Venue",
      render: (value: string) => (
        <span className={`px-2 py-1 rounded text-xs font-medium ${getVenueColor(value)}`}>
          {value.toUpperCase()}
        </span>
      ),
    },
    {
      key: "position" as keyof PredictionPosition,
      label: "Position",
      render: (value: string) => (
        <span className={`px-2 py-1 rounded text-xs font-medium ${
          value === "yes" ? "bg-green-500/20 text-green-500" : "bg-red-500/20 text-red-500"
        }`}>
          {value.toUpperCase()}
        </span>
      ),
    },
    {
      key: "size" as keyof PredictionPosition,
      label: "Size",
      sortable: true,
      render: (value: number) => formatCurrency(value),
    },
    {
      key: "avgPrice" as keyof PredictionPosition,
      label: "Avg Price",
      sortable: true,
      render: (value: number) => formatCurrency(value),
    },
    {
      key: "currentPrice" as keyof PredictionPosition,
      label: "Current Price",
      sortable: true,
      render: (value: number) => formatCurrency(value),
    },
    {
      key: "pnl" as keyof PredictionPosition,
      label: "P&L",
      sortable: true,
      render: (value: number) => (
        <span className={value >= 0 ? "text-green-500" : "text-red-500"}>
          {formatCurrency(value)}
        </span>
      ),
    },
    {
      key: "pnlPercent" as keyof PredictionPosition,
      label: "P&L %",
      sortable: true,
      render: (value: number) => (
        <span className={value >= 0 ? "text-green-500" : "text-red-500"}>
          {formatPercent(value)}
        </span>
      ),
    },
    {
      key: "createdAt" as keyof PredictionPosition,
      label: "Created",
      sortable: true,
      render: (value: string) => formatDateTime(value),
    },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Prediction Markets</h1>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-400">
            {favorites.length} favorites
          </span>
        </div>
      </div>

      {/* Summary Cards */}
      {markets && positions && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <MetricCard
            label="Active Markets"
            value={markets.filter(m => m.status === "active").length}
            status="GOOD"
          />
          <MetricCard
            label="Total Volume"
            value={markets.reduce((sum, m) => sum + m.volume, 0)}
            status="GOOD"
          />
          <MetricCard
            label="Open Positions"
            value={positions.length}
            status="WARNING"
          />
          <MetricCard
            label="Position P&L"
            value={positions.reduce((sum, p) => sum + p.pnl, 0)}
            status={convertRiskStatus(getPnLStatus(positions.reduce((sum, p) => sum + p.pnl, 0)))}
          />
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-400 mb-1">Venue</label>
          <select
            title="Filter by venue"
            value={selectedVenue}
            onChange={(e) => setSelectedVenue(e.target.value)}
            className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
          >
            <option value="all">All Venues</option>
            {venues.map(venue => (
              <option key={venue} value={venue}>{venue}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-400 mb-1">Category</label>
          <select
            title="Filter by category"
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
          >
            <option value="all">All Categories</option>
            {categories.map(category => (
              <option key={category} value={category}>{category}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Favorite Markets */}
      {favoriteMarkets.length > 0 && (
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
          <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <span className="text-yellow-500">★</span>
            Favorite Markets
          </h2>
          <DataTableEnhanced
            data={favoriteMarkets}
            columns={marketColumns}
            pageSize={5}
            showPagination={false}
            showFilter={false}
          />
        </div>
      )}

      {/* All Markets */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">
          All Markets ({filteredMarkets.length})
        </h2>
        <DataTableEnhanced
          data={filteredMarkets}
          columns={marketColumns}
          pageSize={15}
          showPagination
          showFilter
        />
      </div>

      {/* My Positions */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">My Positions</h2>
        <DataTableEnhanced
          data={positions || []}
          columns={positionColumns}
          pageSize={10}
          showPagination
          showFilter
        />
      </div>
    </div>
  );
}
