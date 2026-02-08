import { 
  LayoutDashboard, 
  Activity, 
  Search, 
  TrendingUp, 
  Shield, 
  Settings,
  Bot,
  BarChart3,
  Database,
  Terminal,
  HeartPulse,
  Wallet,
  Coins,
  Twitter,
  Trophy,
  Cpu,
  Building2,
  Package,
  Monitor,
  Zap,
  Code2,
  Briefcase,
  ClipboardList,
  Star,
  Target
} from 'lucide-react';

type View = "overview" | "trading" | "agents" | "predictions" | "prediction-consensus" | "risk" | "health" | "api" | "research" | "logs" | "settings" | "analytics" | "wallet" | "treasury" | "social" | "betting" | "mining" | "institutional" | "plugins" | "operator" | "tradefloor" | "devswarm" | "positions" | "orders" | "rewards";

interface SidebarProps {
  current: View;
  onChange: (view: View) => void;
  className?: string;
}

const navigation = [
  { name: 'Overview', href: 'overview', icon: LayoutDashboard, color: 'text-blue-400' },
  { name: 'Wallet', href: 'wallet', icon: Wallet, color: 'text-yellow-400' },
  { name: 'Treasury', href: 'treasury', icon: Coins, color: 'text-amber-400' },
  { name: 'Live Trading', href: 'trading', icon: Activity, color: 'text-green-400' },
  { name: 'Trade Floor', href: 'tradefloor', icon: Zap, color: 'text-emerald-400' },
  { name: 'Positions', href: 'positions', icon: Briefcase, color: 'text-teal-400' },
  { name: 'Orders', href: 'orders', icon: ClipboardList, color: 'text-violet-400' },
  { name: 'Research', href: 'research', icon: Search, color: 'text-purple-400' },
  { name: 'Prediction Markets', href: 'predictions', icon: TrendingUp, color: 'text-orange-400' },
  { name: 'Prediction Consensus', href: 'prediction-consensus', icon: Target, color: 'text-blue-400' },
  { name: 'Betting Markets', href: 'betting', icon: Trophy, color: 'text-yellow-500' },
  { name: 'Rewards', href: 'rewards', icon: Star, color: 'text-amber-400' },
  { name: 'Social Feed', href: 'social', icon: Twitter, color: 'text-sky-400' },
];

const management = [
  { name: 'Operator', href: 'operator', icon: Monitor, color: 'text-orange-400' },
  { name: 'Risk & Health', href: 'risk', icon: Shield, color: 'text-red-400' },
  { name: 'Bots/Agents', href: 'agents', icon: Bot, color: 'text-cyan-400' },
  { name: 'Dev Swarm', href: 'devswarm', icon: Code2, color: 'text-lime-400' },
  { name: 'Mining', href: 'mining', icon: Cpu, color: 'text-purple-400' },
  { name: 'Institutional', href: 'institutional', icon: Building2, color: 'text-blue-500' },
  { name: 'Plugins', href: 'plugins', icon: Package, color: 'text-indigo-500' },
  { name: 'API Dashboard', href: 'api', icon: Database, color: 'text-indigo-400' },
  { name: 'Analytics', href: 'analytics', icon: BarChart3, color: 'text-pink-400' },
  { name: 'Settings', href: 'settings', icon: Settings, color: 'text-gray-400' },
];

const system = [
  { name: 'System Health', href: 'health', icon: HeartPulse, color: 'text-emerald-400' },
  { name: 'Logs', href: 'logs', icon: Terminal, color: 'text-gray-400' },
];

export default function Sidebar({ current, onChange, className }: SidebarProps) {
  return (
    <div className={`flex flex-col h-full bg-slate-900 border-r border-slate-800 ${className}`}>
      {/* Logo */}
      <div className="flex items-center gap-3 p-6 border-b border-slate-800">
        <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
          <span className="text-white font-bold text-sm">M</span>
        </div>
        <span className="text-xl font-bold text-white">MERID</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-8 overflow-y-auto">
        {/* Main Navigation */}
        <div>
          <h3 className="px-3 text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
            Main
          </h3>
          <div className="space-y-1">
            {navigation.map((item) => {
              const Icon = item.icon;
              const isActive = current === item.href;
              
              return (
                <button
                  key={item.name}
                  onClick={() => onChange(item.href as View)}
                  className={`
                    w-full flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-lg transition-colors
                    ${isActive 
                      ? 'bg-blue-600 text-white' 
                      : `${item.color} hover:bg-slate-800 hover:text-white`
                    }
                  `}
                >
                  <Icon className={`w-4 h-4 ${isActive ? 'text-white' : item.color}`} />
                  {item.name}
                </button>
              );
            })}
          </div>
        </div>

        {/* Management */}
        <div>
          <h3 className="px-3 text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
            Management
          </h3>
          <div className="space-y-1">
            {management.map((item) => {
              const Icon = item.icon;
              const isActive = current === item.href;
              
              return (
                <button
                  key={item.name}
                  onClick={() => onChange(item.href as View)}
                  className={`
                    w-full flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-lg transition-colors
                    ${isActive 
                      ? 'bg-blue-600 text-white' 
                      : `${item.color} hover:bg-slate-800 hover:text-white`
                    }
                  `}
                >
                  <Icon className={`w-4 h-4 ${isActive ? 'text-white' : item.color}`} />
                  {item.name}
                </button>
              );
            })}
          </div>
        </div>

        {/* System */}
        <div>
          <h3 className="px-3 text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
            System
          </h3>
          <div className="space-y-1">
            {system.map((item) => {
              const Icon = item.icon;
              const isActive = current === item.href;
              
              return (
                <button
                  key={item.name}
                  onClick={() => onChange(item.href as View)}
                  className={`
                    w-full flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-lg transition-colors
                    ${isActive 
                      ? 'bg-blue-600 text-white' 
                      : `${item.color} hover:bg-slate-800 hover:text-white`
                    }
                  `}
                >
                  <Icon className={`w-4 h-4 ${isActive ? 'text-white' : item.color}`} />
                  {item.name}
                </button>
              );
            })}
          </div>
        </div>
      </nav>
    </div>
  );
}
