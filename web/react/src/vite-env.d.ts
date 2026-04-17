/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE: string;
  readonly VITE_WS_URL: string;
  readonly VITE_WS_PORTFOLIO_URL: string;
  readonly VITE_KALSHI_ONLY: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
