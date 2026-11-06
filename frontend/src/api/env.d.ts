/// <reference types="vite/client" />

// URLs base de cada microservicio (salidas de `serverless deploy`). Se configuran en Amplify y en frontend/.env.local.
interface ImportMetaEnv {
  readonly VITE_API_IDENTITY_URL: string;
  readonly VITE_API_CMDB_URL: string;
  readonly VITE_API_INCIDENTS_URL: string;
  readonly VITE_API_PROBLEMS_URL: string;
  readonly VITE_API_CHANGES_URL: string;
  readonly VITE_API_REQUESTS_URL: string;
  /** "true" fuerza el simulador en todos los servicios (src/mocks). */
  readonly VITE_USE_MOCKS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
