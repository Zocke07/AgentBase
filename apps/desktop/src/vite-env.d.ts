/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Development only: the scratch sidecar's port. See `lib/sidecar.ts`. */
  readonly VITE_AGENTBASE_SIDECAR_PORT?: string;
}
