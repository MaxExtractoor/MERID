import { useState, useEffect } from 'react';
import { Package, Download, Trash2, Settings, RefreshCw, AlertCircle, CheckCircle, Star, ExternalLink } from 'lucide-react';
import StubBanner from '../components/StubBanner';

interface Plugin {
  id: string;
  name: string;
  version: string;
  author: string;
  description: string;
  category: 'trading' | 'analytics' | 'data' | 'utility' | 'integration';
  status: 'installed' | 'available' | 'updating';
  rating: number;
  downloads: number;
  size: string;
  last_updated: string;
  dependencies?: string[];
  enabled: boolean;
}

interface PluginStats {
  total_installed: number;
  total_enabled: number;
  total_available: number;
  updates_available: number;
}

export default function Plugins() {
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [stats, setStats] = useState<PluginStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rawData, setRawData] = useState<any>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [activeTab, setActiveTab] = useState<'installed' | 'available'>('installed');

  useEffect(() => {
    fetchPluginData();
    const interval = setInterval(fetchPluginData, 30000);
    return () => clearInterval(interval);
  }, []);

  const fetchPluginData = async () => {
    try {
      const response = await fetch('/api/v1/plugins/list');
      if (response.ok) {
        const data = await response.json();
        setRawData(data);
        setPlugins(data.plugins || []);
        setStats(data.stats || null);
        setError(null);
      } else {
        throw new Error('Failed to fetch plugin data');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      setRawData({ _stub: true, _stub_message: 'Plugin system unavailable', data_mode: 'offline' });
      setPlugins([]);
      setStats(null);
    } finally {
      setLoading(false);
    }
  };

  const installPlugin = async (pluginId: string) => {
    try {
      await fetch(`/api/v1/plugins/install/${pluginId}`, { method: 'POST' });
      fetchPluginData();
    } catch (err) {
      console.error('Failed to install plugin:', err);
    }
  };

  const uninstallPlugin = async (pluginId: string) => {
    try {
      await fetch(`/api/v1/plugins/uninstall/${pluginId}`, { method: 'DELETE' });
      fetchPluginData();
    } catch (err) {
      console.error('Failed to uninstall plugin:', err);
    }
  };

  const togglePlugin = async (pluginId: string) => {
    try {
      await fetch(`/api/v1/plugins/toggle/${pluginId}`, { method: 'POST' });
      fetchPluginData();
    } catch (err) {
      console.error('Failed to toggle plugin:', err);
    }
  };

  const getCategoryColor = (category: string) => {
    switch (category) {
      case 'trading': return 'text-green-400 bg-green-500/20';
      case 'analytics': return 'text-blue-400 bg-blue-500/20';
      case 'data': return 'text-purple-400 bg-purple-500/20';
      case 'utility': return 'text-gray-400 bg-gray-500/20';
      case 'integration': return 'text-orange-400 bg-orange-500/20';
      default: return 'text-gray-400 bg-gray-500/20';
    }
  };

  const filteredPlugins = plugins.filter(p => {
    const categoryMatch = selectedCategory === 'all' || p.category === selectedCategory;
    const tabMatch = activeTab === 'installed' ? p.status === 'installed' : p.status === 'available';
    return categoryMatch && tabMatch;
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 animate-spin text-blue-500 mx-auto mb-2" />
          <p className="text-gray-400">Loading plugins...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <StubBanner data={rawData} />
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Package className="w-8 h-8 text-indigo-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Plugin Manager</h1>
            <p className="text-sm text-gray-400">Extend functionality with plugins</p>
          </div>
        </div>
        <button
          onClick={fetchPluginData}
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
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Package className="w-4 h-4 text-indigo-400" />
              <p className="text-xs text-gray-400">Installed</p>
            </div>
            <p className="text-2xl font-bold text-white">{stats.total_installed}</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <CheckCircle className="w-4 h-4 text-green-400" />
              <p className="text-xs text-gray-400">Enabled</p>
            </div>
            <p className="text-2xl font-bold text-green-400">{stats.total_enabled}</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Download className="w-4 h-4 text-blue-400" />
              <p className="text-xs text-gray-400">Available</p>
            </div>
            <p className="text-2xl font-bold text-white">{stats.total_available}</p>
          </div>

          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <RefreshCw className="w-4 h-4 text-yellow-400" />
              <p className="text-xs text-gray-400">Updates</p>
            </div>
            <p className="text-2xl font-bold text-yellow-400">{stats.updates_available}</p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-slate-700">
        {(['installed', 'available'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 font-medium transition-colors ${
              activeTab === tab
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {tab === 'installed' ? 'Installed Plugins' : 'Available Plugins'}
          </button>
        ))}
      </div>

      {/* Category Filter */}
      <div className="flex gap-2">
        {['all', 'trading', 'analytics', 'data', 'utility', 'integration'].map(cat => (
          <button
            key={cat}
            onClick={() => setSelectedCategory(cat)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              selectedCategory === cat
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-gray-400 hover:bg-slate-600'
            }`}
          >
            {cat.charAt(0).toUpperCase() + cat.slice(1)}
          </button>
        ))}
      </div>

      {/* Plugins Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {filteredPlugins.map(plugin => (
          <div key={plugin.id} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
            <div className="flex items-start justify-between mb-3">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-2">
                  <Package className="w-6 h-6 text-indigo-400" />
                  <h3 className="text-lg font-bold text-white">{plugin.name}</h3>
                </div>
                <div className="flex items-center gap-2 mb-2">
                  <span className={`px-2 py-1 rounded text-xs font-medium ${getCategoryColor(plugin.category)}`}>
                    {plugin.category}
                  </span>
                  <span className="text-sm text-gray-400">v{plugin.version}</span>
                  <span className="text-sm text-gray-500">by {plugin.author}</span>
                </div>
              </div>
              {plugin.status === 'installed' && (
                <div className={`px-3 py-1 rounded-full text-xs font-medium ${
                  plugin.enabled ? 'text-green-400 bg-green-500/20' : 'text-gray-400 bg-gray-500/20'
                }`}>
                  {plugin.enabled ? 'Enabled' : 'Disabled'}
                </div>
              )}
            </div>

            <p className="text-sm text-gray-300 mb-4">{plugin.description}</p>

            <div className="flex items-center gap-4 text-sm text-gray-400 mb-4">
              <div className="flex items-center gap-1">
                <Star className="w-4 h-4 text-yellow-400" />
                <span>{plugin.rating.toFixed(1)}</span>
              </div>
              <div className="flex items-center gap-1">
                <Download className="w-4 h-4" />
                <span>{plugin.downloads.toLocaleString()}</span>
              </div>
              <span>{plugin.size}</span>
              <span>Updated {new Date(plugin.last_updated).toLocaleDateString()}</span>
            </div>

            {plugin.dependencies && plugin.dependencies.length > 0 && (
              <div className="mb-4">
                <p className="text-xs text-gray-500 mb-1">Dependencies:</p>
                <div className="flex flex-wrap gap-1">
                  {plugin.dependencies.map(dep => (
                    <span key={dep} className="px-2 py-1 bg-slate-700 text-gray-400 text-xs rounded">
                      {dep}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="flex gap-2">
              {plugin.status === 'installed' ? (
                <>
                  <button
                    onClick={() => togglePlugin(plugin.id)}
                    className={`px-4 py-2 rounded-lg text-sm transition-colors ${
                      plugin.enabled
                        ? 'bg-yellow-600 hover:bg-yellow-700 text-white'
                        : 'bg-green-600 hover:bg-green-700 text-white'
                    }`}
                  >
                    {plugin.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button 
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm transition-colors"
                    title="Configure plugin"
                  >
                    <Settings className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => uninstallPlugin(plugin.id)}
                    className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm transition-colors"
                    title="Uninstall plugin"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </>
              ) : (
                <>
                  <button
                    onClick={() => installPlugin(plugin.id)}
                    className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm transition-colors flex items-center gap-2"
                  >
                    <Download className="w-4 h-4" />
                    Install
                  </button>
                  <button className="px-4 py-2 bg-slate-600 hover:bg-slate-700 text-white rounded-lg text-sm transition-colors flex items-center gap-2">
                    <ExternalLink className="w-4 h-4" />
                    Details
                  </button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>

      {filteredPlugins.length === 0 && (
        <div className="text-center py-12">
          <Package className="w-16 h-16 text-gray-600 mx-auto mb-4" />
          <p className="text-gray-400">No plugins found in this category</p>
        </div>
      )}
    </div>
  );
}
