import { useState, useEffect } from 'react';
import { Wallet as WalletIcon, Send, Download, RefreshCw, HardDrive, AlertCircle, CheckCircle } from 'lucide-react';
import StubBanner from '../components/StubBanner';

interface Balance {
  currency: string;
  available: number;
  locked: number;
  total: number;
}

interface Transaction {
  id: string;
  type: 'deposit' | 'withdrawal' | 'transfer';
  currency: string;
  amount: number;
  status: 'pending' | 'completed' | 'failed';
  timestamp: string;
  address?: string;
}

interface WalletData {
  balances: Balance[];
  transactions: Transaction[];
  total_value_usd: number;
  source?: 'live' | 'stub';
}

export default function Wallet() {
  const [walletData, setWalletData] = useState<WalletData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCurrency, setSelectedCurrency] = useState<string>('all');

  useEffect(() => {
    fetchWalletData();
    const interval = setInterval(fetchWalletData, 30000);
    return () => clearInterval(interval);
  }, []);

  const fetchWalletData = async () => {
    try {
      const response = await fetch('/api/v1/wallet/balances');
      if (response.ok) {
        const data = await response.json();
        setWalletData(data);
        setError(null);
      } else {
        throw new Error('Failed to fetch wallet data');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const formatCurrency = (amount: number, currency: string) => {
    if (currency === 'USD') {
      return `$${amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    return `${amount.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 8 })} ${currency}`;
  };

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    return date.toLocaleDateString();
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'text-green-400';
      case 'pending': return 'text-yellow-400';
      case 'failed': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };

  const getTypeIcon = (type: string) => {
    switch (type) {
      case 'deposit': return <Download className="w-4 h-4 text-green-400" />;
      case 'withdrawal': return <Send className="w-4 h-4 text-red-400" />;
      case 'transfer': return <RefreshCw className="w-4 h-4 text-blue-400" />;
      default: return null;
    }
  };

  const filteredBalances = selectedCurrency === 'all' 
    ? walletData?.balances || []
    : walletData?.balances.filter(b => b.currency === selectedCurrency) || [];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 animate-spin text-blue-500 mx-auto mb-2" />
          <p className="text-gray-400">Loading wallet...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <StubBanner data={walletData} />
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <WalletIcon className="w-8 h-8 text-blue-500" />
          <div>
            <h1 className="text-2xl font-bold text-white">Wallet</h1>
            <div className="flex items-center gap-2">
              <p className="text-sm text-gray-400">Manage your funds and transactions</p>
              {walletData?.source === 'live' && (
                <span className="flex items-center gap-1 text-xs text-green-400">
                  <CheckCircle className="w-3 h-3" /> Live
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            disabled
            title="Receive — available in live trading mode"
            className="px-4 py-2 bg-blue-600/40 text-white/50 rounded-lg flex items-center gap-2 cursor-not-allowed"
          >
            <Download className="w-4 h-4" />
            Receive
          </button>
          <button
            disabled
            title="Send — available in live trading mode"
            className="px-4 py-2 bg-green-600/40 text-white/50 rounded-lg flex items-center gap-2 cursor-not-allowed"
          >
            <Send className="w-4 h-4" />
            Send
          </button>
          <button
            onClick={fetchWalletData}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg flex items-center gap-2 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>
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

      {/* Total Value Card */}
      <div className="bg-gradient-to-br from-blue-600 to-purple-600 rounded-xl p-6 shadow-lg">
        <p className="text-blue-100 text-sm mb-2">Total Portfolio Value</p>
        <p className="text-4xl font-bold text-white mb-4">
          ${walletData?.total_value_usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </p>
        <div className="flex gap-4 text-sm">
          <div>
            <p className="text-blue-100">Available</p>
            <p className="text-white font-medium">
              ${(walletData?.balances.reduce((sum, b) => sum + b.available, 0) || 0).toLocaleString()}
            </p>
          </div>
          <div>
            <p className="text-blue-100">Locked</p>
            <p className="text-white font-medium">
              ${(walletData?.balances.reduce((sum, b) => sum + b.locked, 0) || 0).toLocaleString()}
            </p>
          </div>
        </div>
      </div>

      {/* Currency Filter */}
      <div className="flex gap-2 overflow-x-auto pb-2">
        <button
          onClick={() => setSelectedCurrency('all')}
          className={`px-4 py-2 rounded-lg whitespace-nowrap transition-colors ${
            selectedCurrency === 'all'
              ? 'bg-blue-600 text-white'
              : 'bg-slate-800 text-gray-400 hover:bg-slate-700'
          }`}
        >
          All Assets
        </button>
        {walletData?.balances.map(balance => (
          <button
            key={balance.currency}
            onClick={() => setSelectedCurrency(balance.currency)}
            className={`px-4 py-2 rounded-lg whitespace-nowrap transition-colors ${
              selectedCurrency === balance.currency
                ? 'bg-blue-600 text-white'
                : 'bg-slate-800 text-gray-400 hover:bg-slate-700'
            }`}
          >
            {balance.currency}
          </button>
        ))}
      </div>

      {/* Balances Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {filteredBalances.map(balance => (
          <div key={balance.currency} className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
            <div className="flex items-center justify-between mb-3">
              <span className="text-lg font-bold text-white">{balance.currency}</span>
              <div className="w-10 h-10 bg-slate-700 rounded-full flex items-center justify-center">
                <WalletIcon className="w-5 h-5 text-blue-400" />
              </div>
            </div>
            <div className="space-y-2">
              <div>
                <p className="text-xs text-gray-400">Available</p>
                <p className="text-sm font-medium text-white">{formatCurrency(balance.available, balance.currency)}</p>
              </div>
              <div>
                <p className="text-xs text-gray-400">Locked</p>
                <p className="text-sm font-medium text-gray-300">{formatCurrency(balance.locked, balance.currency)}</p>
              </div>
              <div className="pt-2 border-t border-slate-700">
                <p className="text-xs text-gray-400">Total</p>
                <p className="text-base font-bold text-white">{formatCurrency(balance.total, balance.currency)}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Recent Transactions */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50">
        <div className="p-4 border-b border-slate-700/50">
          <h2 className="text-lg font-bold text-white">Recent Transactions</h2>
        </div>
        <div className="divide-y divide-slate-700/50">
          {walletData?.transactions.map(tx => (
            <div key={tx.id} className="p-4 hover:bg-slate-700/30 transition-colors">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {getTypeIcon(tx.type)}
                  <div>
                    <p className="text-white font-medium capitalize">{tx.type}</p>
                    <p className="text-sm text-gray-400">{formatTimestamp(tx.timestamp)}</p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-white font-medium">
                    {tx.type === 'withdrawal' ? '-' : '+'}{formatCurrency(tx.amount, tx.currency)}
                  </p>
                  <p className={`text-sm ${getStatusColor(tx.status)} capitalize`}>{tx.status}</p>
                </div>
              </div>
              {tx.address && (
                <p className="text-xs text-gray-500 mt-2 font-mono">To: {tx.address}</p>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Hardware Wallet Info */}
      <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50 flex items-center gap-3">
        <HardDrive className="w-6 h-6 text-purple-400" />
        <div>
          <p className="text-white font-medium">Hardware Wallet Support</p>
          <p className="text-sm text-gray-400">Connect Ledger or Trezor for enhanced security</p>
        </div>
        <button className="ml-auto px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition-colors">
          Connect
        </button>
      </div>
    </div>
  );
}
