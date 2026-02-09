import { useState, useEffect } from 'react';
import { Cpu, Zap, DollarSign, TrendingUp, RefreshCw, AlertCircle, Thermometer, Activity } from 'lucide-react';
import StubBanner from '../components/StubBanner';

interface MiningRig {
  id: string;
  name: string;
  status: 'active' | 'idle' | 'offline';
  hashrate: number;
  power_consumption: number;
  temperature: number;
  uptime: number;
  shares_accepted: number;
  shares_rejected: number;
  pool: string;
}

interface MiningPool {
  id: string;
  name: string;
  url: string;
  algorithm: string;
  workers: number;
  hashrate: number;
  balance: number;
  last_payout: string;
}

interface MiningStats {
  total_hashrate: number;
  total_power: number;
  daily_revenue: number;
  daily_cost: number;
  daily_profit: number;
  efficiency: number;
  active_rigs: number;
  total_rigs: number;
}

export default function Mining() {
  const [rigs, setRigs] = useState<MiningRig[]>([]);
  const [pools, setPools] = useState<MiningPool[]>([]);
  const [stats, setStats] = useState<MiningStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rawResponse, setRawResponse] = useState<any>(null);
  const [activeTab, setActiveTab] = useState<'rigs' | 'pools' | 'stats'>('rigs');

  useEffect(() => {
    fetchMiningData();
    const interval = setInterval(fetchMiningData, 15000);
    return () => clearInterval(interval);
  }, []);

  const fetchMiningData = async () => {
    try {
      const response = await fetch('/api/v1/mining/overview');
      if (response.ok) {
        const data = await response.json();
        setRawResponse(data);
        setRigs(data.rigs || []);
        setPools(data.pools || []);
        setStats(data.stats || null);
        setError(null);
      } else {
        throw new Error('Failed to fetch mining data');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      setRigs([]);
      setPools([]);
      setStats(null);
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'text-green-400 bg-green-500/20';
      case 'idle': return 'text-yellow-400 bg-yellow-500/20';
      case 'offline': return 'text-red-400 bg-red-500/20';
      default: return 'text-gray-400 bg-gray-500/20';
    }
  };

  const getTempColor = (temp: number) => {
    if (temp >= 80) return 'text-red-400';
    if (temp >= 70) return 'text-yellow-400';
    return 'text-green-400';
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 animate-spin text-blue-500 mx-auto mb-2" />
          <p className="text-gray-400">Loading mining data...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <StubBanner data={rawResponse} />
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Cpu className="w-8 h-8 text-purple-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Mining Operations</h1>
            <p className="text-sm text-gray-400">Monitor and manage mining rigs</p>
          </div>
        </div>
        <button
          onClick={fetchMiningData}
          className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg flex items-center gap-2 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-yellow-500" />
          <div>
            <p className="text-yellow-500 font-medium">Using fallback data</p>
            <p className="text-sm text-gray-400">{error}</p>
          </div>
        </div>
      )}

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Activity className="w-4 h-4 text-purple-400" />
              <p className="text-xs text-gray-400">Hashrate</p>
            </div>
            <p className="text-2xl font-bold text-white">{stats.total_hashrate.toFixed(1)}</p>
            <p className="text-xs text-gray-400">MH/s</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Zap className="w-4 h-4 text-yellow-400" />
              <p className="text-xs text-gray-400">Power</p>
            </div>
            <p className="text-2xl font-bold text-white">{stats.total_power}</p>
            <p className="text-xs text-gray-400">Watts</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <DollarSign className="w-4 h-4 text-green-400" />
              <p className="text-xs text-gray-400">Daily Revenue</p>
            </div>
            <p className="text-2xl font-bold text-green-400">${stats.daily_revenue.toFixed(2)}</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <DollarSign className="w-4 h-4 text-red-400" />
              <p className="text-xs text-gray-400">Daily Cost</p>
            </div>
            <p className="text-2xl font-bold text-red-400">${stats.daily_cost.toFixed(2)}</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp className="w-4 h-4 text-emerald-400" />
              <p className="text-xs text-gray-400">Daily Profit</p>
            </div>
            <p className="text-2xl font-bold text-emerald-400">${stats.daily_profit.toFixed(2)}</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Cpu className="w-4 h-4 text-blue-400" />
              <p className="text-xs text-gray-400">Efficiency</p>
            </div>
            <p className="text-2xl font-bold text-white">{stats.efficiency.toFixed(3)}</p>
            <p className="text-xs text-gray-400">MH/W</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Activity className="w-4 h-4 text-cyan-400" />
              <p className="text-xs text-gray-400">Active Rigs</p>
            </div>
            <p className="text-2xl font-bold text-white">{stats.active_rigs}/{stats.total_rigs}</p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-slate-700">
        {(['rigs', 'pools', 'stats'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 font-medium transition-colors ${
              activeTab === tab
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {tab === 'rigs' ? 'Mining Rigs' : tab === 'pools' ? 'Pools' : 'Statistics'}
          </button>
        ))}
      </div>

      {/* Rigs Tab */}
      {activeTab === 'rigs' && (
        <div className="space-y-4">
          {rigs.map(rig => (
            <div key={rig.id} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <Cpu className="w-6 h-6 text-purple-400" />
                    <h3 className="text-lg font-bold text-white">{rig.name}</h3>
                    <span className={`px-3 py-1 rounded-full text-xs font-medium ${getStatusColor(rig.status)}`}>
                      {rig.status}
                    </span>
                  </div>
                  <p className="text-sm text-gray-400">Pool: {rig.pool}</p>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                <div>
                  <p className="text-xs text-gray-400 mb-1">Hashrate</p>
                  <p className="text-lg font-bold text-white">{rig.hashrate.toFixed(1)} MH/s</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">Power</p>
                  <p className="text-lg font-bold text-yellow-400">{rig.power_consumption}W</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">Temperature</p>
                  <div className="flex items-center gap-1">
                    <Thermometer className={`w-4 h-4 ${getTempColor(rig.temperature)}`} />
                    <p className={`text-lg font-bold ${getTempColor(rig.temperature)}`}>{rig.temperature}°C</p>
                  </div>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">Uptime</p>
                  <p className="text-lg font-bold text-green-400">{rig.uptime.toFixed(1)}%</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">Accepted</p>
                  <p className="text-lg font-bold text-white">{rig.shares_accepted.toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">Rejected</p>
                  <p className="text-lg font-bold text-red-400">{rig.shares_rejected}</p>
                </div>
              </div>

              <div className="mt-4 flex gap-2">
                <button className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm transition-colors">
                  Configure
                </button>
                {rig.status === 'active' ? (
                  <button className="px-4 py-2 bg-yellow-600 hover:bg-yellow-700 text-white rounded-lg text-sm transition-colors">
                    Stop
                  </button>
                ) : (
                  <button className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm transition-colors">
                    Start
                  </button>
                )}
                <button className="px-4 py-2 bg-slate-600 hover:bg-slate-700 text-white rounded-lg text-sm transition-colors">
                  Restart
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Pools Tab */}
      {activeTab === 'pools' && (
        <div className="space-y-4">
          {pools.map(pool => (
            <div key={pool.id} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                  <h3 className="text-lg font-bold text-white mb-2">{pool.name}</h3>
                  <p className="text-sm text-gray-400 mb-1">URL: {pool.url}</p>
                  <p className="text-sm text-gray-400">Algorithm: {pool.algorithm}</p>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-4">
                <div>
                  <p className="text-xs text-gray-400 mb-1">Workers</p>
                  <p className="text-lg font-bold text-white">{pool.workers}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">Hashrate</p>
                  <p className="text-lg font-bold text-purple-400">{pool.hashrate.toFixed(1)} MH/s</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">Balance</p>
                  <p className="text-lg font-bold text-green-400">{pool.balance.toFixed(3)} ETH</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">USD Value</p>
                  <p className="text-lg font-bold text-white">${(pool.balance * 3850).toFixed(2)}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-400 mb-1">Last Payout</p>
                  <p className="text-sm text-gray-300">{new Date(pool.last_payout).toLocaleDateString()}</p>
                </div>
              </div>

              <div className="flex gap-2">
                <button className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm transition-colors">
                  Request Payout
                </button>
                <button className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm transition-colors">
                  View Stats
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Stats Tab */}
      {activeTab === 'stats' && stats && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
              <h3 className="text-lg font-bold text-white mb-4">Profitability</h3>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">Daily Revenue</span>
                  <span className="text-xl font-bold text-green-400">${stats.daily_revenue.toFixed(2)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">Daily Cost</span>
                  <span className="text-xl font-bold text-red-400">-${stats.daily_cost.toFixed(2)}</span>
                </div>
                <div className="h-px bg-slate-700" />
                <div className="flex items-center justify-between">
                  <span className="text-white font-semibold">Daily Profit</span>
                  <span className="text-2xl font-bold text-emerald-400">${stats.daily_profit.toFixed(2)}</span>
                </div>
                <div className="mt-4 space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-400">Monthly Est.</span>
                    <span className="text-white font-medium">${(stats.daily_profit * 30).toFixed(2)}</span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-400">Yearly Est.</span>
                    <span className="text-white font-medium">${(stats.daily_profit * 365).toFixed(2)}</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
              <h3 className="text-lg font-bold text-white mb-4">Performance</h3>
              <div className="space-y-4">
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-gray-400">Total Hashrate</span>
                    <span className="text-white font-medium">{stats.total_hashrate.toFixed(1)} MH/s</span>
                  </div>
                  <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div className="h-full bg-gradient-to-r from-purple-500 to-pink-500" style={{ width: '100%' }} />
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-gray-400">Power Consumption</span>
                    <span className="text-white font-medium">{stats.total_power}W</span>
                  </div>
                  <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div className="h-full bg-gradient-to-r from-yellow-500 to-orange-500" style={{ width: '78%' }} />
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-gray-400">Efficiency</span>
                    <span className="text-white font-medium">{stats.efficiency.toFixed(3)} MH/W</span>
                  </div>
                  <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div className="h-full bg-gradient-to-r from-green-500 to-emerald-500" style={{ width: '82%' }} />
                  </div>
                </div>
                <div className="mt-4 pt-4 border-t border-slate-700">
                  <div className="flex items-center justify-between">
                    <span className="text-gray-400">Active Rigs</span>
                    <span className="text-2xl font-bold text-white">{stats.active_rigs} / {stats.total_rigs}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
            <h3 className="text-lg font-bold text-white mb-4">Cost Analysis</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div>
                <p className="text-sm text-gray-400 mb-2">Electricity Rate</p>
                <p className="text-xl font-bold text-white">$0.12/kWh</p>
              </div>
              <div>
                <p className="text-sm text-gray-400 mb-2">Daily kWh</p>
                <p className="text-xl font-bold text-white">{(stats.total_power * 24 / 1000).toFixed(2)}</p>
              </div>
              <div>
                <p className="text-sm text-gray-400 mb-2">Break-even Price</p>
                <p className="text-xl font-bold text-yellow-400">$3,200/ETH</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
