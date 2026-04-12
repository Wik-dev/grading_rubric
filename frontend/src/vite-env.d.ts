/// <reference types="vite/client" />

// DR-UI-01: VITE_VALIDANCE_BASE_URL is the only build-time env the SPA
// reads. It is the base URL of the running Validance instance and is
// injected at build time per Vite's standard `import.meta.env` mechanism.
interface ImportMetaEnv {
  readonly VITE_VALIDANCE_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
