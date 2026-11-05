import { api, tokenStorage, decodeJwt, isTokenExpired } from './http';
import type { ApiResponse, AuthUser, JwtPayload, LoginRequest, LoginResponse } from '../types/api';

/** ms-identity: login y sesión. */
export const authService = {
  /** POST /auth/login (pública). Guarda el token y devuelve el usuario. */
  async login(body: LoginRequest): Promise<LoginResponse> {
    const { data } = await api.identity.post<ApiResponse<LoginResponse>>('/auth/login', {
      tenant_code: body.tenant_code.trim().toLowerCase(),
      email: body.email.trim().toLowerCase(),
      password: body.password,
    });
    tokenStorage.set(data.data.access_token);
    return data.data;
  },

  /** GET /auth/me: restaura la sesión al recargar la página. */
  async me(): Promise<AuthUser> {
    const { data } = await api.identity.get<ApiResponse<AuthUser>>('/auth/me');
    return data.data;
  },

  /** No hay endpoint de logout: el JWT simplemente se descarta. */
  logout(): void {
    tokenStorage.clear();
  },

  hasValidSession(): boolean {
    return !isTokenExpired(tokenStorage.get());
  },

  /** Claims del token actual, solo para la UI (p. ej. ocultar menús por rol). */
  currentClaims(): JwtPayload | null {
    const token = tokenStorage.get();
    return token ? decodeJwt(token) : null;
  },
};
