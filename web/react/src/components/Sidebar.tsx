import { 
  LayoutDashboard, 
  Activity, 
  Search, 
  TrendingUp, 
  Shield, 
  Cpu, 
  FileText, 
  Settings 
} from 'lucide-react';

type View = "overview" | "trading" | "agents" | "predictions" | "risk" | "api" | "research" | "logs" | "settings";

interface SidebarProps {
  current: View;
  onChange: (view: View) => void;
  className?: string;
}

const navigation = [
  { name: 'Overview', href: 'overview', icon: LayoutDashboard },
  { name: 'Live Trading', href: 'trading', icon: Activity },
  { name: 'Research', href: 'research', icon: Search },
  { name: 'Prediction Markets', href: 'predictions', icon: TrendingUp },
];

const management = [
  { name: 'Risk & Health', href: 'risk', icon: Shield },
  { name: 'Bots/Agents', href: 'agents', icon: Cpu },
  { name: 'API Dashboard', href: 'api', icon: FileText },
];

const system = [
  { name: 'Logs', href: 'logs', icon: FileText },
  { name: 'Settings', href: 'settings', icon: Settings },
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
      <nav className="flex-1 p-4 space-y-8">
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
                      : 'text-slate-400 hover:bg-slate-800 hover:text-white'
                    }
                  `}
                >
                  <Icon className="w-4 h-4" />
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
                      : 'text-slate-400 hover:bg-slate-800 hover:text-white'
                    }
                  `}
                >
                  <Icon className="w-4 h-4" />
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
                      : 'text-slate-400 hover:bg-slate-800 hover:text-white'
                    }
                  `}
                >
                  <Icon className="w-4 h-4" />
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
