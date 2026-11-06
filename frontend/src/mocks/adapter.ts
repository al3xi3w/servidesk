/**
 * Adaptador de Axios que responde como los microservicios (modo demo).
 *
 * Se activa por servicio: si `VITE_USE_MOCKS=true` o si falta la URL de ese servicio en el entorno.
 * Así, cuando un backend se despliega, basta con configurar su URL para dejar de simularlo.
 * Respeta los formatos de docs/API_CONTRACTS.md: respuestas, errores, paginación, roles y transiciones.
 */
import { AxiosError, AxiosHeaders, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import type {
  ChangeDetail,
  ChangeStatus,
  ErrorCode,
  FieldError,
  Incident,
  IncidentStatus,
  JwtPayload,
  Notification,
  Priority,
  ProblemStatus,
  Role,
  ServiceRequestStatus,
} from '../types/api';
import { commentsOf, iso, keyOf, priorityOf, saveTenant, SLA_HOURS, tenantDb, TENANTS, type StoredUser, type TenantDb } from './db';
import { publish, registerConsumer } from './events';

type ServiceName = 'identity' | 'cmdb' | 'incidents' | 'problems' | 'changes' | 'requests';
type Q = Record<string, unknown>;
type Body = Record<string, unknown>;

interface Ctx {
  db: TenantDb;
  me: StoredUser;
  role: Role;
}

// ------------------------------------------------------------------ Errores con el formato del contrato

class HttpError {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown) {
    this.status = status;
    this.body = body;
  }
}

function fail(status: number, code: ErrorCode, message: string, details: FieldError[] = []): never {
  throw new HttpError(status, { error: { code, message, details, request_id: crypto.randomUUID() } });
}

const notFound = (what = 'Recurso') => fail(404, 'NOT_FOUND', `${what} no encontrado`);
const forbidden = () => fail(403, 'FORBIDDEN', 'No tienes permiso para esta acción');
const invalid = (field: string, issue: string) => fail(400, 'VALIDATION_ERROR', 'Datos inválidos', [{ field, issue }]);
const transition = (from: string, to: string) =>
  fail(409, 'INVALID_STATUS_TRANSITION', 'Transición de estado no permitida', [{ field: 'status', issue: `De '${from}' no se puede pasar a '${to}'` }]);

function requireRole(ctx: Ctx, ...roles: Role[]) {
  if (!roles.includes(ctx.role)) forbidden();
}

/** Valida que el body solo traiga campos permitidos (D12). */
function strict(body: Body, allowed: string[]) {
  for (const k of Object.keys(body)) if (!allowed.includes(k)) invalid(k, 'Campo no permitido');
}

function requireText(body: Body, field: string, min = 1, max = 5000): string {
  const v = body[field];
  if (typeof v !== 'string' || v.trim().length < min) invalid(field, min > 1 ? `Debe tener al menos ${min} caracteres` : 'Campo obligatorio');
  if ((v as string).length > max) invalid(field, `Máximo ${max} caracteres`);
  return (v as string).trim();
}

// ------------------------------------------------------------------ Token simulado

