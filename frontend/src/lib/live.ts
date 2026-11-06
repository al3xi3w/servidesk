import { useEffect, useRef } from 'react';
import { MOCKED_SERVICES } from '../api';
import { onMockEvents } from '../mocks/events';

/**
 * Recarga datos cuando el bus de eventos procesa algo en este tenant (modo demo).
 * Con el backend real no hace nada; ahí la consistencia llega al volver a consultar.
 */
export function useLiveRefresh(tenantId: string, ...reloads: (() => void)[]) {
  const fns = useRef(reloads);
  fns.current = reloads;
  useEffect(() => {
    if (!MOCKED_SERVICES.length) return;
    let t: ReturnType<typeof setTimeout>;
    const off = onMockEvents((id) => {
      if (id !== tenantId) return;
      clearTimeout(t);
      t = setTimeout(() => fns.current.forEach((r) => r()), 300);
    });
    return () => {
      off();
      clearTimeout(t);
    };
  }, [tenantId]);
}
