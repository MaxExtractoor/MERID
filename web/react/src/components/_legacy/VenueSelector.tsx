import { Building2, Check } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';

interface Venue {
  id: string;
  name: string;
  type: 'crypto' | 'stocks' | 'prediction' | 'paper';
  status: 'active' | 'limited' | 'inactive';
}

const VENUES: Venue[] = [
  // Crypto Exchanges
  { id: 'alpaca', name: 'Alpaca', type: 'stocks', status: 'active' },
  { id: 'coinbase', name: 'Coinbase Advanced', type: 'crypto', status: 'active' },
  { id: 'kraken', name: 'Kraken', type: 'crypto', status: 'active' },
  { id: 'binanceus', name: 'Binance US', type: 'crypto', status: 'limited' },
  { id: 'gemini', name: 'Gemini', type: 'crypto', status: 'limited' },
  { id: 'kucoin', name: 'KuCoin', type: 'crypto', status: 'limited' },
  { id: 'okx', name: 'OKX', type: 'crypto', status: 'limited' },
  { id: 'bitget', name: 'Bitget', type: 'crypto', status: 'limited' },
  { id: 'gateio', name: 'Gate.io', type: 'crypto', status: 'limited' },
  { id: 'htx', name: 'HTX (Huobi)', type: 'crypto', status: 'limited' },
  { id: 'mexc', name: 'MEXC', type: 'crypto', status: 'limited' },
  // Traditional
  { id: 'ibkr', name: 'Interactive Brokers', type: 'stocks', status: 'limited' },
  // Prediction Markets
  { id: 'kalshi', name: 'Kalshi', type: 'prediction', status: 'active' },
  { id: 'polymarket', name: 'Polymarket', type: 'prediction', status: 'limited' },
  // Paper Trading
  { id: 'merid-sim', name: 'MERID Simulator', type: 'paper', status: 'active' },
  { id: 'local-sim', name: 'Local Simulator', type: 'paper', status: 'active' },
];

interface VenueSelectorProps {
  selected: string;
  onChange: (venueId: string) => void;
  className?: string;
}

export default function VenueSelector({ selected, onChange, className = '' }: VenueSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [filter, setFilter] = useState<'all' | 'crypto' | 'stocks' | 'prediction' | 'paper'>('all');
  const dropdownRef = useRef<HTMLDivElement>(null);

  const selectedVenue = VENUES.find(v => v.id === selected) || VENUES[0];

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const filteredVenues = filter === 'all' 
    ? VENUES 
    : VENUES.filter(v => v.type === filter);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'text-green-400';
      case 'limited': return 'text-yellow-400';
      case 'inactive': return 'text-gray-500';
      default: return 'text-gray-400';
    }
  };

  const getStatusDot = (status: string) => {
    switch (status) {
      case 'active': return 'bg-green-400';
      case 'limited': return 'bg-yellow-400';
      case 'inactive': return 'bg-gray-500';
      default: return 'bg-gray-400';
    }
  };

  return (
    <div className={`relative ${className}`} ref={dropdownRef}>
      {/* Selected Venue Button */}
      <button type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg transition-colors"
      >
        <Building2 className="w-4 h-4 text-blue-400" />
        <span className="text-white font-medium">{selectedVenue.name}</span>
        <div className={`w-2 h-2 rounded-full ${getStatusDot(selectedVenue.status)}`} />
        <svg
          className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown */}
      {isOpen && (
        <div className="absolute top-full mt-2 w-80 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-50">
          {/* Filter Tabs */}
          <div className="flex gap-1 p-2 border-b border-slate-700">
            {(['all', 'crypto', 'stocks', 'prediction', 'paper'] as const).map(type => (
              <button type="button"
                key={type}
                onClick={() => setFilter(type)}
                className={`px-3 py-1 text-xs rounded transition-colors ${
                  filter === type
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-400 hover:text-white hover:bg-slate-700'
                }`}
              >
                {type === 'all' ? 'All' : type.charAt(0).toUpperCase() + type.slice(1)}
              </button>
            ))}
          </div>

          {/* Venue List */}
          <div className="max-h-96 overflow-y-auto">
            {filteredVenues.map(venue => (
              <button type="button"
                key={venue.id}
                onClick={() => {
                  onChange(venue.id);
                  setIsOpen(false);
                }}
                className={`w-full flex items-center justify-between px-4 py-3 hover:bg-slate-700/50 transition-colors ${
                  venue.id === selected ? 'bg-slate-700/30' : ''
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${getStatusDot(venue.status)}`} />
                  <div className="text-left">
                    <p className="text-white font-medium">{venue.name}</p>
                    <p className="text-xs text-gray-400 capitalize">{venue.type}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-xs ${getStatusColor(venue.status)} capitalize`}>
                    {venue.status}
                  </span>
                  {venue.id === selected && (
                    <Check className="w-4 h-4 text-blue-400" />
                  )}
                </div>
              </button>
            ))}
          </div>

          {/* Footer */}
          <div className="p-3 border-t border-slate-700 bg-slate-900/50">
            <p className="text-xs text-gray-400">
              <span className="text-green-400">●</span> Active
              <span className="ml-3 text-yellow-400">●</span> Limited
              <span className="ml-3 text-gray-500">●</span> Inactive
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
