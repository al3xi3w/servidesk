import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, userService } from '../api';
import type { User } from '../types/api';
import { normalizeError } from '../api/http';

export interface AsyncState<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
  setData: (v: T) => void;
}

/** Ejecuta una carga asíncrona cuando cambian las dependencias; descarta respuestas viejas. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const seq = useRef(0);

  useEffect(() => {
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    fn()
      .then((v) => {
        if (id === seq.current) setData(v);
      })
      .catch((e: unknown) => {
        if (id === seq.current) setError(normalizeError(e));
      })
      .finally(() => {
        if (id === seq.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}

// ------------------------------------------------------------------ Nombres de usuarios (caché por sesión)

const userCache = new Map<string, User>();

export function clearUserCache() {
  userCache.clear();
}

/** Resuelve IDs a usuarios con una sola llamada GET /users?ids=… (solo agent/admin). */
export function useUsers(ids: (string | null | undefined)[], enabled = true): Map<string, User> {
  const key = [...new Set(ids.filter(Boolean) as string[])].sort().join(',');
  const [, force] = useState(0);
  useEffect(() => {
    if (!enabled || !key) return;
    const missing = key.split(',').filter((id) => !userCache.has(id));
    if (!missing.length) return;
    let alive = true;
    userService
      .byIds(missing)
      .then((users) => {
        users.forEach((u) => userCache.set(u.id, u));
        if (alive) force((n) => n + 1);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [key, enabled]);
  return userCache;
}

/** Debounce simple para buscadores. */
export function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}
