import { Play, Pause, RefreshCw, AlertTriangle, Shield, Zap } from 'lucide-react';

interface QuickAction {
  id: string;
  label: string;
  icon: any;
  color: string;
  action: () => void;
  disabled?: boolean;
}

export default function QuickActionsPanel() {
  const actions: QuickAction[] = [
    {
      id: 'pause-trading',
      label: 'Pause Trading',
      icon: Pause,
      color: 'amber',
      action: () => console.log('Pause trading'),
    },
    {
      id: 'resume-trading',
      label: 'Resume Trading',
      icon: Play,
      color: 'emerald',
      action: () => console.log('Resume trading'),
    },
    {
      id: 'refresh-data',
      label: 'Refresh All Data',
      icon: RefreshCw,
      color: 'blue',
      action: () => window.location.reload(),
    },
    {
      id: 'emergency-stop',
      label: 'Emergency Stop',
      icon: AlertTriangle,
      color: 'rose',
      action: () => console.log('Emergency stop'),
    },
    {
      id: 'risk-check',
      label: 'Run Risk Check',
      icon: Shield,
      color: 'purple',
      action: () => console.log('Risk check'),
    },
    {
      id: 'force-sync',
      label: 'Force Sync',
      icon: Zap,
      color: 'cyan',
      action: () => console.log('Force sync'),
    },
  ];

  const getColorClasses = (color: string) => {
    const colors: Record<string, string> = {
      amber: 'bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 border-amber-500/30',
      emerald: 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border-emerald-500/30',
      blue: 'bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 border-blue-500/30',
      rose: 'bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 border-rose-500/30',
      purple: 'bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 border-purple-500/30',
      cyan: 'bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 border-cyan-500/30',
    };
    return colors[color] || colors.blue;
  };

  return (
    <div className="bg-slate-900/70 rounded-xl p-6 border border-slate-800">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-200">Quick Actions</h2>
        <p className="text-sm text-slate-400">Common system controls</p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {actions.map((action) => {
          const Icon = action.icon;
          return (
            <button
              key={action.id}
              onClick={action.action}
              disabled={action.disabled}
              className={`
                p-4 rounded-lg border transition-all
                disabled:opacity-50 disabled:cursor-not-allowed
                ${getColorClasses(action.color)}
              `}
            >
              <div className="flex flex-col items-center gap-2">
                <Icon className="w-5 h-5" />
                <span className="text-xs font-medium text-center">
                  {action.label}
                </span>
              </div>
            </button>
          );
        })}
      </div>

      <div className="mt-4 pt-4 border-t border-slate-800">
        <div className="text-xs text-slate-500 text-center">
          Keyboard shortcuts: Press <kbd className="px-1.5 py-0.5 bg-slate-800 rounded text-slate-400">?</kbd> for help
        </div>
      </div>
    </div>
  );
}
