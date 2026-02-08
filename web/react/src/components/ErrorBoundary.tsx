import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface ErrorBoundaryProps {
  children: React.ReactNode;
  viewName?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

export default class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = {
    hasError: false,
  };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[ErrorBoundary]", this.props.viewName, error, info);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: undefined });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full items-center justify-center">
          <div className="max-w-md rounded-2xl border border-red-500/30 bg-slate-900/70 p-6 text-center shadow-xl">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-red-500/10">
              <AlertTriangle className="h-6 w-6 text-red-400" />
            </div>
            <h2 className="text-lg font-semibold text-white">View error</h2>
            <p className="mt-2 text-sm text-slate-400">
              {this.props.viewName
                ? `The ${this.props.viewName} view crashed while rendering.`
                : "This view crashed while rendering."}
            </p>
            {this.state.error?.message && (
              <p className="mt-2 text-xs text-red-300/80">
                {this.state.error.message}
              </p>
            )}
            <div className="mt-4 flex items-center justify-center gap-2">
              <button
                type="button"
                onClick={this.handleRetry}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-700/60 bg-slate-800/80 px-3 py-2 text-xs text-slate-200 hover:border-slate-600/80"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Try again
              </button>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="inline-flex items-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200 hover:border-red-400/60"
              >
                Reload
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
