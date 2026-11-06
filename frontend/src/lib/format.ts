import type {
  ChangeRisk,
  ChangeStatus,
  ChangeType,
  CIEnvironment,
  CIStatus,
  IncidentChannel,
  IncidentStatus,
  Level,
  Priority,
  ProblemStatus,
  Role,
  ServiceRequestStatus,
} from '../types/api';

/** Tono visual de una etiqueta (ver .tone-* en styles.css). */
export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'accent' | 'muted';

type LabelMap<K extends string> = Record<K, [string, Tone]>;

export const INCIDENT_STATUS: LabelMap<IncidentStatus> = {
  new: ['Nueva', 'info'],
  in_progress: ['En curso', 'accent'],
  on_hold: ['En espera', 'warning'],
  resolved: ['Resuelta', 'success'],
  closed: ['Cerrada', 'muted'],
};

export const PROBLEM_STATUS: LabelMap<ProblemStatus> = {
  new: ['Nuevo', 'info'],
  investigating: ['Buscando la causa', 'accent'],
  known_error: ['Con solución temporal', 'warning'],
  resolved: ['Resuelto', 'success'],
  closed: ['Cerrado', 'muted'],
};

export const CHANGE_STATUS: LabelMap<ChangeStatus> = {
  draft: ['Borrador', 'muted'],
  submitted: ['En revisión del comité', 'info'],
  approved: ['Aprobada', 'success'],
  rejected: ['Rechazada', 'danger'],
  scheduled: ['Programada', 'accent'],
  implemented: ['Implementada', 'success'],
  failed: ['Fallida', 'danger'],
};

export const REQUEST_STATUS: LabelMap<ServiceRequestStatus> = {
  submitted: ['Recibido', 'info'],
  pending_approval: ['Por aprobar', 'warning'],
  approved: ['Aprobado', 'success'],
  in_fulfillment: ['En atención', 'accent'],
  fulfilled: ['Completado', 'success'],
  rejected: ['Rechazado', 'danger'],
};

export const CI_STATUS: LabelMap<CIStatus> = {
  operational: ['Funcionando', 'success'],
  degraded: ['Con problemas', 'warning'],
  down: ['Caído', 'danger'],
  retired: ['Dado de baja', 'muted'],
};

export const CHANGE_TYPE: Record<ChangeType, string> = { standard: 'Rutinaria', normal: 'Planificada', emergency: 'De emergencia' };
export const RISK: LabelMap<ChangeRisk> = { low: ['Bajo', 'success'], medium: ['Medio', 'warning'], high: ['Alto', 'danger'] };
export const LEVEL: Record<Level, string> = { high: 'Alto', medium: 'Medio', low: 'Bajo' };
export const ENV: Record<CIEnvironment, string> = { prod: 'Producción', qa: 'QA', dev: 'Desarrollo' };
export const CHANNEL: Record<IncidentChannel, string> = { portal: 'Portal', email: 'Correo', auto: 'Detección automática' };
export const ROLE: Record<Role, string> = { admin: 'Jefatura de TI', agent: 'Técnico de TI', customer: 'Trabajador' };

/** Qué significa cada prioridad, en palabras simples. */
export const PRIORITY_HINT: Record<'P1' | 'P2' | 'P3' | 'P4', string> = { P1: 'Urgente', P2: 'Alta', P3: 'Media', P4: 'Baja' };

const dateFmt = new Intl.DateTimeFormat('es-PE', { day: '2-digit', month: 'short', year: 'numeric' });
const dateTimeFmt = new Intl.DateTimeFormat('es-PE', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
const rtf = new Intl.RelativeTimeFormat('es', { numeric: 'auto' });

export function fmtDate(v: string | null | undefined): string {
  return v ? dateFmt.format(new Date(v)) : '—';
}

export function fmtDateTime(v: string | null | undefined): string {
  return v ? dateTimeFmt.format(new Date(v)) : '—';
}

export function fromNow(v: string | null | undefined): string {
  if (!v) return '—';
  const diff = (Date.parse(v) - Date.now()) / 1000;
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(Math.round(diff), 'second');
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), 'day');
  return rtf.format(Math.round(diff / (86400 * 30)), 'month');
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

/** <input type="datetime-local"> ↔ ISO UTC */
export function toLocalInput(isoStr: string | null | undefined): string {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export function fromLocalInput(v: string): string | null {
  return v ? new Date(v).toISOString().replace(/\.\d{3}Z$/, 'Z') : null;
}

/** Matriz de prioridad (D6): impacto × urgencia. */
export function priorityOf(impact: Level, urgency: Level): Priority {
  const score = { high: 0, medium: 1, low: 2 };
  const s = score[impact] + score[urgency];
  return (['P1', 'P2', 'P3', 'P4', 'P4'] as const)[s];
}