function b64url(s: string): string {
  return btoa(unescape(encodeURIComponent(s))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function signToken(payload: JwtPayload): string {
  return `${b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))}.${b64url(JSON.stringify(payload))}.mock-signature`;
}

function readToken(config: InternalAxiosRequestConfig): JwtPayload | null {
  const auth = AxiosHeaders.from(config.headers).get('Authorization');
  if (typeof auth !== 'string' || !auth.startsWith('Bearer ')) return null;
  try {
    const part = auth.slice(7).split('.')[1];
    const json = decodeURIComponent(escape(atob(part.replace(/-/g, '+').replace(/_/g, '/'))));
    const p = JSON.parse(json) as JwtPayload;
    return p.exp * 1000 > Date.now() ? p : null;
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------ Listados

function multi(v: unknown): string[] | null {
  if (v === undefined || v === null || v === '') return null;
  // Igual que serializeParams: un arreglo vacío no filtra.
  if (Array.isArray(v)) return v.length ? v.map(String) : null;
  return String(v).split(',');
}

const RANK: Record<string, number> = { low: 1, medium: 2, high: 3 };

function paginate<T extends object>(items: T[], q: Q, opts: { search?: (keyof T)[]; sortable: string[]; defaultSort?: string; defaultOrder?: 'asc' | 'desc' }) {
  const page = Number(q.page ?? 1);
  const limit = Number(q.limit ?? 20);
  if (!Number.isInteger(page) || page < 1) invalid('page', 'Debe ser un entero ≥ 1');
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) invalid('limit', 'Debe estar entre 1 y 100');
  const sortBy = String(q.sort_by ?? opts.defaultSort ?? 'created_at');
  if (!opts.sortable.includes(sortBy)) invalid('sort_by', `Valores permitidos: ${opts.sortable.join(', ')}`);
  const order = (q.sort_order ?? opts.defaultOrder ?? 'desc') === 'asc' ? 1 : -1;

  let rows = items;
  const search = typeof q.search === 'string' ? q.search.trim().toLowerCase() : '';
  if (search && opts.search) {
    if (search.length < 2) invalid('search', 'Mínimo 2 caracteres');
    rows = rows.filter((r) => opts.search!.some((f) => String(r[f] ?? '').toLowerCase().includes(search)));
  }
  rows = [...rows].sort((a, b) => {
    const va = (a as Record<string, unknown>)[sortBy];
    const vb = (b as Record<string, unknown>)[sortBy];
    if (va === vb) return 0;
    if (va === null || va === undefined) return 1;
    if (vb === null || vb === undefined) return -1;
    const ra = RANK[String(va)] ?? va;
    const rb = RANK[String(vb)] ?? vb;
    return (ra < rb ? -1 : 1) * order;
  });
  const total = rows.length;
  return {
    data: rows.slice((page - 1) * limit, page * limit),
    meta: { page, limit, total, total_pages: Math.max(1, Math.ceil(total / limit)) },
  };
}

function by<T>(rows: T[], q: Q, field: string, pick: (r: T) => unknown = (r) => (r as Record<string, unknown>)[field]): T[] {
  const vals = multi(q[field]);
  return vals ? rows.filter((r) => vals.includes(String(pick(r)))) : rows;
}

function assigneeFilter<T extends { assignee_id: string | null }>(rows: T[], v: unknown, me: string): T[] {
  if (!v) return rows;
  if (v === 'none') return rows.filter((r) => !r.assignee_id);
  const id = v === 'me' ? me : String(v);
  return rows.filter((r) => r.assignee_id === id);
}

function publicUser(u: StoredUser) {
  const { password: _p, team_ids: _t, ...rest } = u;
  return rest;
}

// ------------------------------------------------------------------ Efectos de eventos (simulan SNS/SQS)

function nextKey(db: TenantDb, prefix: keyof TenantDb['counters']): string {
  db.counters[prefix] += 1;
  return keyOf(prefix, db.counters[prefix]);
}

function newIncident(db: TenantDb, data: Partial<Incident> & Pick<Incident, 'title' | 'impact' | 'urgency' | 'reporter_id' | 'channel'>): Incident {
  const now = Date.now();
  const priority = priorityOf(data.impact, data.urgency);
  const inc: Incident = {
    id: crypto.randomUUID(),
    key: nextKey(db, 'INC'),
    description: null,
    status: 'new',
    priority,
    sla_policy_id: { P1: 1, P2: 2, P3: 3, P4: 4 }[priority],
    sla_due_at: iso(now + SLA_HOURS[priority] * 3_600_000),
    sla_breached: false,
    assignee_id: null,
    team_id: null,
    ci_id: null,
    problem_id: null,
    created_at: iso(now),
    resolved_at: null,
    ...data,
  };
  db.incidents.push(inc);
  db.comments.set(inc.id, []);
  return inc;
}

// ------------------------------------------------------------------ Publicación y consumidores (SNS → SQS → Lambda)

type Data = Record<string, unknown>;
const str = (v: unknown) => (typeof v === 'string' ? v : null);

function incidentCreatedEvent(db: TenantDb, inc: Incident, actorId: string | null) {
  publish(db, 'IncidentCreated', 'incidents', {
    incidentId: inc.id, key: inc.key, title: inc.title, priority: inc.priority, ciId: inc.ci_id, teamId: inc.team_id,
    assigneeId: inc.assignee_id, reporterId: inc.reporter_id, channel: inc.channel, actorId,
  });
}

type ProblemRow = TenantDb['problems'][number];

function createProblem(db: TenantDb, f: Pick<ProblemRow, 'title' | 'description' | 'priority' | 'ci_id' | 'owner_id' | 'incident_ids'>, actorId: string | null): ProblemRow {
  const p: ProblemRow = { id: crypto.randomUUID(), key: nextKey(db, 'PRB'), status: 'new', root_cause: null, fix_change_id: null, created_at: iso(Date.now()), known_error: null, ...f };
  db.problems.push(p);
  for (const inc of db.incidents) if (p.incident_ids.includes(inc.id)) inc.problem_id = p.id;
  publish(db, 'ProblemCreated', 'problems', { problemId: p.id, key: p.key, priority: p.priority, ciId: p.ci_id, ownerId: p.owner_id, incidentIds: p.incident_ids, actorId });
  if (p.incident_ids.length) publish(db, 'ProblemIncidentsLinked', 'problems', { problemId: p.id, incidentIds: p.incident_ids, actorId });
  return p;
}

function requestEventData(r: TenantDb['requests'][number], actorId: string | null): Data {
  return { requestId: r.id, key: r.key, catalogItemId: r.catalog_item_id, catalogItemName: r.catalog_item_name, status: r.status, requesterId: r.requester_id, actorId };
}

/** Inserta notificaciones (tabla notifications de ms-identity). No se notifica al propio actor. */
function notify(db: TenantDb, userIds: unknown[], n: Pick<Notification, 'event_type' | 'title' | 'body' | 'resource_type' | 'resource_id'>, exclude?: string | null): number {
  const ids = [...new Set(userIds.filter((x): x is string => typeof x === 'string'))].filter((id) => id !== exclude);
  for (const user_id of ids) db.notifications.unshift({ ...n, id: crypto.randomUUID(), user_id, read: false, created_at: iso(Date.now()) });
  if (db.notifications.length > 600) db.notifications.length = 600;
  return ids.length;
}
const admins = (db: TenantDb) => db.users.filter((u) => u.role === 'admin' && u.active).map((u) => u.id);
const teamMembers = (db: TenantDb, teamId: string | null) => (teamId ? db.users.filter((u) => u.role !== 'customer' && u.team_ids.includes(teamId)).map((u) => u.id) : []);
const PRIO_RANK: Record<Priority, number> = { P1: 1, P2: 2, P3: 3, P4: 4 };

// ms-incidents · CIStatusChanged → incidente automático P2 (canal auto) cuando el CI cae.
registerConsumer('incidents-ci-q', (db, env) => {
  const d = env.data as Data;
  if (d.status !== 'down') return null;
  const ci = db.cis.find((c) => c.id === d.ciId);
  const inc = newIncident(db, {
    title: `[Automático] ${str(d.name) ?? 'Equipo'} dejó de responder`,
    description: 'ServiDesk detectó que este equipo o sistema dejó de responder y abrió el reporte automáticamente.',
    impact: 'high',
    urgency: 'medium',
    reporter_id: str(d.actorId) ?? db.users[0].id,
    channel: 'auto',
    ci_id: str(d.ciId),
    team_id: ci?.owner_team_id ?? null,
  });
  incidentCreatedEvent(db, inc, null);
  return `Creó ${inc.key} (${inc.priority}, canal auto)`;
});

// ms-problems · IncidentCreated → 3 o más incidentes del mismo CI en 24 h crean (o alimentan) un problema.
registerConsumer('problems-incidents-q', (db, env) => {
  const d = env.data as Data;
  const ciId = str(d.ciId);
  if (!ciId) return 'Sin CI: no aplica la regla de recurrencia';
  const since = Date.now() - 24 * 3_600_000;
  const group = db.incidents.filter((i) => i.ci_id === ciId && Date.parse(i.created_at) >= since && i.status !== 'closed');
  if (group.length < 3) return `${group.length} incidente(s) del CI en 24 h (umbral: 3)`;
  const free = group.filter((i) => !i.problem_id);
  if (!free.length) return 'Los incidentes ya estaban vinculados';
  const open = db.problems.find((p) => p.ci_id === ciId && !['resolved', 'closed'].includes(p.status));
  if (open) {
    free.forEach((i) => {
      i.problem_id = open.id;
      if (!open.incident_ids.includes(i.id)) open.incident_ids.push(i.id);
    });
    publish(db, 'ProblemIncidentsLinked', 'problems', { problemId: open.id, incidentIds: free.map((i) => i.id), actorId: null });
    return `Vinculó ${free.length} incidente(s) a ${open.key}`;
  }
  const ci = db.cis.find((c) => c.id === ciId);
  const worst = free.reduce<Priority>((m, i) => (PRIO_RANK[i.priority] < PRIO_RANK[m] ? i.priority : m), 'P4');
  const p = createProblem(
    db,
    {
      title: `Fallas que se repiten en ${ci?.name ?? 'un equipo'}`,
      description: `Registrado automáticamente: ${group.length} fallas en el mismo equipo o sistema en las últimas 24 horas.`,
      priority: worst,
      ci_id: ciId,
      owner_id: free.find((i) => i.assignee_id)?.assignee_id ?? db.users[0].id,
      incident_ids: free.map((i) => i.id),
    },
    null,
  );
  return `Creó ${p.key} con ${free.length} incidentes`;
});

// ms-incidents · ProblemIncidentsLinked → fija incidents.problem_id (idempotente).
registerConsumer('incidents-problem-q', (db, env) => {
  const d = env.data as Data;
  const ids = (d.incidentIds as string[]) ?? [];
  let n = 0;
  for (const inc of db.incidents) {
    if (!ids.includes(inc.id) || inc.problem_id === d.problemId) continue;
    inc.problem_id = String(d.problemId);
    n++;
  }
  return n ? `Actualizó problem_id en ${n} incidente(s)` : 'Ya estaban actualizados';
});

// ms-incidents · KnownErrorPublished → workaround como comentario en los incidentes vinculados.
registerConsumer('incidents-kedb-q', (db, env) => {
  const d = env.data as Data;
  const ids = (d.incidentIds as string[]) ?? [];
  let n = 0;
  for (const inc of db.incidents) {
    if (!ids.includes(inc.id) || inc.status === 'closed') continue;
    commentsOf(db, inc).push({
      id: crypto.randomUUID(), incident_id: inc.id, author_id: str(d.actorId) ?? db.users[0].id,
      body: `Solución temporal mientras se corrige: ${String(d.workaround)}`, internal: false, created_at: iso(Date.now()),
    });
    n++;
  }
  return `Comentó el workaround en ${n} incidente(s)`;
});

// ms-cmdb · ChangeImplemented → aplica new_version a los CI afectados.
registerConsumer('cmdb-changes-q', (db, env) => {
  const cis = ((env.data as Data).cis as { ciId: string; newVersion?: string | null }[]) ?? [];
  let n = 0;
  for (const c of cis) {
    const ci = db.cis.find((x) => x.id === c.ciId);
    if (!ci || !c.newVersion) continue;
    ci.version = c.newVersion;
    ci.updated_at = iso(Date.now());
    n++;
  }
  return n ? `Actualizó la versión de ${n} CI` : 'Ningún CI con versión nueva';
});

// ms-problems · ChangeImplemented → cierra el problema cuyo fix_change_id coincide.
registerConsumer('problems-changes-q', (db, env) => {
  const d = env.data as Data;
  const p = db.problems.find((x) => x.fix_change_id === d.changeId || (d.problemId && x.id === d.problemId));
  if (!p) return 'Ningún problema esperaba este cambio';
  if (p.status === 'closed') return `${p.key} ya estaba cerrado`;
  p.root_cause ||= `Corregido con la actualización ${String(d.key)}.`;
  p.status = 'closed';
  return `Cerró ${p.key}`;
});

// ms-requests · RequestApproved → tareas de cumplimiento (fuera de la v0.9 por D16).
registerConsumer('requests-fulfillment-q', () => 'Tareas de cumplimiento: pendientes de contrato (D16)');

// ms-identity · identity-notify-q → bandeja de notificaciones.
registerConsumer('identity-notify-q', (db, env) => {
  const d = env.data as Data;
  const actor = str(d.actorId);
  const key = String(d.key ?? '');
  let n = 0;
  switch (env.eventType) {
    case 'IncidentCreated': {
      const to = d.assigneeId ? [d.assigneeId] : [...teamMembers(db, str(d.teamId)), ...(['P1', 'P2'].includes(String(d.priority)) ? admins(db) : [])];
      n = notify(db, to.length ? to : admins(db), { event_type: env.eventType, title: `Nueva falla ${key} (${d.priority})`, body: String(d.title), resource_type: 'incident', resource_id: str(d.incidentId) }, actor);
      break;
    }
    case 'IncidentUpdated':
      if ((d.changedFields as string[])?.includes('assignee_id'))
        n = notify(db, [d.assigneeId], { event_type: env.eventType, title: `Te asignaron la falla ${key}`, body: 'Revísala en tu lista de fallas.', resource_type: 'incident', resource_id: str(d.incidentId) }, actor);
      break;
    case 'IncidentResolved':
      n = notify(db, [d.reporterId], { event_type: env.eventType, title: `Resolvimos tu falla ${key}`, body: 'Confírmalo o avísanos si sigue pasando.', resource_type: 'incident', resource_id: str(d.incidentId) }, actor);
      break;
    case 'ProblemCreated':
      n = notify(db, [d.ownerId], { event_type: env.eventType, title: `Te asignaron el problema recurrente ${key}`, body: actor ? 'Busca la causa de fondo.' : 'Se detectaron varias fallas iguales en poco tiempo.', resource_type: 'problem', resource_id: str(d.problemId) }, actor);
      break;
    case 'KnownErrorPublished': {
      const ids = (d.incidentIds as string[]) ?? [];
      const to = db.incidents.filter((i) => ids.includes(i.id)).map((i) => i.assignee_id);
      n = notify(db, to, { event_type: env.eventType, title: 'Hay una solución temporal publicada', body: String(d.workaround), resource_type: 'problem', resource_id: str(d.problemId) }, actor);
      break;
    }
    case 'ChangeSubmitted':
      n = notify(db, admins(db), { event_type: env.eventType, title: `La actualización ${key} espera tu aprobación`, body: `Riesgo ${({ low: 'bajo', medium: 'medio', high: 'alto' } as Record<string, string>)[String(d.risk)] ?? d.risk}.`, resource_type: 'change', resource_id: str(d.changeId) }, actor);
      break;
    case 'ChangeApproved':
    case 'ChangeRejected':
      n = notify(db, [d.requesterId], {
        event_type: env.eventType,
        title: `La actualización ${key} fue ${env.eventType === 'ChangeApproved' ? 'aprobada' : 'rechazada'}`,
        body: str(d.comment) ?? (env.eventType === 'ChangeApproved' ? 'Ya puedes programarlo.' : 'Revisa el motivo.'),
        resource_type: 'change',
        resource_id: str(d.changeId),
      }, actor);
      break;
    case 'RequestSubmitted':
      n = notify(db, [d.requesterId], { event_type: env.eventType, title: `Recibimos tu pedido ${key}`, body: String(d.catalogItemName), resource_type: 'request', resource_id: str(d.requestId) });
      if (d.status === 'pending_approval')
        n += notify(db, admins(db), { event_type: env.eventType, title: `El pedido ${key} necesita tu aprobación`, body: String(d.catalogItemName), resource_type: 'request', resource_id: str(d.requestId) }, actor);
      break;
    case 'RequestApproved':
    case 'RequestRejected':
    case 'RequestFulfilled': {
      const verb = { RequestApproved: 'aprobado', RequestRejected: 'rechazado', RequestFulfilled: 'entregado' }[env.eventType];
      n = notify(db, [d.requesterId], { event_type: env.eventType, title: `Tu pedido ${key} fue ${verb}`, body: String(d.catalogItemName), resource_type: 'request', resource_id: str(d.requestId) }, actor);
      break;
    }
    default:
      return null;
  }
  return `${n} notificación(es)`;
});

// ------------------------------------------------------------------ Rutas por servicio

type Handler = (ctx: Ctx, params: string[], q: Q, body: Body) => unknown;
interface Route {
  method: string;
  pattern: RegExp;
  handler: Handler;
  status?: number;
}

const ID = '([^/]+)';
const r = (method: string, path: string, handler: Handler, status?: number): Route => ({
  method,
  pattern: new RegExp(`^${path.replace(/:id/g, ID)}$`),
  handler,
  status,
});

function findOr404<T extends { id: string }>(rows: T[], id: string, what?: string): T {
  return rows.find((x) => x.id === id) ?? notFound(what);
}

const identityRoutes: Route[] = [
  r('get', '/auth/me', (ctx) => ({ data: { ...publicUser(ctx.me), tenant: { id: ctx.db.def.id, name: ctx.db.def.name } } })),
  r('get', '/users', (ctx, _p, q) => {
    requireRole(ctx, 'admin', 'agent');
    let rows = ctx.db.users;
    rows = by(rows, q, 'role');
    if (q.active !== undefined && q.active !== '') rows = rows.filter((u) => String(u.active) === String(q.active));
    const ids = multi(q.ids);
    if (ids) {
      if (ids.length > 100) invalid('ids', 'Máximo 100 IDs');
      rows = rows.filter((u) => ids.includes(u.id));
    }
    const page = paginate(rows, q, { search: ['email', 'full_name'], sortable: ['created_at', 'full_name', 'email'] });
    return { ...page, data: page.data.map(publicUser) };
  }),
  r('get', '/users/:id', (ctx, [id]) => {
    requireRole(ctx, 'admin', 'agent');
    return { data: publicUser(findOr404(ctx.db.users, id, 'Usuario')) };
  }),
  r('post', '/users', (ctx, _p, _q, b) => {
    requireRole(ctx, 'admin');
    strict(b, ['email', 'full_name', 'role', 'password', 'active']);
    const email = requireText(b, 'email').toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) invalid('email', 'Formato de email inválido');
    if (ctx.db.users.some((u) => u.email === email)) fail(409, 'EMAIL_ALREADY_EXISTS', 'Ya existe un usuario con ese email', [{ field: 'email', issue: 'Ya registrado' }]);
    const full_name = requireText(b, 'full_name', 3, 150);
    if (!['admin', 'agent', 'customer'].includes(String(b.role))) invalid('role', 'Rol inválido');
    const password = requireText(b, 'password', 8, 128);
    const u: StoredUser = { id: crypto.randomUUID(), email, full_name, role: b.role as Role, active: b.active !== false, created_at: iso(Date.now()), password, team_ids: [] };
    ctx.db.users.push(u);
    publish(ctx.db, 'UserCreated', 'identity', { userId: u.id, email: u.email, role: u.role, actorId: ctx.me.id });
    return { data: publicUser(u) };
  }, 201),
  r('patch', '/users/:id', (ctx, [id], _q, b) => {
    requireRole(ctx, 'admin');
    strict(b, ['full_name', 'role', 'active', 'password']);
    const u = findOr404(ctx.db.users, id, 'Usuario');
    if (b.full_name !== undefined) u.full_name = requireText(b, 'full_name', 3, 150);
    if (b.role !== undefined) u.role = b.role as Role;
    if (b.active !== undefined) u.active = Boolean(b.active);
    if (b.password !== undefined) u.password = requireText(b, 'password', 8, 128);
    return { data: publicUser(u) };
  }),
  // PROPUESTO (D16): bandeja de notificaciones.
  r('get', '/notifications', (ctx, _p, q) => {
    const limit = Math.min(Math.max(Number(q.limit ?? 20), 1), 100);
    const mine = ctx.db.notifications.filter((n) => n.user_id === ctx.me.id);
    return { data: mine.slice(0, limit), meta: { unread: mine.filter((n) => !n.read).length } };
  }),
  r('post', '/notifications/read', (ctx, _p, _q, b) => {
    strict(b, ['ids']);
    const ids = Array.isArray(b.ids) ? (b.ids as string[]) : null;
    for (const n of ctx.db.notifications) if (n.user_id === ctx.me.id && (!ids || ids.includes(n.id))) n.read = true;
    return undefined;
  }, 204),
  r('get', '/teams', (ctx, _p, q) => {
    requireRole(ctx, 'admin', 'agent');
    return paginate(ctx.db.teams, q, { search: ['name'], sortable: ['name'], defaultSort: 'name', defaultOrder: 'asc' });
  }),
];

const cmdbRoutes: Route[] = [
  r('get', '/ci-types', (ctx) => {
    requireRole(ctx, 'admin', 'agent');
    return { data: ctx.db.ciTypes };
  }),
  r('get', '/cis', (ctx, _p, q) => {
    requireRole(ctx, 'admin', 'agent');
    let rows = ctx.db.cis;
    rows = by(rows, q, 'status');
    rows = by(rows, q, 'environment');
    rows = by(rows, q, 'type_id');
    rows = by(rows, q, 'owner_team_id');
    return paginate(rows, q, { search: ['name'], sortable: ['created_at', 'updated_at', 'name', 'status'] });
  }),
  r('post', '/cis', (ctx, _p, _q, b) => {
    requireRole(ctx, 'admin', 'agent');
    strict(b, ['type_id', 'name', 'environment', 'version', 'owner_team_id', 'attributes']);
    const type = ctx.db.ciTypes.find((t) => t.id === Number(b.type_id)) ?? invalid('type_id', 'Tipo inexistente');
    const name = requireText(b, 'name', 2, 150);
    if (!['prod', 'qa', 'dev'].includes(String(b.environment))) invalid('environment', 'Valor inválido');
    const now = iso(Date.now());
    const ci = {
      id: crypto.randomUUID(),
      type_id: type.id,
      type_name: type.name,
      name,
      status: 'operational' as const,
      environment: b.environment as 'prod' | 'qa' | 'dev',
      version: (b.version as string) || null,
      owner_team_id: (b.owner_team_id as string) || null,
      attributes: (b.attributes as Record<string, unknown>) ?? {},
      created_at: now,
      updated_at: now,
    };
    ctx.db.cis.push(ci);
    return { data: ci };
  }, 201),
  r('get', '/cis/:id/relations', (ctx, [id]) => {
    requireRole(ctx, 'admin', 'agent');
    findOr404(ctx.db.cis, id, 'CI');
    const view = (ciId: string) => {
      const c = ctx.db.cis.find((x) => x.id === ciId)!;
      return { id: c.id, name: c.name, status: c.status, type_name: c.type_name };
    };
    return {
      data: ctx.db.relations
        .filter((x) => x.source_id === id || x.target_id === id)
        .map((x) =>
          x.source_id === id
            ? { id: x.id, relation: x.relation, direction: 'outgoing', ci: view(x.target_id) }
            : { id: x.id, relation: x.relation, direction: 'incoming', ci: view(x.source_id) },
        ),
    };
  }),
  r('get', '/cis/:id', (ctx, [id]) => {
    requireRole(ctx, 'admin', 'agent');
    return { data: findOr404(ctx.db.cis, id, 'CI') };
  }),
  r('patch', '/cis/:id', (ctx, [id], _q, b) => {
    requireRole(ctx, 'admin', 'agent');
    strict(b, ['type_id', 'name', 'environment', 'version', 'owner_team_id', 'attributes']);
    const ci = findOr404(ctx.db.cis, id, 'CI');
    if (b.name !== undefined) ci.name = requireText(b, 'name', 2, 150);
    if (b.version !== undefined) ci.version = (b.version as string) || null;
    if (b.environment !== undefined) ci.environment = b.environment as 'prod';
    if (b.owner_team_id !== undefined) ci.owner_team_id = (b.owner_team_id as string) || null;
    if (b.attributes !== undefined) ci.attributes = b.attributes as Record<string, unknown>;
    if (b.type_id !== undefined) {
      const t = ctx.db.ciTypes.find((x) => x.id === Number(b.type_id)) ?? invalid('type_id', 'Tipo inexistente');
      ci.type_id = t.id;
      ci.type_name = t.name;
    }
    ci.updated_at = iso(Date.now());
    return { data: ci };
  }),
  r('put', '/cis/:id/status', (ctx, [id], _q, b) => {
    requireRole(ctx, 'admin', 'agent');
    strict(b, ['status']);
    if (!['operational', 'degraded', 'down', 'retired'].includes(String(b.status))) invalid('status', 'Valor inválido');
    const ci = findOr404(ctx.db.cis, id, 'CI');
    const prev = ci.status;
    ci.status = b.status as typeof ci.status;
    ci.updated_at = iso(Date.now());
    // Evento CIStatusChanged: ms-incidents (incidents-ci-q) crea el incidente automático si el CI cae.
    if (prev !== ci.status) publish(ctx.db, 'CIStatusChanged', 'cmdb', { ciId: ci.id, name: ci.name, previousStatus: prev, status: ci.status, actorId: ctx.me.id });
    return { data: ci };
  }),
  r('delete', '/cis/:id', (ctx, [id]) => {
    requireRole(ctx, 'admin');
    const ci = findOr404(ctx.db.cis, id, 'CI');
    const prev = ci.status;
    ci.status = 'retired';
    ci.updated_at = iso(Date.now());
    if (prev !== 'retired') publish(ctx.db, 'CIStatusChanged', 'cmdb', { ciId: ci.id, name: ci.name, previousStatus: prev, status: 'retired', actorId: ctx.me.id });
    return undefined;
  }, 204),
];

const INC_TRANSITIONS: Record<IncidentStatus, IncidentStatus[]> = {
  new: ['in_progress', 'on_hold', 'resolved'],
  in_progress: ['on_hold', 'resolved'],
  on_hold: ['in_progress', 'resolved'],
  resolved: ['closed', 'in_progress'],
  closed: [],
};

function incidentFor(ctx: Ctx, id: string): Incident {
  const inc = findOr404(ctx.db.incidents, id, 'Incidente');
  if (ctx.role === 'customer' && inc.reporter_id !== ctx.me.id) notFound('Incidente');
  return inc;
}

const LEVELS = ['high', 'medium', 'low'];

const incidentRoutes: Route[] = [
  r('get', '/incidents', (ctx, _p, q) => {
    let rows = ctx.db.incidents;
    if (ctx.role === 'customer') rows = rows.filter((i) => i.reporter_id === ctx.me.id);
    for (const f of ['status', 'priority', 'impact', 'urgency', 'team_id', 'ci_id', 'problem_id', 'channel']) rows = by(rows, q, f);
    if (q.sla_breached !== undefined && q.sla_breached !== '') rows = rows.filter((i) => String(i.sla_breached) === String(q.sla_breached));
    rows = assigneeFilter(rows, q.assignee_id, ctx.me.id);
    return paginate(rows, q, { search: ['key', 'title'], sortable: ['created_at', 'priority', 'sla_due_at', 'status', 'key'] });
  }),
  r('post', '/incidents', (ctx, _p, _q, b) => {
    const allowed = ['title', 'description', 'impact', 'urgency', 'ci_id'];
    strict(b, ctx.role === 'customer' ? allowed : [...allowed, 'team_id', 'assignee_id']);
    const title = requireText(b, 'title', 5, 200);
    if (!LEVELS.includes(String(b.impact))) invalid('impact', 'Selecciona el impacto');
    if (!LEVELS.includes(String(b.urgency))) invalid('urgency', 'Selecciona la urgencia');
    const inc = newIncident(ctx.db, {
      title,
      description: (b.description as string) || null,
      impact: b.impact as 'high',
      urgency: b.urgency as 'high',
      ci_id: (b.ci_id as string) || null,
      team_id: (b.team_id as string) || null,
      assignee_id: (b.assignee_id as string) || null,
      reporter_id: ctx.me.id,
      channel: 'portal',
    });
    incidentCreatedEvent(ctx.db, inc, ctx.me.id);
    return { data: inc };
  }, 201),
  r('get', '/incidents/:id/comments', (ctx, [id], q) => {
    const inc = incidentFor(ctx, id);
    let rows = commentsOf(ctx.db, inc);
    if (ctx.role === 'customer') rows = rows.filter((c) => !c.internal);
    return paginate(rows, { limit: 100, ...q }, { sortable: ['created_at'], defaultOrder: 'asc' });
  }),
  r('post', '/incidents/:id/comments', (ctx, [id], _q, b) => {
    const inc = incidentFor(ctx, id);
    strict(b, ctx.role === 'customer' ? ['body'] : ['body', 'internal']);
    const body = requireText(b, 'body', 1, 4000);
    const c = { id: crypto.randomUUID(), incident_id: inc.id, author_id: ctx.me.id, body, internal: Boolean(b.internal), created_at: iso(Date.now()) };
    commentsOf(ctx.db, inc).push(c);
    return { data: c };
  }, 201),
  r('get', '/incidents/:id', (ctx, [id]) => ({ data: incidentFor(ctx, id) })),
  r('patch', '/incidents/:id', (ctx, [id], _q, b) => {
    requireRole(ctx, 'admin', 'agent');
    strict(b, ['title', 'description', 'impact', 'urgency', 'ci_id', 'team_id', 'assignee_id', 'problem_id']);
    const inc = incidentFor(ctx, id);
    const before = { ...inc };
    if (b.title !== undefined) inc.title = requireText(b, 'title', 5, 200);
    for (const f of ['description', 'ci_id', 'team_id', 'assignee_id', 'problem_id'] as const) {
      if (b[f] !== undefined) (inc as unknown as Record<string, unknown>)[f] = (b[f] as string) || null;
    }
    if (b.impact !== undefined) inc.impact = b.impact as 'high';
    if (b.urgency !== undefined) inc.urgency = b.urgency as 'high';
    inc.priority = priorityOf(inc.impact, inc.urgency);
    const changedFields = (Object.keys(inc) as (keyof Incident)[]).filter((k) => inc[k] !== before[k]);
    if (changedFields.length)
      publish(ctx.db, 'IncidentUpdated', 'incidents', { incidentId: inc.id, key: inc.key, changedFields, status: inc.status, assigneeId: inc.assignee_id, teamId: inc.team_id, actorId: ctx.me.id });
    return { data: inc };
  }),
  r('put', '/incidents/:id/status', (ctx, [id], _q, b) => {
    strict(b, ['status', 'comment']);
    const inc = incidentFor(ctx, id);
    const to = b.status as IncidentStatus;
    if (ctx.role === 'customer' && !(inc.status === 'resolved' && (to === 'closed' || to === 'in_progress'))) forbidden();
    if (!INC_TRANSITIONS[inc.status]?.includes(to)) transition(inc.status, String(to));
    if (to === 'resolved') {
      const comment = requireText(b, 'comment', 1, 4000);
      commentsOf(ctx.db, inc).push({ id: crypto.randomUUID(), incident_id: inc.id, author_id: ctx.me.id, body: comment, internal: false, created_at: iso(Date.now()) });
      inc.resolved_at = iso(Date.now());
    } else if (typeof b.comment === 'string' && b.comment.trim()) {
      commentsOf(ctx.db, inc).push({ id: crypto.randomUUID(), incident_id: inc.id, author_id: ctx.me.id, body: b.comment.trim(), internal: false, created_at: iso(Date.now()) });
    }
    if (to === 'in_progress' && inc.status === 'resolved') inc.resolved_at = null;
    inc.status = to;
    if (to === 'resolved') publish(ctx.db, 'IncidentResolved', 'incidents', { incidentId: inc.id, key: inc.key, reporterId: inc.reporter_id, resolvedAt: inc.resolved_at, actorId: ctx.me.id });
    else publish(ctx.db, 'IncidentUpdated', 'incidents', { incidentId: inc.id, key: inc.key, changedFields: ['status'], status: inc.status, assigneeId: inc.assignee_id, teamId: inc.team_id, actorId: ctx.me.id });
    return { data: inc };
  }),
];

const PRB_TRANSITIONS: Record<ProblemStatus, ProblemStatus[]> = {
  new: ['investigating'],
  investigating: ['resolved'],
  known_error: ['resolved'],
  resolved: ['closed', 'investigating'],
  closed: [],
};

const problemRoutes: Route[] = [
  r('get', '/problems', (ctx, _p, q) => {
    requireRole(ctx, 'admin', 'agent');
    let rows = ctx.db.problems;
    for (const f of ['status', 'priority', 'ci_id']) rows = by(rows, q, f);
    if (q.owner_id) rows = rows.filter((p) => p.owner_id === (q.owner_id === 'me' ? ctx.me.id : q.owner_id));
    const page = paginate(rows, q, { search: ['key', 'title'], sortable: ['created_at', 'priority', 'status', 'key'] });
    return { ...page, data: page.data.map(({ incident_ids: _i, known_error: _k, ...p }) => p) };
  }),
  r('post', '/problems', (ctx, _p, _q, b) => {
    requireRole(ctx, 'admin', 'agent');
    strict(b, ['title', 'description', 'priority', 'ci_id', 'owner_id', 'incident_ids']);
    const title = requireText(b, 'title', 5, 200);
    if (!['P1', 'P2', 'P3', 'P4'].includes(String(b.priority))) invalid('priority', 'Prioridad inválida');
    const p = createProblem(
      ctx.db,
      {
        title,
        description: (b.description as string) || null,
        priority: b.priority as Priority,
        ci_id: (b.ci_id as string) || null,
        owner_id: (b.owner_id as string) || ctx.me.id,
        incident_ids: (b.incident_ids as string[]) ?? [],
      },
      ctx.me.id,
    );
    return { data: p };
  }, 201),
  r('get', '/problems/:id', (ctx, [id]) => {
    requireRole(ctx, 'admin', 'agent');
    return { data: findOr404(ctx.db.problems, id, 'Problema') };
  }),
  r('patch', '/problems/:id', (ctx, [id], _q, b) => {
    requireRole(ctx, 'admin', 'agent');
    strict(b, ['title', 'description', 'priority', 'root_cause', 'ci_id', 'owner_id', 'fix_change_id']);
    const p = findOr404(ctx.db.problems, id, 'Problema');
    if (b.title !== undefined) p.title = requireText(b, 'title', 5, 200);
    for (const f of ['description', 'root_cause', 'ci_id', 'owner_id', 'fix_change_id'] as const) {
      if (b[f] !== undefined) (p as unknown as Record<string, unknown>)[f] = (b[f] as string) || null;
    }
    if (b.priority !== undefined) p.priority = b.priority as 'P1';
    return { data: p };
  }),
  r('put', '/problems/:id/status', (ctx, [id], _q, b) => {
    requireRole(ctx, 'admin', 'agent');
    strict(b, ['status']);
    const p = findOr404(ctx.db.problems, id, 'Problema');
    const to = b.status as ProblemStatus;
    if (to === 'known_error') invalid('status', 'Usa "Publicar error conocido"');
    if (!PRB_TRANSITIONS[p.status]?.includes(to)) transition(p.status, String(to));
    if (to === 'resolved' && !p.root_cause?.trim()) invalid('root_cause', 'Registra la causa raíz antes de resolver');
    p.status = to;
    return { data: p };
  }),
  r('post', '/problems/:id/known-error', (ctx, [id], _q, b) => {
    requireRole(ctx, 'admin', 'agent');
    strict(b, ['symptom', 'workaround']);
    const p = findOr404(ctx.db.problems, id, 'Problema');
    if (p.status !== 'investigating') transition(p.status, 'known_error');
    p.known_error = { id: crypto.randomUUID(), problem_id: p.id, symptom: requireText(b, 'symptom', 5), workaround: requireText(b, 'workaround', 5), published_at: iso(Date.now()) };
    p.status = 'known_error';
    publish(ctx.db, 'KnownErrorPublished', 'problems', { problemId: p.id, knownErrorId: p.known_error.id, symptom: p.known_error.symptom, workaround: p.known_error.workaround, incidentIds: p.incident_ids, actorId: ctx.me.id });
    return { data: p };
  }),
  r('post', '/problems/:id/incidents', (ctx, [id], _q, b) => {
    requireRole(ctx, 'admin', 'agent');
    strict(b, ['incident_ids']);
    const p = findOr404(ctx.db.problems, id, 'Problema');
    const ids = Array.isArray(b.incident_ids) ? (b.incident_ids as string[]) : invalid('incident_ids', 'Lista requerida');
    for (const incId of ids) {
      const inc = ctx.db.incidents.find((i) => i.id === incId) ?? invalid('incident_ids', `Incidente ${incId} no existe`);
      inc.problem_id = p.id;
      if (!p.incident_ids.includes(incId)) p.incident_ids.push(incId);
    }
    publish(ctx.db, 'ProblemIncidentsLinked', 'problems', { problemId: p.id, incidentIds: ids, actorId: ctx.me.id });
    return { data: p };
  }),
];

const CHG_TRANSITIONS: Partial<Record<ChangeStatus, ChangeStatus[]>> = {
  draft: ['submitted'],
  rejected: ['draft'],
  approved: ['scheduled'],
  scheduled: ['implemented', 'failed'],
};

function overlaps(c: ChangeDetail, from?: unknown, to?: unknown): boolean {
  if (!from && !to) return true;
  if (!c.planned_start || !c.planned_end) return false;
  if (from && c.planned_end < String(from)) return false;
  if (to && c.planned_start > String(to)) return false;
  return true;
}

const changeRoutes: Route[] = [
  r('get', '/changes', (ctx, _p, q) => {
    requireRole(ctx, 'admin', 'agent');
    let rows = ctx.db.changes;
    for (const f of ['status', 'type', 'risk']) rows = by(rows, q, f);
    if (q.requester_id) rows = rows.filter((c) => c.requester_id === (q.requester_id === 'me' ? ctx.me.id : q.requester_id));
    rows = rows.filter((c) => overlaps(c, q.planned_from, q.planned_to));
    const page = paginate(rows, q, { search: ['key', 'title'], sortable: ['created_at', 'planned_start', 'risk', 'status', 'key'] });
    return { ...page, data: page.data.map(({ cis: _c, approvals: _a, ...c }) => c) };
  }),
  r('post', '/changes', (ctx, _p, _q, b) => {
    requireRole(ctx, 'admin', 'agent');
    strict(b, ['title', 'description', 'type', 'risk', 'rollback_plan', 'planned_start', 'planned_end', 'problem_id', 'cis']);
    const title = requireText(b, 'title', 5, 200);
    if (!['standard', 'normal', 'emergency'].includes(String(b.type))) invalid('type', 'Tipo inválido');
    if (!['low', 'medium', 'high'].includes(String(b.risk))) invalid('risk', 'Riesgo inválido');
    if (b.planned_start && b.planned_end && String(b.planned_end) <= String(b.planned_start)) invalid('planned_end', 'Debe ser posterior al inicio');
    const c: ChangeDetail = {
      id: crypto.randomUUID(),
      key: nextKey(ctx.db, 'CHG'),
      title,
      description: (b.description as string) || null,
      type: b.type as 'normal',
      risk: b.risk as 'low',
      status: 'draft',
      rollback_plan: (b.rollback_plan as string) || null,
      planned_start: (b.planned_start as string) || null,
      planned_end: (b.planned_end as string) || null,
      requester_id: ctx.me.id,
      problem_id: (b.problem_id as string) || null,
      created_at: iso(Date.now()),
      cis: (b.cis as ChangeDetail['cis']) ?? [],
      approvals: [],
    };
    ctx.db.changes.push(c);
    return { data: c };
  }, 201),
  r('get', '/changes/:id', (ctx, [id]) => {
    requireRole(ctx, 'admin', 'agent');
    return { data: findOr404(ctx.db.changes, id, 'Cambio') };
  }),
  r('patch', '/changes/:id', (ctx, [id], _q, b) => {
    requireRole(ctx, 'admin', 'agent');
    strict(b, ['title', 'description', 'type', 'risk', 'rollback_plan', 'planned_start', 'planned_end', 'problem_id', 'cis']);
    const c = findOr404(ctx.db.changes, id, 'Cambio');
    if (c.status !== 'draft') fail(409, 'CONFLICT', 'Solo se puede editar un cambio en borrador');
    Object.assign(c, b);
    return { data: c };
  }),
  r('put', '/changes/:id/status', (ctx, [id], _q, b) => {
    requireRole(ctx, 'admin', 'agent');
    strict(b, ['status']);
    const c = findOr404(ctx.db.changes, id, 'Cambio');
    const to = b.status as ChangeStatus;
    if (!CHG_TRANSITIONS[c.status]?.includes(to)) transition(c.status, String(to));
    if (to === 'submitted') {
      if (!c.planned_start) invalid('planned_start', 'Obligatorio para enviar');
      if (!c.planned_end) invalid('planned_end', 'Obligatorio para enviar');
      if (c.type !== 'standard' && !c.rollback_plan?.trim()) invalid('rollback_plan', 'Obligatorio para cambios normales y de emergencia');
      if (c.type === 'standard') {
        c.status = 'approved'; // D14: preaprobado
        publish(ctx.db, 'ChangeApproved', 'changes', { changeId: c.id, key: c.key, requesterId: c.requester_id, approverId: null, comment: 'Cambio estándar preaprobado.', actorId: ctx.me.id });
        return { data: c };
      }
      c.approvals.push({ id: crypto.randomUUID(), change_id: c.id, approver_id: ctx.db.users[0].id, decision: 'pending', comment: null, decided_at: null });
    }
    c.status = to;
    if (to === 'submitted') publish(ctx.db, 'ChangeSubmitted', 'changes', { changeId: c.id, key: c.key, type: c.type, risk: c.risk, plannedStart: c.planned_start, requesterId: c.requester_id, actorId: ctx.me.id });
    if (to === 'implemented')
      publish(ctx.db, 'ChangeImplemented', 'changes', { changeId: c.id, key: c.key, problemId: c.problem_id, cis: c.cis.map((x) => ({ ciId: x.ci_id, newVersion: x.new_version ?? null })), actorId: ctx.me.id });
    return { data: c };
  }),
  ...(['approve', 'reject'] as const).map((action) =>
    r('post', `/changes/:id/${action}`, (ctx, [id], _q, b) => {
      requireRole(ctx, 'admin');
      strict(b, ['comment']);
      const c = findOr404(ctx.db.changes, id, 'Cambio');
      const to = action === 'approve' ? 'approved' : 'rejected';
      if (c.status !== 'submitted') transition(c.status, to);
      const comment = action === 'reject' ? requireText(b, 'comment', 3) : (b.comment as string) || null;
      const pending = c.approvals.find((a) => a.decision === 'pending');
      const entry = { decision: to, comment, decided_at: iso(Date.now()), approver_id: ctx.me.id } as const;
      if (pending) Object.assign(pending, entry);
      else c.approvals.push({ id: crypto.randomUUID(), change_id: c.id, ...entry });
      c.status = to;
      publish(ctx.db, action === 'approve' ? 'ChangeApproved' : 'ChangeRejected', 'changes', { changeId: c.id, key: c.key, requesterId: c.requester_id, approverId: ctx.me.id, comment, actorId: ctx.me.id });
      return { data: c };
    }),
  ),
];

const REQ_TRANSITIONS: Partial<Record<ServiceRequestStatus, ServiceRequestStatus[]>> = {
  pending_approval: ['approved', 'rejected'],
  submitted: ['in_fulfillment', 'rejected'],
  approved: ['in_fulfillment'],
  in_fulfillment: ['fulfilled'],
};

const requestRoutes: Route[] = [
  r('get', '/catalog', (ctx, _p, q) => {
    let rows = ctx.db.catalog;
    if (q.category_id) rows = rows.filter((c) => c.category_id === Number(q.category_id));
    const s = typeof q.search === 'string' ? q.search.toLowerCase() : '';
    if (s) rows = rows.filter((c) => c.name.toLowerCase().includes(s) || c.category_name.toLowerCase().includes(s));
    return { data: rows };
  }),
  r('get', '/requests', (ctx, _p, q) => {
    let rows = ctx.db.requests;
    if (ctx.role === 'customer') rows = rows.filter((x) => x.requester_id === ctx.me.id);
    rows = by(rows, q, 'status');
    rows = by(rows, q, 'catalog_item_id');
    if (q.requester_id) rows = rows.filter((x) => x.requester_id === (q.requester_id === 'me' ? ctx.me.id : q.requester_id));
    rows = assigneeFilter(rows, q.assignee_id, ctx.me.id);
    const page = paginate(rows, q, { search: ['key', 'catalog_item_name'], sortable: ['created_at', 'status', 'key'] });
    return { ...page, data: page.data.map(({ approvals: _a, ...x }) => x) };
  }),
  r('post', '/requests', (ctx, _p, _q, b) => {
    strict(b, ['catalog_item_id', 'form_data']);
    const item = ctx.db.catalog.find((c) => c.id === b.catalog_item_id) ?? invalid('catalog_item_id', 'Ítem de catálogo inexistente');
    const form = (b.form_data ?? {}) as Record<string, string | number | boolean | null>;
    for (const f of item.form_schema.fields) {
      if (f.required && (form[f.name] === undefined || form[f.name] === null || form[f.name] === '')) invalid(`form_data.${f.name}`, `${f.label} es obligatorio`);
    }
    const id = crypto.randomUUID();
    const req = {
      id,
      key: nextKey(ctx.db, 'REQ'),
      catalog_item_id: item.id,
      catalog_item_name: item.name,
      form_data: form,
      status: (item.needs_approval ? 'pending_approval' : 'submitted') as ServiceRequestStatus,
      requester_id: ctx.me.id,
      assignee_id: null,
      created_at: iso(Date.now()),
      fulfilled_at: null,
      approvals: item.needs_approval ? [{ id: crypto.randomUUID(), request_id: id, approver_id: ctx.db.users[0].id, decision: 'pending' as const, decided_at: null }] : [],
    };
    ctx.db.requests.push(req);
    publish(ctx.db, 'RequestSubmitted', 'requests', requestEventData(req, ctx.me.id));
    return { data: req };
  }, 201),
  r('get', '/requests/:id', (ctx, [id]) => {
    const req = findOr404(ctx.db.requests, id, 'Solicitud');
    if (ctx.role === 'customer' && req.requester_id !== ctx.me.id) notFound('Solicitud');
    return { data: req };
  }),
  r('patch', '/requests/:id', (ctx, [id], _q, b) => {
    const req = findOr404(ctx.db.requests, id, 'Solicitud');
    if (ctx.role === 'customer') {
      if (req.requester_id !== ctx.me.id) notFound('Solicitud');
      strict(b, ['form_data']);
      if (!['submitted', 'pending_approval'].includes(req.status)) fail(409, 'CONFLICT', 'La solicitud ya está en atención');
    } else strict(b, ['assignee_id']);
    if (b.form_data !== undefined) req.form_data = b.form_data as typeof req.form_data;
    if (b.assignee_id !== undefined) req.assignee_id = (b.assignee_id as string) || null;
    return { data: req };
  }),
  r('put', '/requests/:id/status', (ctx, [id], _q, b) => {
    requireRole(ctx, 'admin', 'agent');
    strict(b, ['status']);
    const req = findOr404(ctx.db.requests, id, 'Solicitud');
    const to = b.status as ServiceRequestStatus;
    if (!REQ_TRANSITIONS[req.status]?.includes(to)) transition(req.status, String(to));
    if (req.status === 'pending_approval') {
      requireRole(ctx, 'admin');
      const ap = req.approvals.find((a) => a.decision === 'pending');
      if (ap) Object.assign(ap, { decision: to, decided_at: iso(Date.now()), approver_id: ctx.me.id });
    }
    if (to === 'in_fulfillment' && !req.assignee_id) req.assignee_id = ctx.me.id;
    if (to === 'fulfilled') req.fulfilled_at = iso(Date.now());
    req.status = to;
    const reqEvent = ({ approved: 'RequestApproved', rejected: 'RequestRejected', fulfilled: 'RequestFulfilled' } as const)[to as 'approved'];
    if (reqEvent) publish(ctx.db, reqEvent, 'requests', requestEventData(req, ctx.me.id));
    return { data: req };
  }),
];

const ROUTES: Record<ServiceName, Route[]> = {
  identity: identityRoutes,
  cmdb: cmdbRoutes,
  incidents: incidentRoutes,
  problems: problemRoutes,
  changes: changeRoutes,
  requests: requestRoutes,
};

// ------------------------------------------------------------------ Login (pública)

function login(body: Body) {
  strict(body, ['tenant_code', 'email', 'password']);
  const code = String(body.tenant_code ?? '');
  if (!/^[a-z0-9_]{2,30}$/.test(code)) invalid('tenant_code', 'Código de organización inválido');
  const pwd = String(body.password ?? '');
  if (pwd.length < 8) invalid('password', 'Mínimo 8 caracteres');
  const bad = () => fail(401, 'INVALID_CREDENTIALS', 'Organización, email o contraseña incorrectos');
  const def = TENANTS.find((t) => t.id === code) ?? bad();
  const db = tenantDb(def.id)!;
  const u = db.users.find((x) => x.email === String(body.email).toLowerCase()) ?? bad();
  if (u.password !== pwd || !u.active) bad();
  const now = Math.floor(Date.now() / 1000);
  const expires_in = 8 * 3600;
  const token = signToken({ sub: u.id, tenant_id: def.id, schema: `tenant_${def.id}`, role: u.role, iat: now, exp: now + expires_in });
  return { data: { access_token: token, token_type: 'Bearer', expires_in, user: { ...publicUser(u), tenant: { id: def.id, name: def.name } } } };
}

// ------------------------------------------------------------------ Adaptador

const delay = () => new Promise((res) => setTimeout(res, 120 + Math.random() * 230));

export function mockAdapter(service: ServiceName): AxiosAdapter {
  return async (config) => {
    await delay();
    const method = (config.method ?? 'get').toLowerCase();
    const path = (config.url ?? '').split('?')[0];
    const body: Body = typeof config.data === 'string' && config.data ? JSON.parse(config.data) : (config.data ?? {});
    const q = (config.params ?? {}) as Q;

    const respond = (status: number, data: unknown): AxiosResponse => ({
      data,
      status,
      statusText: String(status),
      headers: new AxiosHeaders({ 'content-type': 'application/json' }),
      config,
    });

    try {
      if (service === 'identity' && method === 'post' && path === '/auth/login') return respond(200, login(body));

      const claims = readToken(config);
      if (!claims) throw new HttpError(401, { message: 'Unauthorized' });
      const db = tenantDb(claims.tenant_id);
      const me = db?.users.find((u) => u.id === claims.sub);
      if (!db || !me) throw new HttpError(403, { message: 'Forbidden' });
      const ctx: Ctx = { db, me, role: claims.role };

      for (const route of ROUTES[service]) {
        if (route.method !== method) continue;
        const m = route.pattern.exec(path);
        if (!m) continue;
        const out = route.handler(ctx, m.slice(1), q, body);
        // Las lecturas también pueden generar comentarios la primera vez; solo se persisten las escrituras.
        if (method !== 'get') saveTenant(db);
        return respond(route.status ?? 200, out ?? '');
      }
      fail(404, 'NOT_FOUND', `Ruta ${method.toUpperCase()} ${path} no existe`);
    } catch (e) {
      if (e instanceof HttpError) {
        const res = respond(e.status, e.body);
        throw new AxiosError(`Request failed with status code ${e.status}`, String(e.status), config, undefined, res);
      }
      throw e;
    }
  };
}

/** true si el servicio debe simularse. */
export function shouldMock(baseUrl: string | undefined): boolean {
  return import.meta.env.VITE_USE_MOCKS === 'true' || !baseUrl;
}
