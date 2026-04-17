import { createContext, useContext } from 'react';

// ── Context: tracks which endpoints are currently returning stub data ──

export interface StubRegistryContextValue {
  register: (endpoint: string, isStub: boolean) => void;
}

// eslint-disable-next-line @typescript-eslint/no-empty-function
const noop = () => {};

export const StubRegistryContext = createContext<StubRegistryContextValue>({
  register: noop,
});

export function useStubRegistry() {
  return useContext(StubRegistryContext);
}
