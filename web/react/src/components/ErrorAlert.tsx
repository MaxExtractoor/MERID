import React from 'react';
import { AlertTriangle, RefreshCw } from '../ui/icons';

interface ErrorAlertProps {
  message: string;
  onRetry?: () => void;
}

function ErrorAlert({ message, onRetry }: ErrorAlertProps) {
  return (
    <div className="bg-red-900/20 border border-red-500/30 rounded-xl p-4 flex items-center gap-3">
      <AlertTriangle className="w-5 h-5 text-red-400 shrink-0" />
      <div className="flex-1">
        <p className="text-sm text-red-300">{message}</p>
      </div>
      {onRetry && (
        <button type="button"
          onClick={onRetry}
          title="Retry"
          className="px-3 py-1.5 text-xs bg-red-900/40 hover:bg-red-900/60 text-red-300 rounded-lg transition-colors flex items-center gap-1.5"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Retry
        </button>
      )}
    </div>
  );
}

const MemoizedErrorAlert = React.memo(ErrorAlert);
MemoizedErrorAlert.displayName = 'ErrorAlert';
export default MemoizedErrorAlert;
