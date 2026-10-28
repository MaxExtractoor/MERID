/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE: string;
  readonly VITE_KALSHI_ONLY: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
