/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MERID_API_URL?: string;
  readonly VITE_MERID_DASHBOARD_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
