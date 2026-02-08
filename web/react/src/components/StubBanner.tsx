import { AlertTriangle } from 'lucide-react';
import { isStub, stubMessage } from '../utils/stub';

interface StubBannerProps {
  /** The API response data — if it contains `_stub: true`, the banner shows */
  data: unknown;
  /** Optional className override */
  className?: string;
}

/**
 * Displays a subtle banner when the data comes from a stub endpoint.
 *
 * Usage:
 *   const { data } = useApiData('/api/v1/wallet/balances');
 *   return (
 *     <>
 *       <StubBanner data={data} />
 *       {/* rest of component *\/}
 *     </>
 *   );
 */
export default function StubBanner({ data, className = '' }: StubBannerProps) {
  if (!isStub(data)) return null;

  const message = stubMessage(data);

  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 text-amber-300 text-xs ${className}`}
      role="status"
      aria-live="polite"
    >
      <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
      <span>{message}</span>
    </div>
  );
}
