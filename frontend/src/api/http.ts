/**
 * Clientes Axios de ServiDesk: uno por microservicio (cada uno tiene su propia URL de API Gateway).
 *
 * - El interceptor de request agrega `Authorization: Bearer <token>`.
 * - El interceptor de response convierte cualquier error en `ApiError` (NormalizedApiError).
 * - Nunca se envía tenant_id ni schema: el backend los toma del JWT.
 */
import axios, { AxiosError, type AxiosInstance } from 'axios';
import type {
  ApiErrorBody,
  FieldError,
  GatewayErrorBody,
  JwtPayload,
  NormalizedApiError,
} from '../types/api';

// ------------------------------------------------------------------ Token (sessionStorage, decisión D11)

const TOKEN_KEY = 'servidesk.access_token';

/** sessionStorage es por pestaña: permite tener Andina y Pacífico abiertos a la vez en la demo. */
export const tokenStorage = {
  get(): string | null {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string): void {
    try {
      sessionStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* almacenamiento no disponible: la sesión dura lo que la pestaña */
    }
  },
  clear(): void {
    try {
      sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* nada que limpiar */
    }
  },
};

/** Decodifica el payload del JWT SIN verificar la firma. Solo para la UI (expiración, rol); nunca para autorizar. */
export function decodeJwt(token: string): JwtPayload | null {
  try {
    const part = token.split('.')[1];
    const base64 = part.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(part.length / 4) * 4, '=');
    const json = decodeURIComponent(
      Array.from(atob(base64), (c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0')).join(''),
    );
    return JSON.parse(json) as JwtPayload;
  } catch {
    return null;
  }
}

/** true si no hay token o vence en menos de `skewSeconds`. */
export function isTokenExpired(token: string | null, skewSeconds = 30): boolean {
  if (!token) return true;
  const payload = decodeJwt(token);
  return !payload || payload.exp * 1000 <= Date.now() + skewSeconds * 1000;
}

// ------------------------------------------------------------------ Sesión vencida

type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler = () => {};

/** La app registra aquí qué hacer cuando la sesión no es válida (p. ej. limpiar estado y navegar a /login). */
export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  onUnauthorized = handler;
}

// ------------------------------------------------------------------ Errores

export class ApiError extends Error implements NormalizedApiError {
  status: number;
  code: NormalizedApiError['code'];
  details: FieldError[];
  requestId?: string;

  constructor(e: NormalizedApiError) {
    super(e.message);
    this.name = 'ApiError';
    this.status = e.status;
    this.code = e.code;
    this.details = e.details;
    this.requestId = e.requestId;
  }

  /** Mensaje del primer error de un campo, útil para formularios. */
  fieldError(field: string): string | undefined {
    return this.details.find((d) => d.field === field)?.issue;
  }
}

function isAppError(body: unknown): body is ApiErrorBody {
  return typeof body === 'object' && body !== null && 'error' in body && typeof (body as ApiErrorBody).error === 'object';
}

function isGatewayError(body: unknown): body is GatewayErrorBody {
  return typeof body === 'object' && body !== null && 'message' in body && !('error' in body);
}

export function normalizeError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  if (!axios.isAxiosError(err)) {
    return new ApiError({ status: 0, code: 'NETWORK_ERROR', message: String(err), details: [] });
  }
  const e = err as AxiosError<unknown>;
  if (!e.response) {
    return new ApiError({ status: 0, code: 'NETWORK_ERROR', message: 'No se pudo conectar con el servidor', details: [] });
  }
  const { status, data } = e.response;
  if (isAppError(data)) {
    return new ApiError({
      status,
      code: data.error.code,
      message: data.error.message,
      details: data.error.details ?? [],
      requestId: data.error.request_id,
    });
  }
  // API Gateway: 401 sin token, 403 token inválido o vencido.
  if (isGatewayError(data) && (status === 401 || status === 403)) {
    return new ApiError({ status, code: 'SESSION_EXPIRED', message: 'Tu sesión expiró. Inicia sesión de nuevo.', details: [] });
  }
  return new ApiError({ status, code: 'INTERNAL_ERROR', message: 'Error inesperado del servidor', details: [] });
}

// ------------------------------------------------------------------ Query params

/** Serializa params: arreglos separados por comas, omite undefined/null/''. */
export function serializeParams(params: Record<string, unknown> = {}): string {
  const out = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      if (value.length) out.set(key, value.join(','));
    } else {
      out.set(key, String(value));
    }
  }
  return out.toString();
}

// ------------------------------------------------------------------ Clientes

export type ServiceName = 'identity' | 'cmdb' | 'incidents' | 'problems' | 'changes' | 'requests';

const BASE_URLS: Record<ServiceName, string | undefined> = {
  identity: import.meta.env.VITE_API_IDENTITY_URL,
  cmdb: import.meta.env.VITE_API_CMDB_URL,
  incidents: import.meta.env.VITE_API_INCIDENTS_URL,
  problems: import.meta.env.VITE_API_PROBLEMS_URL,
  changes: import.meta.env.VITE_API_CHANGES_URL,
  requests: import.meta.env.VITE_API_REQUESTS_URL,
};

function createClient(service: ServiceName): AxiosInstance {
  const client = axios.create({
    baseURL: BASE_URLS[service],
    timeout: 15_000,
    headers: { 'Content-Type': 'application/json' },
    paramsSerializer: { serialize: (p) => serializeParams(p as Record<string, unknown>) },
  });

  client.interceptors.request.use((config) => {
    const token = tokenStorage.get();
    if (token) config.headers.set('Authorization', `Bearer ${token}`);
    return config;
  });

  client.interceptors.response.use(
    (response) => response,
    (error: unknown) => {
      const apiError = normalizeError(error);
      if (apiError.code === 'SESSION_EXPIRED') {
        tokenStorage.clear();
        onUnauthorized();
      }
      return Promise.reject(apiError);
    },
  );

  return client;
}

export const api: Record<ServiceName, AxiosInstance> = {
  identity: createClient('identity'),
  cmdb: createClient('cmdb'),
  incidents: createClient('incidents'),
  problems: createClient('problems'),
  changes: createClient('changes'),
  requests: createClient('requests'),
};
