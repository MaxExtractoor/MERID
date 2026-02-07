import { useState } from 'react';
import { ChevronDown, ChevronUp, Terminal } from 'lucide-react';
import ConsoleViewer from './ConsoleViewer';

export default function CollapsibleConsole() {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 overflow-hidden">
      {/* Header - Always Visible */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-slate-800/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <Terminal className="w-5 h-5 text-blue-400" />
          <div className="text-left">
            <h2 className="text-lg font-semibold text-slate-200">API Console</h2>
            <p className="text-sm text-slate-400">
              {isExpanded ? 'Live system events and API responses' : 'Click to expand console viewer'}
            </p>
          </div>
        </div>
        {isExpanded ? (
          <ChevronUp className="w-5 h-5 text-slate-400" />
        ) : (
          <ChevronDown className="w-5 h-5 text-slate-400" />
        )}
      </button>

      {/* Expandable Content */}
      {isExpanded && (
        <div className="border-t border-slate-800 p-6">
          <ConsoleViewer />
        </div>
      )}
    </div>
  );
}
