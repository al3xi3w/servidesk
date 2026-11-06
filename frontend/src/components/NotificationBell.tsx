import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError, MOCKED_SERVICES, notificationService } from '../api';
import { useMe } from '../auth/AuthContext';
import { fromNow } from '../lib/format';
import { onMockEvents } from '../mocks/events';
import type { Notification } from '../types/api';
import { Icon, type IconName } from './Icon';

const ICON: Record<string, IconName> = { incident: 'incident', problem: 'problem', change: 'change', request: 'request', ci: 'cmdb' };
const PATH: Record<string, string> = { incident: 'incidents', problem: 'problems', change: 'changes', request: 'requests', ci: 'cmdb' };

/** Campana con la bandeja de ms-identity (llenada por el consumidor identity-notify-q). */
export function NotificationBell() {
  const me = useMe();
  const nav = useNavigate();
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [ring, setRing] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const prevUnread = useRef<number | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    notificationService
      .list(15)
      .then((r) => {
        setItems(r.data);
        setUnread(r.meta.unread);
        if (prevUnread.current !== null && r.meta.unread > prevUnread.current) {
          setRing(true);
          setTimeout(() => setRing(false), 1000);
        }
        prevUnread.current = r.meta.unread;
      })
      // Ruta propuesta (D16): si el backend real aún no la tiene, se oculta la campana.
      .catch((e: ApiError) => (e.status === 404 || e.code === 'NOT_FOUND') && setUnavailable(true));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 20_000);
    const off = MOCKED_SERVICES.includes('identity') ? onMockEvents((tenant) => tenant === me.tenant.id && setTimeout(load, 50)) : () => {};
    return () => {
      clearInterval(t);
      off();
    };
  }, [load, me.tenant.id]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  if (unavailable) return null;

  async function openItem(n: Notification) {
    setOpen(false);
    if (!n.read) {
      setItems((xs) => xs.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
      setUnread((u) => Math.max(0, u - 1));
      prevUnread.current = Math.max(0, (prevUnread.current ?? 1) - 1);
      notificationService.markRead({ ids: [n.id] }).catch(() => {});
    }
    if (n.resource_type && n.resource_id) nav(`/app/${PATH[n.resource_type]}/${n.resource_id}`);
  }

  async function readAll() {
    setItems((xs) => xs.map((x) => ({ ...x, read: true })));
    setUnread(0);
    prevUnread.current = 0;
    await notificationService.markRead().catch(() => {});
  }

  return (
    <div className="bell" ref={box}>
      <button className={`icon-btn ${ring ? 'ring' : ''}`} aria-label={`Notificaciones (${unread} sin leer)`} onClick={() => setOpen((o) => !o)}>
        <Icon name="bell" />
        {unread > 0 && (
          <span className="bell-count" key={unread}>
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="bell-panel" role="dialog" aria-label="Notificaciones">
          <div className="bell-head">
            <strong>Notificaciones</strong>
            {unread > 0 && (
              <button className="link-btn" style={{ fontSize: 13 }} onClick={readAll}>
                Marcar todo como leído
              </button>
            )}
          </div>
          <div className="bell-list">
            {items.length === 0 && <p className="muted" style={{ padding: 20, textAlign: 'center' }}>Sin notificaciones.</p>}
            {items.map((n, i) => (
              <button key={n.id} className={`bell-item ${n.read ? '' : 'unread'}`} style={{ animationDelay: `${i * 30}ms` }} onClick={() => openItem(n)}>
                <span className="bell-ic">
                  <Icon name={ICON[n.resource_type ?? ''] ?? 'bell'} size={16} />
                </span>
                <span className="grow" style={{ minWidth: 0 }}>
                  <strong>{n.title}</strong>
                  <small>{n.body}</small>
                  <em>
                    {fromNow(n.created_at)}
                  </em>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
