/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Where the engine is listening. Set in web/.env.local; defaults to
   *  http://127.0.0.1:8000 when unset. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
