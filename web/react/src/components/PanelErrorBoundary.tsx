import React from "react";
import { AlertTriangle, RefreshCw } from '../ui/icons';
import { logUiError } from '../utils/logger';

interface PanelErrorBoundaryProps {
  children: React.ReactNode;
  panelName?: string;
  fallback?: React.ReactNode;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
}

interface PanelErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

/**
 * PanelErrorBoundary — Granular error boundary for individual panels/sections.
 * 
 * Used for:
 * - Risk panels
 * - Portfolio sections  
 * - Data-heavy components that might fail independently
 * - WebSocket-powered panels
 * 
 * Unlike the main ErrorBoundary which crashes the whole view,
 * this shows a localized error that doesn't break the entire page.
 */
export class PanelErrorBoundary extends React.Component<
  PanelErrorBoundaryProps,
  PanelErrorBoundaryState
> {
  state: PanelErrorBoundaryState = {
    hasError: false,
  };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    logUiError('PanelErrorBoundary', 'Panel crashed during render', error, {
      panelName: this.props.panelName ?? 'unknown',
      componentStack: info.componentStack ?? undefined,
    });
    this.props.onError?.(error, info);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: undefined });
  };

  render() {
    if (this.state.hasError) {
      // Custom fallback if provided
      if (this.props.fallback) {
        return this.props.fallback;
      }

      // Default panel error UI (compact, localized)
      return (
        <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4">
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-red-500/10">
              <AlertTriangle className="h-4 w-4 text-red-400" />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-medium text-red-300">
                {this.props.panelName 
                  ? `${this.props.panelName} unavailable` 
                  : "Section error"}
              </h3>
              <p className="mt-1 text-xs text-red-300/70">
                This section failed to load. Other parts of the view are still functional.
              </p>
              {this.state.error?.message && (
                <p className="mt-1 text-[10px] text-red-300/50 truncate">
                  {this.state.error.message}
                </p>
              )}
              <button
                type="button"
                onClick={this.handleRetry}
                className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1 text-xs text-red-300 hover:bg-red-500/20 transition-colors"
              >
                <RefreshCw className="h-3 w-3" />
                Retry
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default PanelErrorBoundary;
