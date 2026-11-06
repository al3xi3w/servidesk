import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import type { ApiError } from '../api';
import type { PaginationMeta, Priority } from '../types/api';
import { initials, PRIORITY_HINT, type Tone } from '../lib/format';
import { Icon } from './Icon';

// ------------------------------------------------------------------ Etiquetas

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge tone-${tone}`}>{children}</span>;
}

/** Muestra el estado de un mapa [etiqueta, tono]. */
export function StatusBadge<K extends string>({ map, value }: { map: Record<K, [string, Tone]>; value: K }) {
  const [label, tone] = map[value] ?? [value, 'neutral'];
  return (
    <span className={`badge tone-${tone}`}>
      <span className="dot" />
      {label}
    </span>
  );
}

export function PriorityBadge({ value }: { value: Priority }) {
  return <span className={`prio prio-${value}`} title={`Prioridad ${PRIORITY_HINT[value].toLowerCase()}`}>{value}</span>;
}

export function Avatar({ name, size = 28 }: { name: string; size?: number }) {
  const hue = [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  return (
    <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.38, background: `hsl(${hue} 45% 88%)`, color: `hsl(${hue} 45% 28%)` }}>
      {initials(name)}
    </span>
  );
}

// ------------------------------------------------------------------ Estados de carga

export function Spinner({ label }: { label?: string }) {
  if (!label)
    return (
      <div className="skeleton" role="status" aria-label="Cargando">
        {[92, 78, 85, 64, 88, 70].map((w, i) => (
          <span key={i} className="sk-line" style={{ width: `${w}%`, animationDelay: `${i * 80}ms` }} />
        ))}
      </div>
    );
  return (
    <div className="spinner-wrap" role="status">
      <span className="spinner" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  const msg =
    error.code === 'FORBIDDEN' ? 'No tienes permiso para ver esta sección.' : error.code === 'NOT_FOUND' ? 'No encontramos este registro en tu organización.' : error.message;
  return (
    <div className="empty error">
      <Icon name="incident" size={28} />
      <p>{msg}</p>
      {error.requestId && <small className="muted">ID de solicitud: {error.requestId}</small>}
      {onRetry && (
        <button className="btn btn-ghost" onClick={onRetry}>
          Reintentar
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children, icon = 'search' }: { title: string; children?: ReactNode; icon?: Parameters<typeof Icon>[0]['name'] }) {
  return (
    <div className="empty">
      <Icon name={icon} size={28} />
      <strong>{title}</strong>
      {children}
    </div>
  );
}

// ------------------------------------------------------------------ Paginación

export function Pagination({ meta, onPage }: { meta: PaginationMeta; onPage: (p: number) => void }) {
  const from = meta.total === 0 ? 0 : (meta.page - 1) * meta.limit + 1;
  const to = Math.min(meta.page * meta.limit, meta.total);
  return (
    <div className="pagination">
      <span className="muted">
        {from.toLocaleString('es-PE')}–{to.toLocaleString('es-PE')} de {meta.total.toLocaleString('es-PE')}
      </span>
      <div className="row gap-xs">
        <button className="btn btn-ghost btn-sm" disabled={meta.page <= 1} onClick={() => onPage(meta.page - 1)}>
          Anterior
        </button>
        <span className="page-indicator">
          {meta.page} / {meta.total_pages}
        </span>
        <button className="btn btn-ghost btn-sm" disabled={meta.page >= meta.total_pages} onClick={() => onPage(meta.page + 1)}>
          Siguiente
        </button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Modal

export function Modal({ title, onClose, children, footer, wide }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Cerrar">
            <Icon name="x" />
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Formularios

export function Field({ label, error, hint, children, full }: { label: string; error?: string; hint?: string; children: ReactNode; full?: boolean }) {
  return (
    <label className={`field ${full ? 'field-full' : ''} ${error ? 'has-error' : ''}`}>
      <span className="field-label">{label}</span>
      {children}
      {error ? <span className="field-error">{error}</span> : hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

/** Errores de campo a partir de un ApiError VALIDATION_ERROR. */
export function fieldErrors(e: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  const details = (e as ApiError | undefined)?.details ?? [];
  for (const d of details) out[d.field] = d.issue;
  return out;
}

// ------------------------------------------------------------------ Toasts

interface ToastItem {
  id: number;
  text: string;
  tone: 'success' | 'danger' | 'info';
}

const ToastCtx = createContext<(text: string, tone?: ToastItem['tone']) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((text: string, tone: ToastItem['tone'] = 'success') => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, text, tone }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 4200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone}`}>
            <Icon name={t.tone === 'danger' ? 'incident' : t.tone === 'info' ? 'bell' : 'check'} size={16} />
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  return useContext(ToastCtx);
}

/** Muestra el mensaje adecuado para un ApiError según la tabla 3.4 de la guía. */
export function useApiErrorToast() {
  const toast = useToast();
  return useCallback(
    (e: unknown) => {
      const err = e as ApiError;
      if (err?.code === 'FORBIDDEN') toast('No tienes permiso para esta acción', 'danger');
      else if (err?.code === 'INVALID_STATUS_TRANSITION') toast(err.details?.[0]?.issue ?? err.message, 'danger');
      else if (err?.code === 'VALIDATION_ERROR') toast(err.details?.[0]?.issue ?? 'Revisa los campos marcados', 'danger');
      else toast(err?.message ?? 'Ocurrió un error inesperado', 'danger');
    },
    [toast],
  );
}

// ------------------------------------------------------------------ Varios

export function PageHeader({ title, subtitle, actions, back }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; back?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        {back}
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {actions && <div className="row gap-sm wrap">{actions}</div>}
    </div>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v ?? '—'}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Chips de filtro de selección múltiple. */
export function FilterChips<K extends string>({ options, value, onChange }: { options: [K, string][]; value: K[]; onChange: (v: K[]) => void }) {
  return (
    <div className="chips">
      {options.map(([k, label]) => {
        const on = value.includes(k);
        return (
          <button key={k} type="button" className={`chip ${on ? 'on' : ''}`} aria-pressed={on} onClick={() => onChange(on ? value.filter((x) => x !== k) : [...value, k])}>
            {label}
          </button>
        );
      })}
    </div>
  );
}
