interface LoadingStateProps {
  message?: string;
  subMessage?: string;
  fullHeight?: boolean;
  className?: string;
}

function LoadingState({
  message = "Loading...",
  subMessage,
  fullHeight = false,
  className = "",
}: LoadingStateProps) {
  return (
    <div
      className={`flex w-full items-center justify-center ${fullHeight ? "min-h-[60vh]" : ""} ${className}`}
      role="status"
      aria-live="polite"
    >
      <div className="text-center">
        <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        <p className="text-sm text-slate-400">{message}</p>
        {subMessage && <p className="mt-1 text-xs text-slate-500">{subMessage}</p>}
      </div>
    </div>
  );
}

const MemoizedLoadingState = React.memo(LoadingState);
MemoizedLoadingState.displayName = 'LoadingState';
export default MemoizedLoadingState;
