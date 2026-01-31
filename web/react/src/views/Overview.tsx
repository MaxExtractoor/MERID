import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

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

export default function Overview() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [recentActivity, setRecentActivity] = useState<RecentActivity[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        // Load portfolio summary
        const summaryResponse = await fetch('/api/v1/portfolio/summary');
        const summaryData = await summaryResponse.json();
        setSummary(summaryData);

        // Load watchlist
        const watchlistResponse = await fetch('/api/v1/prices/live?symbols=BTC-USD,ETH-USD,SOL-USD,AAPL,NVDA');
        const watchlistData = await watchlistResponse.json();
        setWatchlist(watchlistData.prices || []);

        // Load recent activity
        const activityResponse = await fetch('/api/v1/orders/recent');
        const activityData = await activityResponse.json();
        setRecentActivity(activityData.orders || []);

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
      {/* Metrics Grid */}
      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
          <h2 className="text-sm font-medium text-slate-400 mb-2">Total Equity</h2>
          <p className="mt-2 text-2xl font-semibold">
            ${summary?.equity?.toLocaleString() || '...'}
          </p>
          <p className="text-sm text-slate-400 mt-1">
            Available: ${summary?.availableMargin?.toLocaleString() || '...'}
          </p>
        </div>
        
        <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
          <h2 className="text-sm font-medium text-slate-400 mb-2">Daily P&L</h2>
          <p className={`mt-2 text-2xl font-semibold ${
            summary && summary.dailyPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
          }`}>
            {summary ? `${summary.dailyPnl >= 0 ? '+' : ''}$${summary.dailyPnl.toFixed(2)}` : '...'}
          </p>
          <p className={`text-sm mt-1 ${
            summary && summary.dailyPnlPct >= 0 ? 'text-emerald-400' : 'text-rose-400'
          }`}>
            {summary ? `${summary.dailyPnlPct >= 0 ? '+' : ''}${summary.dailyPnlPct.toFixed(2)}%` : '...'}
          </p>
        </div>
        
        <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
          <h2 className="text-sm font-medium text-slate-400 mb-2">Available Margin</h2>
          <p className="mt-2 text-2xl font-semibold text-blue-400">
            ${summary?.availableMargin?.toLocaleString() || '...'}
          </p>
          <p className="text-sm text-slate-400 mt-1">
            {summary ? `${((summary.availableMargin / summary.equity) * 100).toFixed(1)}% available` : '...'}
          </p>
        </div>
        
        <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
          <h2 className="text-sm font-medium text-slate-400 mb-2">Active Bots</h2>
          <p className="mt-2 text-2xl font-semibold text-purple-400">
            {summary?.activeBots || '...'}
          </p>
          <p className="text-sm text-slate-400 mt-1">3 paused</p>
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

      {/* Watchlist and Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
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
      </div>
    </div>
  );
}
