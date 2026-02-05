import { useState, useEffect } from 'react';
import { Search, RefreshCw } from 'lucide-react';

interface Order {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  type: 'market' | 'limit' | 'stop';
  quantity: number;
  price: number | null;
  status: 'open' | 'filled' | 'cancelled' | 'rejected';
  timestamp: string;
  venue: string;
}

export default function Orders() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    // Simulated data - replace with real API call
    const mockOrders: Order[] = [
      { id: 'ord-001', symbol: 'AAPL', side: 'buy', type: 'market', quantity: 100, price: 185.50, status: 'filled', timestamp: '2025-01-31 14:30:00', venue: 'Alpaca' },
      { id: 'ord-002', symbol: 'TSLA', side: 'sell', type: 'limit', quantity: 50, price: 245.00, status: 'open', timestamp: '2025-01-31 14:25:00', venue: 'Alpaca' },
      { id: 'ord-003', symbol: 'BTC-USD', side: 'buy', type: 'market', quantity: 0.5, price: 42500.00, status: 'filled', timestamp: '2025-01-31 14:20:00', venue: 'Coinbase' },
      { id: 'ord-004', symbol: 'ETH-USD', side: 'buy', type: 'limit', quantity: 2.0, price: 2550.00, status: 'open', timestamp: '2025-01-31 14:15:00', venue: 'Kraken' },
    ];
    
    setTimeout(() => {
      setOrders(mockOrders);
      setLoading(false);
    }, 500);
  }, []);

  const filteredOrders = orders.filter(order => {
    if (filter !== 'all' && order.status !== filter) return false;
    if (searchTerm && !order.symbol.toLowerCase().includes(searchTerm.toLowerCase())) return false;
    return true;
  });

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'filled': return 'text-emerald-400 bg-emerald-500/10';
      case 'open': return 'text-blue-400 bg-blue-500/10';
      case 'cancelled': return 'text-slate-400 bg-slate-500/10';
      case 'rejected': return 'text-rose-400 bg-rose-500/10';
      default: return 'text-slate-400';
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Orders</h1>
          <p className="text-slate-400">View and manage all trading orders</p>
        </div>
        <button className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition-colors">
          New Order
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-4 items-center bg-slate-900/70 rounded-xl p-4 border border-slate-800">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            id="order-search"
            name="orderSearch"
            type="text"
            placeholder="Search symbol..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-9 pr-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm focus:outline-none focus:border-blue-500 w-48"
          />
        </div>
        
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="all">All Status</option>
          <option value="open">Open</option>
          <option value="filled">Filled</option>
          <option value="cancelled">Cancelled</option>
          <option value="rejected">Rejected</option>
        </select>

        <button className="p-2 hover:bg-slate-800 rounded-lg transition-colors" title="Refresh">
          <RefreshCw className="w-4 h-4 text-slate-400" />
        </button>
      </div>

      {/* Orders Table */}
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center">
            <div className="animate-spin w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
            <p className="text-slate-400">Loading orders...</p>
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-slate-800/50">
              <tr>
                <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">ID</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Symbol</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Side</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Type</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Quantity</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Price</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Status</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Venue</th>
                <th className="text-left px-4 py-3 text-sm font-medium text-slate-400">Time</th>
              </tr>
            </thead>
            <tbody>
              {filteredOrders.map((order) => (
                <tr key={order.id} className="border-t border-slate-800 hover:bg-slate-800/30">
                  <td className="px-4 py-3 text-sm font-mono text-slate-500">{order.id}</td>
                  <td className="px-4 py-3 text-sm font-medium">{order.symbol}</td>
                  <td className="px-4 py-3 text-sm">
                    <span className={order.side === 'buy' ? 'text-emerald-400' : 'text-rose-400'}>
                      {order.side.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-300 capitalize">{order.type}</td>
                  <td className="px-4 py-3 text-sm">{order.quantity}</td>
                  <td className="px-4 py-3 text-sm">${order.price?.toFixed(2) || 'Market'}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(order.status)}`}>
                      {order.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-400">{order.venue}</td>
                  <td className="px-4 py-3 text-sm text-slate-400">{order.timestamp}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        
        {!loading && filteredOrders.length === 0 && (
          <div className="p-8 text-center text-slate-400">
            No orders found matching your criteria.
          </div>
        )}
      </div>
    </div>
  );
}
