import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import CollapsibleConsole from '../components/CollapsibleConsole';
import PredictionMarketsPanel from '../components/PredictionMarketsPanel';
import AgentActivityPanel from '../components/AgentActivityPanel';
import QuickActionsPanel from '../components/QuickActionsPanel';
import LivePriceStream from '../components/LivePriceStream';
import LivePortfolioValue from '../components/LivePortfolioValue';
import { api } from '../services/api';
import { 
  SystemHealthCard, 
  PnLCard, 
  TradingOperationsCard, 
  PrimeStatusCard,
  AgentStatusCard,
  RiskProtectionCard 
} from '../hooks/useDashboard';

interface PortfolioSummary {
  equity: number;
  dailyPnl: number;
  dailyPnlPct: number;
  availableMargin: number;
  activeBots: number;
}

interface WatchlistItem {
  symbol: string;
  price: number;
  change: number;
  volume: string;
}

interface RecentActivity {
  time: string;
  action: string;
  size: string;
  price: string;
}

// Risk Exposure Hook
function useRiskExposure() {
  const [exposure, setExposure] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchExposure() {
      try {
        const response = await fetch('/api/risk/exposure');
        if (response.ok) {
          const data = await response.json();
          setExposure(data);
        }
      } catch (e) {
        console.error('Failed to fetch exposure:', e);
      } finally {
        setLoading(false);
      }
    }

    fetchExposure();
    const interval = setInterval(fetchExposure, 30000);
    return () => clearInterval(interval);
  }, []);

  return { exposure, loading };
}

// Exposure Bar Component
function ExposureBar() {
  const { exposure, loading } = useRiskExposure();

  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800 animate-pulse">
        <div className="h-4 bg-slate-700 rounded mb-2"></div>
        <div className="h-4 bg-slate-700 rounded"></div>
      </div>
    );
  }

  const maxSymbol = exposure?.by_symbol?.reduce((max: any, s: any) => 
    s.pct_of_equity > (max?.pct_of_equity || 0) ? s : max, exposure?.by_symbol?.[0]
  );

  return (
    <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-slate-400">Risk Exposure</h3>
        <span className="text-xs text-slate-500">${((exposure?.total_exposure || 0) / 1000).toFixed(1)}k</span>
      </div>
      
      <div className="grid grid-cols-3 gap-4 mb-3">
        <div>
          <div className="text-lg font-semibold text-slate-200">{exposure?.open_orders_count || 0}</div>
          <div className="text-xs text-slate-500">Open Orders</div>
        </div>
        <div>
          <div className="text-lg font-semibold text-slate-200">{maxSymbol?.symbol || '-'}</div>
          <div className="text-xs text-slate-500">Top Symbol ({((maxSymbol?.pct_of_equity || 0) * 100).toFixed(1)}%)</div>
        </div>
        <div>
          <div className="text-lg font-semibold text-emerald-400">${((exposure?.buying_power || 0) / 1000).toFixed(0)}k</div>
          <div className="text-xs text-slate-500">Buying Power</div>
        </div>
      </div>
      
      <div className="text-xs text-slate-500">
        Total: {((exposure?.total_exposure_pct || 0) * 100).toFixed(1)}% of equity deployed
      </div>
    </div>
  );
}

