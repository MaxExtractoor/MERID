import { useCallback, useRef, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { StubRegistryContext } from '../hooks/useStubRegistry';

export function StubRegistryProvider({ children }: { children: React.ReactNode }) {
  const stubsRef = useRef<Set<string>>(new Set());
  const [stubCount, setStubCount] = useState(0);

  const register = useCallback((endpoint: string, isStub: boolean) => {
    const prev = stubsRef.current.size;
    if (isStub) {
      stubsRef.current.add(endpoint);
    } else {
      stubsRef.current.delete(endpoint);
    }
    if (stubsRef.current.size !== prev) {
      setStubCount(stubsRef.current.size);
    }
  }, []);

  return (
    <StubRegistryContext.Provider value={{ register }}>
      {children}
      {stubCount > 0 && <GlobalStubBannerInner count={stubCount} />}
    </StubRegistryContext.Provider>
  );
}

// ── Banner UI ──

function GlobalStubBannerInner({ count }: { count: number }) {
  return (
    <div className="fixed top-0 left-0 right-0 z-50 bg-yellow-900/95 border-b border-yellow-600/50 px-4 py-2 flex items-center justify-center gap-2 text-yellow-300 text-sm font-medium shadow-lg">
      <AlertTriangle className="w-4 h-4 flex-shrink-0" />
      <span>
        Stub Mode — {count} data source{count > 1 ? 's' : ''} returning simulated data.
        Metrics may not reflect reality.
      </span>
    </div>
  );
}
