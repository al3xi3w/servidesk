import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { authService, setUnauthorizedHandler } from '../api';
import type { AuthUser, LoginRequest, Role } from '../types/api';
import { clearUserCache } from '../lib/hooks';

interface AuthValue {
  user: AuthUser | null;
  /** true mientras se restaura la sesión al recargar. */
  booting: boolean;
  login: (body: LoginRequest) => Promise<AuthUser>;
  logout: () => void;
  can: (...roles: Role[]) => boolean;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [booting, setBooting] = useState(authService.hasValidSession());

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      clearUserCache();
      if (!window.location.pathname.startsWith('/login')) window.location.assign('/login?expired=1');
    });
    if (!authService.hasValidSession()) return;
    authService
      .me()
      .then(setUser)
      .catch(() => authService.logout())
      .finally(() => setBooting(false));
  }, []);

  const login = useCallback(async (body: LoginRequest) => {
    const res = await authService.login(body);
    clearUserCache();
    setUser(res.user);
    return res.user;
  }, []);

  const logout = useCallback(() => {
    authService.logout();
    clearUserCache();
    setUser(null);
  }, []);

  const can = useCallback((...roles: Role[]) => !!user && roles.includes(user.role), [user]);

  const value = useMemo(() => ({ user, booting, login, logout, can }), [user, booting, login, logout, can]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth fuera de AuthProvider');
  return ctx;
}

/** Usuario autenticado (solo dentro de rutas protegidas). */
export function useMe(): AuthUser {
  const { user } = useAuth();
  if (!user) throw new Error('Sin sesión');
  return user;
}