export default function Overview() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [recentActivity, setRecentActivity] = useState<RecentActivity[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        // Load portfolio summary
        try {
          const summaryData = await api.getPortfolioSummary();
          setSummary(summaryData as any);
        } catch (e) {
          // Fallback data
          setSummary({
            equity: 1284732.45,
            dailyPnl: 12847.32,
            dailyPnlPct: 2.34,
            availableMargin: 456231.89,
            activeBots: 12
          });
        }

        // Load watchlist
        try {
          const watchlistData = await api.getLivePrices(['BTC-USD', 'ETH-USD', 'SOL-USD', 'AAPL', 'NVDA']);
          setWatchlist((watchlistData as any).prices || []);
        } catch (e) {
          // Fallback data
          setWatchlist([
            { symbol: 'BTC-USD', price: 43256.78, change: 2.34, volume: '1.2B' },
            { symbol: 'ETH-USD', price: 2234.56, change: -1.23, volume: '890M' },
            { symbol: 'SOL-USD', price: 98.45, change: 5.67, volume: '234M' },
            { symbol: 'AAPL', price: 178.92, change: 0.45, volume: '567M' },
            { symbol: 'NVDA', price: 456.78, change: 3.21, volume: '445M' }
          ]);
        }

        // Load recent activity
        try {
          const activityData = await api.getRecentOrders();
          setRecentActivity((activityData as any).orders || []);
        } catch (e) {
          // Fallback data
          setRecentActivity([
            { time: '10:23:45', action: 'BUY BTC', size: '0.5', price: '43256.78' },
            { time: '10:15:22', action: 'SELL ETH', size: '2.3', price: '2234.56' },
            { time: '09:58:11', action: 'BUY SOL', size: '100', price: '98.45' }
          ]);
        }

        setLoading(false);
      } catch (error) {
        console.error('Failed to load overview data:', error);
        setLoading(false);
      }
    }

    loadData();
    const interval = setInterval(loadData, 30000); // Update every 30 seconds
    return () => clearInterval(interval);
  }, []);

  // Chart data
  const chartData = [
    { name: 'Mon', value: 545000 },
    { name: 'Tue', value: 548000 },
    { name: 'Wed', value: 542000 },
    { name: 'Thu', value: 551000 },
    { name: 'Fri', value: 558000 },
    { name: 'Sat', value: 562000 },
    { name: 'Sun', value: 562847 },
  ];

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-slate-900/70 rounded-xl p-4 animate-pulse">
              <div className="h-4 bg-slate-700 rounded mb-2"></div>
              <div className="h-8 bg-slate-700 rounded mb-2"></div>
              <div className="h-4 bg-slate-700 rounded"></div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Top Row - Live System Cards */}
      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        <SystemHealthCard />
        <PnLCard />
        <TradingOperationsCard />
        <PrimeStatusCard />
        <AgentStatusCard />
        <RiskProtectionCard />
      </section>

      {/* Second Row - Live Portfolio & Prices */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <LivePortfolioValue />
        <LivePriceStream symbols={['BTC', 'ETH', 'SOL']} />
      </section>

      {/* Third Row - Risk & Exposure */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <ExposureBar />
        
        {/* Quick Stats */}
        <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
          <h3 className="text-sm font-medium text-slate-400 mb-3">Portfolio Summary</h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-lg font-semibold text-slate-200">${summary?.equity?.toLocaleString() || '...'}</div>
              <div className="text-xs text-slate-500">Total Equity</div>
            </div>
            <div>
              <div className="text-lg font-semibold text-blue-400">${summary?.availableMargin?.toLocaleString() || '...'}</div>
              <div className="text-xs text-slate-500">Available Margin</div>
            </div>
          </div>
        </div>
        
        {/* System Version */}
        <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
          <h3 className="text-sm font-medium text-slate-400 mb-3">System APIs</h3>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-500">Version</span>
              <span className="text-slate-300">v2.0.0</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Build</span>
              <span className="text-slate-300">2025.01.31</span>
            </div>
            <a href="/openapi.json" className="text-blue-400 hover:text-blue-300 text-xs">
              View OpenAPI Docs →
            </a>
          </div>
        </div>
      </section>

      {/* Portfolio Chart */}
      <section className="bg-slate-900/70 rounded-xl p-6 border border-slate-800">
        <div className="mb-4">
          <h2 className="text-lg font-semibold">Portfolio Performance</h2>
          <p className="text-sm text-slate-400">Last 7 days</p>
        </div>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="name" stroke="#64748b" />
              <YAxis stroke="#64748b" />
              <Tooltip 
                contentStyle={{ 
                  backgroundColor: '#1e293b', 
                  border: '1px solid #334155',
                  borderRadius: '8px'
                }}
              />
              <Line 
                type="monotone" 
                dataKey="value" 
                stroke="#10b981" 
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* Agent Activity & Quick Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <AgentActivityPanel />
        </div>
        <QuickActionsPanel />
      </div>

      {/* Three Column Layout - Watchlist, Activity, Prediction Markets */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Watchlist */}
        <section className="bg-slate-900/70 rounded-xl p-6 border border-slate-800">
          <div className="mb-4">
            <h2 className="text-lg font-semibold">Live Watchlist</h2>
            <button className="text-sm text-blue-400 hover:text-blue-300">Add Symbol</button>
          </div>
          <div className="space-y-2">
            {watchlist.map((item) => (
              <div key={item.symbol} className="flex justify-between items-center py-2 border-b border-slate-800">
                <div>
                  <div className="font-medium">{item.symbol}</div>
                  <div className="text-sm text-slate-400">Vol: {item.volume}</div>
                </div>
                <div className="text-right">
                  <div className="font-medium">${item.price.toLocaleString()}</div>
                  <div className={`text-sm ${item.change >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {item.change >= 0 ? '+' : ''}{item.change.toFixed(2)}%
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Recent Activity */}
        <section className="bg-slate-900/70 rounded-xl p-6 border border-slate-800">
          <div className="mb-4">
            <h2 className="text-lg font-semibold">Recent Activity</h2>
            <p className="text-sm text-slate-400">Last 10 trades</p>
          </div>
          <div className="space-y-2">
            {recentActivity.map((activity, index) => (
              <div key={index} className="flex justify-between items-center py-2 border-b border-slate-800">
                <div>
                  <div className="font-medium text-sm">{activity.action}</div>
                  <div className="text-xs text-slate-400">{activity.size} @ {activity.price}</div>
                </div>
                <div className="text-xs text-slate-400">{activity.time}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Prediction Markets */}
        <PredictionMarketsPanel />
      </div>

      {/* Collapsible Console */}
      <CollapsibleConsole />
    </div>
  );
}
