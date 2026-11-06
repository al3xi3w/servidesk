/**
 * Base de datos en memoria para el modo demo (sin backend).
 * Los datos son deterministas por tenant (misma semilla → mismos registros) y siguen docs/API_CONTRACTS.md.
 * Volumen reducido respecto al seed real (10 000 por tenant) para que el navegador lo genere al instante.
 */
import type {
  CatalogItem,
  ChangeApproval,
  ChangeCI,
  ChangeDetail,
  CIRelationType,
  CIType,
  ConfigurationItem,
  EventEnvelope,
  Incident,
  IncidentComment,
  Notification,
  KnownError,
  Priority,
  Problem,
  RequestApproval,
  Role,
  ServiceRequest,
  Team,
  User,
} from '../types/api';
import { priorityOf } from '../lib/format';

// ------------------------------------------------------------------ PRNG determinista

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

export class Rng {
  private next: () => number;
  constructor(seed: string) {
    this.next = mulberry32(hashString(seed));
  }
  float(): number {
    return this.next();
  }
  int(min: number, max: number): number {
    return Math.floor(this.next() * (max - min + 1)) + min;
  }
  pick<T>(arr: readonly T[]): T {
    return arr[Math.floor(this.next() * arr.length)];
  }
  /** Elige según pesos relativos. */
  weighted<T>(entries: readonly (readonly [T, number])[]): T {
    const total = entries.reduce((s, [, w]) => s + w, 0);
    let r = this.next() * total;
    for (const [v, w] of entries) {
      r -= w;
      if (r <= 0) return v;
    }
    return entries[entries.length - 1][0];
  }
  chance(p: number): boolean {
    return this.next() < p;
  }
  uuid(): string {
    const hex = () => Math.floor(this.next() * 16).toString(16);
    const s = (n: number) => Array.from({ length: n }, hex).join('');
    return `${s(8)}-${s(4)}-4${s(3)}-${'89ab'[this.int(0, 3)]}${s(3)}-${s(12)}`;
  }
}

// ------------------------------------------------------------------ Tenants y cuentas demo

export interface TenantDef {
  id: string;
  name: string;
  domain: string;
  password: string;
  /** Ámbito del negocio, usado para nombres de CIs y títulos. */
  flavor: 'retail' | 'salud' | 'campus';
  demo: { admin: [string, string]; agent: [string, string]; customer: [string, string] };
}

export const TENANTS: TenantDef[] = [
  {
    id: 'andina',
    name: 'Andina Retail',
    domain: 'andina.pe',
    password: 'Andina#2026',
    flavor: 'retail',
    demo: {
      admin: ['carla.mendoza', 'Carla Mendoza Ríos'],
      agent: ['lucia.paredes', 'Lucía Paredes Soto'],
      customer: ['jorge.huaman', 'Jorge Huamán Ríos'],
    },
  },
  {
    id: 'pacifico',
    name: 'Clínica Pacífico',
    domain: 'pacifico.pe',
    password: 'Pacifico#2026',
    flavor: 'salud',
    demo: {
      admin: ['ricardo.vega', 'Ricardo Vega Luna'],
      agent: ['ana.quispe', 'Ana Quispe Rojas'],
      customer: ['marta.salazar', 'Marta Salazar Cruz'],
    },
  },
  {
    id: 'unitec',
    name: 'UniTec Campus',
    domain: 'unitec.edu.pe',
    password: 'Unitec#2026',
    flavor: 'campus',
    demo: {
      admin: ['diego.torres', 'Diego Torres Paz'],
      agent: ['sofia.ramos', 'Sofía Ramos Díaz'],
      customer: ['pablo.chavez', 'Pablo Chávez León'],
    },
  },
];

export function demoAccounts(t: TenantDef): { role: Role; email: string; name: string }[] {
  return (['admin', 'agent', 'customer'] as const).map((role) => ({
    role,
    email: `${t.demo[role][0]}@${t.domain}`,
    name: t.demo[role][1],
  }));
}

// ------------------------------------------------------------------ Catálogos de texto

const FIRST = ['Carlos', 'María', 'José', 'Rosa', 'Luis', 'Carmen', 'Miguel', 'Elena', 'Andrés', 'Patricia', 'Raúl', 'Gabriela', 'Fernando', 'Valeria', 'Héctor', 'Daniela', 'Óscar', 'Lorena', 'Iván', 'Claudia', 'Julio', 'Natalia', 'Renzo', 'Pilar', 'Mauricio', 'Silvia', 'Gonzalo', 'Teresa'];
const LAST = ['García', 'Flores', 'Rodríguez', 'Sánchez', 'Ramírez', 'Torres', 'Castillo', 'Mendoza', 'Rojas', 'Vargas', 'Gutiérrez', 'Chávez', 'Morales', 'Ortiz', 'Herrera', 'Medina', 'Aguilar', 'Cárdenas', 'Espinoza', 'Huamán', 'Paredes', 'Salazar'];

const TEAM_DEFS: [string, string][] = [
  ['Mesa de Ayuda N1', 'Primer contacto, triage y resolución rápida'],
  ['Soporte N2', 'Diagnóstico avanzado de estaciones y aplicaciones'],
  ['Infraestructura', 'Servidores, virtualización y almacenamiento'],
  ['Redes y Comunicaciones', 'LAN, WAN, VPN y telefonía'],
  ['Aplicaciones de Negocio', 'ERP, CRM y sistemas propios'],
  ['Seguridad de la Información', 'Accesos, vulnerabilidades y cumplimiento'],
];

const CI_TYPES = ['Servidor', 'Base de datos', 'Aplicación', 'Red', 'Estación de trabajo', 'Servicio cloud'];

const CI_NAMES: Record<TenantDef['flavor'], string[]> = {
  retail: ['pos-tienda', 'erp-sap', 'ecommerce-web', 'inventario-api', 'pagos-gateway', 'crm-clientes', 'almacen-wms'],
  salud: ['his-clinico', 'citas-web', 'laboratorio-lis', 'farmacia-api', 'pacs-imagenes', 'historia-ehr', 'facturacion'],
  campus: ['campus-virtual', 'matricula-api', 'biblioteca', 'notas-sis', 'wifi-campus', 'correo-edu', 'pagos-pension'],
};

const INCIDENT_TITLES = [
  'No puedo acceder a {app}',
  '{app} responde muy lento',
  'Error 500 al guardar en {app}',
  'Impresora del piso {n} no imprime',
  'VPN se desconecta cada pocos minutos',
  'Correo no sincroniza en el móvil',
  'Contraseña bloqueada tras varios intentos',
  'Pantalla azul en laptop asignada',
  'Caída intermitente de red en sede {n}',
  'Certificado SSL vencido en {app}',
  'No llegan notificaciones de {app}',
  'Disco lleno en servidor de {app}',
  'Teléfono IP sin tono',
  'Reporte mensual de {app} no se genera',
  'Wi-Fi sin conexión en sala {n}',
  'Lentitud general al iniciar sesión',
  'Fallo en sincronización de {app} con ERP',
  'Usuario sin permisos en carpeta compartida',
];

const PROBLEM_TITLES = [
  'Fugas de memoria recurrentes en {app}',
  'Saturación del pool de conexiones de {app}',
  'Cortes de red en horario punta',
  'Fallas repetidas de autenticación SSO',
  'Errores de replicación en base de datos de {app}',
  'Degradación del rendimiento tras actualizaciones',
  'Caídas del servicio de colas en {app}',
  'Tiempo de respuesta alto en {app} los lunes',
];

const ROOT_CAUSES = [
  'Configuración incorrecta del pool de conexiones tras la última versión.',
  'Controlador de red desactualizado en los equipos afectados.',
  'Tarea programada que bloquea tablas durante el horario laboral.',
  'Memoria insuficiente asignada a la máquina virtual.',
];

const CHANGE_TITLES = [
  'Actualizar {app} a la versión {v}',
  'Aplicar parches de seguridad mensuales en servidores',
  'Migrar base de datos de {app} a nueva instancia',
  'Ampliar almacenamiento del clúster de {app}',
  'Renovar certificados SSL de {app}',
  'Reemplazar switch del piso {n}',
  'Habilitar MFA para acceso remoto',
  'Ajustar reglas del firewall perimetral',
  'Escalar horizontalmente {app}',
  'Desplegar nueva versión del portal de {app}',
];

const COMMENT_BODIES = [
  'Se revisaron los registros del servicio; se observa un pico de errores a las {h}:00.',
  'Contacté al usuario, confirma que el problema persiste.',
  'Se reinició el servicio y se está monitoreando.',
  'Escalado al equipo de infraestructura para revisión.',
  'Pendiente de ventana de mantenimiento para aplicar la corrección.',
  'El usuario adjunta captura del error.',
  'Se aplicó la solución temporal publicada en el error conocido.',
  'Gracias, quedo atento a la actualización.',
];

// ------------------------------------------------------------------ Reglas compartidas con el backend

export { priorityOf };

export const SLA_HOURS: Record<Priority, number> = { P1: 4, P2: 8, P3: 24, P4: 72 };
const SLA_POLICY_ID: Record<Priority, number> = { P1: 1, P2: 2, P3: 3, P4: 4 };

// ------------------------------------------------------------------ Modelo del tenant

export interface StoredUser extends User {
  password: string;
  team_ids: string[];
}

export interface TenantDb {
  def: TenantDef;
  users: StoredUser[];
  teams: Team[];
  ciTypes: CIType[];
  cis: ConfigurationItem[];
  relations: { id: string; source_id: string; target_id: string; relation: CIRelationType }[];
  incidents: Incident[];
  comments: Map<string, IncidentComment[]>;
  problems: (Problem & { incident_ids: string[]; known_error: KnownError | null })[];
  changes: ChangeDetail[];
  catalog: CatalogItem[];
  requests: (ServiceRequest & { approvals: RequestApproval[] })[];
  counters: { INC: number; PRB: number; CHG: number; REQ: number };
  /** Bitácora de eventos SNS → SQS (más recientes primero). */
  events: MockEvent[];
  notifications: Notification[];
  rng: Rng;
}

export type DeliveryStatus = 'queued' | 'processed' | 'skipped';

export interface MockDelivery {
  queue: string;
  service: string;
  status: DeliveryStatus;
  note?: string;
}

export interface MockEvent {
  envelope: EventEnvelope;
  deliveries: MockDelivery[];
}

const H = 3_600_000;
const D = 24 * H;

function iso(ms: number): string {
  return new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function fill(tpl: string, rng: Rng, apps: string[]): string {
  return tpl
    .replace('{app}', rng.pick(apps))
    .replace('{n}', String(rng.int(1, 9)))
    .replace('{v}', `${rng.int(2, 9)}.${rng.int(0, 12)}`)
    .replace('{h}', String(rng.int(8, 20)).padStart(2, '0'));
}

export function keyOf(prefix: string, n: number): string {
  return `${prefix}-${String(n).padStart(6, '0')}`;
}

function buildTenant(def: TenantDef): TenantDb {
  const rng = new Rng(`servidesk:${def.id}`);
  const now = Date.now();
  const apps = CI_NAMES[def.flavor];

  // Equipos
  const teams: Team[] = TEAM_DEFS.map(([name, description]) => ({ id: rng.uuid(), name, description }));

  // Usuarios: 3 demo + generados
  const users: StoredUser[] = [];
  const addUser = (email: string, full_name: string, role: Role, team_ids: string[]) => {
    users.push({
      id: rng.uuid(),
      email,
      full_name,
      role,
      active: rng.chance(0.96) || users.length < 3,
      created_at: iso(now - rng.int(30, 700) * D),
      password: def.password,
      team_ids,
    });
  };
  for (const acc of demoAccounts(def)) {
    addUser(acc.email, acc.name, acc.role, acc.role === 'customer' ? [] : [teams[0].id, teams[1].id]);
  }
  const usedEmails = new Set(users.map((u) => u.email));
  for (let i = 0; i < 46; i++) {
    const role: Role = i < 2 ? 'admin' : i < 18 ? 'agent' : 'customer';
    const first = rng.pick(FIRST);
    const last = rng.pick(LAST);
    let email = `${first}.${last}`.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '') + `@${def.domain}`;
    if (usedEmails.has(email)) email = email.replace('@', `${i}@`);
    usedEmails.add(email);
    addUser(email, `${first} ${last} ${rng.pick(LAST)}`, role, role === 'customer' ? [] : [rng.pick(teams).id]);
  }
  users[0].active = users[1].active = users[2].active = true;
  const agents = users.filter((u) => u.role !== 'customer');
  const customers = users.filter((u) => u.role === 'customer');

  // CMDB
  const ciTypes: CIType[] = CI_TYPES.map((name, i) => ({ id: i + 1, name }));
  const cis: ConfigurationItem[] = [];
  for (let i = 0; i < 90; i++) {
    const type = rng.pick(ciTypes);
    const base = rng.pick(apps);
    const env = rng.weighted([['prod', 5], ['qa', 2], ['dev', 2]] as const);
    const suffix = { 1: 'srv', 2: 'db', 3: 'app', 4: 'net', 5: 'pc', 6: 'cloud' }[type.id] ?? 'ci';
    const created = now - rng.int(60, 900) * D;
    cis.push({
      id: rng.uuid(),
      type_id: type.id,
      type_name: type.name,
      name: `${base}-${suffix}-${env}-${String(i + 1).padStart(2, '0')}`,
      status: rng.weighted([['operational', 78], ['degraded', 10], ['down', 4], ['retired', 8]] as const),
      environment: env,
      version: rng.chance(0.8) ? `${rng.int(1, 14)}.${rng.int(0, 9)}.${rng.int(0, 20)}` : null,
      owner_team_id: rng.pick(teams).id,
      attributes:
        type.id === 1
          ? { cpu: rng.pick([2, 4, 8, 16]), ram_gb: rng.pick([4, 8, 16, 32, 64]), os: rng.pick(['Ubuntu 24.04', 'RHEL 9', 'Windows Server 2022']) }
          : type.id === 2
            ? { engine: rng.pick(['PostgreSQL 16', 'MySQL 8', 'SQL Server 2022']), size_gb: rng.int(10, 900) }
            : type.id === 6
              ? { provider: 'AWS', region: 'us-east-1', service: rng.pick(['Lambda', 'RDS', 'S3', 'API Gateway']) }
              : { location: `Sede ${rng.pick(['Central', 'Norte', 'Sur', 'Este'])}` },
      created_at: iso(created),
      updated_at: iso(created + rng.int(0, 50) * D),
    });
  }
  const relations: TenantDb['relations'] = [];
  for (let i = 0; i < 120; i++) {
    const a = rng.pick(cis);
    const b = rng.pick(cis);
    if (a.id === b.id) continue;
    relations.push({ id: rng.uuid(), source_id: a.id, target_id: b.id, relation: rng.pick(['depends_on', 'runs_on', 'connects_to'] as const) });
  }
  const liveCis = cis.filter((c) => c.status !== 'retired');

  // Problemas (antes que incidentes, para enlazarlos)
  const problems: TenantDb['problems'] = [];
  for (let i = 0; i < 70; i++) {
    const status = rng.weighted([['new', 15], ['investigating', 30], ['known_error', 20], ['resolved', 20], ['closed', 15]] as const);
    const created = now - rng.int(1, 240) * D - rng.int(0, 23) * H;
    const id = rng.uuid();
    const withCause = status !== 'new' && status !== 'investigating';
    problems.push({
      id,
      key: keyOf('PRB', i + 1),
      title: fill(rng.pick(PROBLEM_TITLES), rng, apps),
      description: 'Se repiten fallas con síntomas parecidos. Se registra para encontrar la causa de fondo.',
      status,
      priority: rng.weighted([['P1', 1], ['P2', 3], ['P3', 4], ['P4', 2]] as const),
      root_cause: withCause || rng.chance(0.3) ? rng.pick(ROOT_CAUSES) : null,
      ci_id: rng.chance(0.85) ? rng.pick(liveCis).id : null,
      owner_id: rng.chance(0.9) ? rng.pick(agents).id : null,
      fix_change_id: null,
      created_at: iso(created),
      incident_ids: [],
      known_error:
        status === 'known_error' || (withCause && rng.chance(0.6))
          ? {
              id: rng.uuid(),
              problem_id: id,
              symptom: 'Los usuarios reportan lentitud y errores intermitentes al iniciar sesión.',
              workaround: 'Reiniciar la sesión y limpiar la caché del navegador. Si persiste, usar el acceso alternativo publicado en la intranet.',
              published_at: iso(created + rng.int(1, 10) * D),
            }
          : null,
    });
  }

  // Incidentes
  const incidents: Incident[] = [];
  const N_INC = 480;
  for (let i = 0; i < N_INC; i++) {
    // Más recientes al final; claves correlativas por fecha.
    // Distribución sesgada hacia lo reciente: más carga abierta en los últimos días.
    const created = now - Math.floor(Math.pow((N_INC - i) / N_INC, 2.2) * 120 * D) - rng.int(0, 10) * H;
    const ageH = (now - created) / H;
    const impact = rng.weighted([['high', 2], ['medium', 5], ['low', 4]] as const);
    const urgency = rng.weighted([['high', 2], ['medium', 5], ['low', 4]] as const);
    const priority = priorityOf(impact, urgency);
    const status =
      ageH < 72
        ? rng.weighted([['new', 4], ['in_progress', 4], ['on_hold', 1], ['resolved', 2]] as const)
        : ageH < 24 * 14
          ? rng.weighted([['in_progress', 1], ['on_hold', 1], ['resolved', 4], ['closed', 9]] as const)
          : rng.weighted([['in_progress', 1], ['resolved', 2], ['closed', 14]] as const);
    const sla_due = created + SLA_HOURS[priority] * H;
    const resolvedAt = status === 'resolved' || status === 'closed' ? created + rng.float() * SLA_HOURS[priority] * 1.6 * H : null;
    const breached = resolvedAt ? resolvedAt > sla_due : now > sla_due;
    const channel = rng.weighted([['portal', 6], ['email', 3], ['auto', 1]] as const);
    const ci = rng.chance(0.75) ? rng.pick(liveCis) : null;
    const assigned = status !== 'new' || rng.chance(0.3);
    const problem = rng.chance(0.18) ? rng.pick(problems) : null;
    const inc: Incident = {
      id: rng.uuid(),
      key: keyOf('INC', i + 1),
      title: channel === 'auto' && ci ? `[Automático] ${ci.name} dejó de responder` : fill(rng.pick(INCIDENT_TITLES), rng, apps),
      description:
        channel === 'auto'
          ? 'ServiDesk detectó que este equipo o sistema dejó de responder y abrió el reporte automáticamente.'
          : 'El usuario reporta el inconveniente desde su puesto de trabajo. Afecta sus labores diarias.',
      status,
      impact,
      urgency,
      priority,
      sla_policy_id: SLA_POLICY_ID[priority],
      sla_due_at: iso(sla_due),
      sla_breached: breached,
      reporter_id: rng.chance(0.65) ? rng.pick(customers).id : rng.pick(users).id,
      assignee_id: assigned ? rng.pick(agents).id : null,
      team_id: assigned || rng.chance(0.5) ? rng.pick(teams).id : null,
      ci_id: ci?.id ?? null,
      problem_id: problem?.id ?? null,
      channel,
      created_at: iso(created),
      resolved_at: resolvedAt ? iso(resolvedAt) : null,
    };
    // El cliente demo tiene varios incidentes propios.
    if (i % 23 === 0) inc.reporter_id = users[2].id;
    if (problem) problem.incident_ids.push(inc.id);
    incidents.push(inc);
  }
  // El agente demo tiene cola propia.
  incidents.filter((x) => x.status === 'new' || x.status === 'in_progress').slice(-18).forEach((x, k) => {
    if (k % 2 === 0) {
      x.assignee_id = users[1].id;
      if (x.status === 'new') x.status = 'in_progress';
    }
  });

  // Cambios
  const changes: ChangeDetail[] = [];
  for (let i = 0; i < 140; i++) {
    const type = rng.weighted([['standard', 4], ['normal', 5], ['emergency', 1]] as const);
    const risk = type === 'emergency' ? 'high' : rng.weighted([['low', 4], ['medium', 4], ['high', 2]] as const);
    const startOffset = rng.int(-60, 45);
    const start = now + startOffset * D + rng.int(-6, 6) * H;
    const end = start + rng.int(1, 8) * H;
    const past = startOffset < -1;
    const status = past
      ? rng.weighted([['implemented', 12], ['failed', 1], ['rejected', 2]] as const)
      : startOffset < 3
        ? rng.weighted([['scheduled', 5], ['approved', 3], ['submitted', 2], ['implemented', 2]] as const)
        : rng.weighted([['draft', 3], ['submitted', 4], ['approved', 3], ['scheduled', 4], ['rejected', 1]] as const);
    const id = rng.uuid();
    const created = Math.min(start, now) - rng.int(3, 20) * D;
    const approvals: ChangeApproval[] = [];
    const admin = users[0];
    if (status !== 'draft' && type !== 'standard') {
      const decision = status === 'submitted' ? 'pending' : status === 'rejected' ? 'rejected' : 'approved';
      approvals.push({
        id: rng.uuid(),
        change_id: id,
        approver_id: admin.id,
        decision,
        comment: decision === 'rejected' ? 'Falta detallar el plan de reversión.' : decision === 'approved' ? 'Aprobado por el CAB.' : null,
        decided_at: decision === 'pending' ? null : iso(created + 2 * D),
      });
    }
    const cisOf: ChangeCI[] = Array.from({ length: rng.int(1, 3) }, () => ({ ci_id: rng.pick(liveCis).id, new_version: rng.chance(0.5) ? `${rng.int(2, 9)}.${rng.int(0, 9)}` : null }));
    const prob = rng.chance(0.15) ? rng.pick(problems) : null;
    changes.push({
      id,
      key: keyOf('CHG', i + 1),
      title: fill(rng.pick(CHANGE_TITLES), rng, apps),
      description: 'Cambio planificado para mejorar la estabilidad y seguridad del servicio.',
      type,
      risk,
      status,
      rollback_plan: type === 'standard' && rng.chance(0.5) ? null : 'Restaurar la instantánea previa y revertir la configuración desde el repositorio.',
      planned_start: iso(start),
      planned_end: iso(end),
      requester_id: rng.pick(agents).id,
      problem_id: prob?.id ?? null,
      created_at: iso(created),
      cis: cisOf,
      approvals,
    });
    if (prob && !prob.fix_change_id) prob.fix_change_id = id;
  }
  changes.sort((a, b) => a.created_at.localeCompare(b.created_at));
  changes.forEach((c, i) => (c.key = keyOf('CHG', i + 1)));

  // Catálogo
  const cat = (category_id: number, category_name: string, name: string, fields: CatalogItem['form_schema']['fields'], needs_approval: boolean, sla_hours: number | null): CatalogItem => ({
    id: rng.uuid(),
    category_id,
    category_name,
    name,
    form_schema: { fields },
    needs_approval,
    sla_hours,
  });
  const just = { name: 'justificacion', label: 'Justificación', type: 'textarea', required: true } as const;
  const catalog: CatalogItem[] = [
    cat(1, 'Hardware', 'Laptop nueva', [
      { name: 'modelo', label: 'Modelo', type: 'select', required: true, options: ['Estándar 14"', 'Desarrollo 16"', 'Ultraligera 13"'] },
      { name: 'fecha_entrega', label: 'Fecha deseada', type: 'date', required: false },
      just,
    ], true, 72),
    cat(1, 'Hardware', 'Monitor adicional', [{ name: 'tamano', label: 'Tamaño', type: 'select', required: true, options: ['24"', '27"', '32"'] }, just], true, 48),
    cat(1, 'Hardware', 'Periféricos (mouse, teclado, headset)', [{ name: 'item', label: 'Artículo', type: 'select', required: true, options: ['Mouse', 'Teclado', 'Headset', 'Webcam'] }, { name: 'cantidad', label: 'Cantidad', type: 'number', required: true }], false, 24),
    cat(2, 'Software', 'Licencia de software', [{ name: 'producto', label: 'Producto', type: 'select', required: true, options: ['Microsoft 365 E3', 'Adobe Acrobat Pro', 'JetBrains All Products', 'Tableau Creator'] }, just], true, 48),
    cat(2, 'Software', 'Instalación de aplicación', [{ name: 'aplicacion', label: 'Aplicación', type: 'text', required: true }, { name: 'equipo', label: 'Nombre del equipo', type: 'text', required: true }], false, 24),
    cat(3, 'Accesos', 'Acceso a sistema', [{ name: 'sistema', label: 'Sistema', type: 'select', required: true, options: apps }, { name: 'perfil', label: 'Perfil', type: 'select', required: true, options: ['Lectura', 'Operador', 'Administrador'] }, just], true, 24),
    cat(3, 'Accesos', 'Restablecer contraseña', [{ name: 'cuenta', label: 'Cuenta', type: 'text', required: true }], false, 4),
    cat(3, 'Accesos', 'Acceso VPN', [{ name: 'temporal', label: 'Acceso temporal', type: 'boolean', required: false }, { name: 'hasta', label: 'Vigente hasta', type: 'date', required: false }, just], true, 24),
    cat(4, 'Colaboración', 'Buzón o lista de correo compartida', [{ name: 'nombre', label: 'Nombre del buzón', type: 'text', required: true }, { name: 'miembros', label: 'Miembros (correos)', type: 'textarea', required: true }], false, 24),
    cat(4, 'Colaboración', 'Sala de videoconferencia', [{ name: 'sede', label: 'Sede', type: 'select', required: true, options: ['Central', 'Norte', 'Sur'] }, { name: 'fecha', label: 'Fecha', type: 'date', required: true }], false, 8),
    cat(5, 'Personas', 'Alta de nuevo colaborador', [{ name: 'nombre', label: 'Nombre completo', type: 'text', required: true }, { name: 'area', label: 'Área', type: 'text', required: true }, { name: 'inicio', label: 'Fecha de ingreso', type: 'date', required: true }, { name: 'laptop', label: 'Requiere laptop', type: 'boolean', required: false }], true, 72),
    cat(5, 'Personas', 'Baja de colaborador', [{ name: 'nombre', label: 'Nombre completo', type: 'text', required: true }, { name: 'ultimo_dia', label: 'Último día', type: 'date', required: true }], true, 24),
  ];

  // Solicitudes
  const requests: TenantDb['requests'] = [];
  for (let i = 0; i < 300; i++) {
    const item = rng.pick(catalog);
    const created = now - Math.floor(((300 - i) / 300) * 90 * D) - rng.int(0, 20) * H;
    const recent = now - created < 5 * D;
    const status = item.needs_approval
      ? recent
        ? rng.weighted([['pending_approval', 4], ['approved', 2], ['in_fulfillment', 2], ['rejected', 1]] as const)
        : rng.weighted([['fulfilled', 12], ['rejected', 2], ['in_fulfillment', 1]] as const)
      : recent
        ? rng.weighted([['submitted', 4], ['in_fulfillment', 3], ['fulfilled', 2]] as const)
        : rng.weighted([['fulfilled', 14], ['rejected', 1]] as const);
    const id = rng.uuid();
    const form_data: Record<string, string | number | boolean | null> = {};
    for (const f of item.form_schema.fields) {
      form_data[f.name] =
        f.type === 'select' ? rng.pick(f.options ?? ['—'])
          : f.type === 'number' ? rng.int(1, 3)
            : f.type === 'boolean' ? rng.chance(0.5)
              : f.type === 'date' ? iso(created + rng.int(2, 15) * D).slice(0, 10)
                : f.type === 'textarea' ? 'Necesario para cumplir con las tareas del puesto.'
                  : `${rng.pick(FIRST)} ${rng.pick(LAST)}`;
    }
    const decided = status !== 'pending_approval' && item.needs_approval;
    requests.push({
      id,
      key: keyOf('REQ', i + 1),
      catalog_item_id: item.id,
      catalog_item_name: item.name,
      form_data,
      status,
      requester_id: i % 17 === 0 ? users[2].id : rng.pick(customers).id,
      assignee_id: status === 'in_fulfillment' || status === 'fulfilled' ? rng.pick(agents).id : null,
      created_at: iso(created),
      fulfilled_at: status === 'fulfilled' ? iso(created + rng.int(2, 70) * H) : null,
      approvals: item.needs_approval
        ? [{ id: rng.uuid(), request_id: id, approver_id: users[0].id, decision: !decided ? 'pending' : status === 'rejected' ? 'rejected' : 'approved', decided_at: decided ? iso(created + rng.int(1, 30) * H) : null }]
        : [],
    });
  }

  // Bandeja inicial de las cuentas demo (lo que habría llenado identity-notify-q).
  const notifications: Notification[] = [];
  const note = (user: StoredUser, event_type: Notification['event_type'], title: string, body: string, hoursAgo: number, read: boolean, resource_type: Notification['resource_type'], resource_id: string | null) =>
    notifications.push({ id: rng.uuid(), user_id: user.id, event_type, title, body, read, created_at: iso(now - hoursAgo * H), resource_type, resource_id });
  const [adminU, agentU, customerU] = users;
  const openInc = incidents.filter((x) => x.status === 'in_progress' && x.assignee_id === agentU.id);
  openInc.slice(0, 3).forEach((x, k) => note(agentU, 'IncidentUpdated', `Te asignaron la falla ${x.key}`, x.title, 2 + k * 5, k > 0, 'incident', x.id));
  const breached = incidents.find((x) => x.sla_breached && x.status !== 'closed' && x.status !== 'resolved');
  if (breached) note(agentU, 'IncidentSlaBreached', `La falla ${breached.key} superó su plazo`, `${breached.priority} · ${breached.title}`, 1, false, 'incident', breached.id);
  changes.filter((c) => c.status === 'submitted').slice(0, 3).forEach((c, k) => note(adminU, 'ChangeSubmitted', `La actualización ${c.key} espera tu aprobación`, c.title, 1 + k * 7, k > 1, 'change', c.id));
  requests.filter((r) => r.status === 'pending_approval').slice(0, 2).forEach((r, k) => note(adminU, 'RequestSubmitted', `El pedido ${r.key} necesita tu aprobación`, r.catalog_item_name, 3 + k * 6, false, 'request', r.id));
  requests.filter((r) => r.requester_id === customerU.id).slice(-3).forEach((r, k) =>
    note(customerU, r.status === 'fulfilled' ? 'RequestFulfilled' : 'RequestSubmitted', r.status === 'fulfilled' ? `Tu pedido ${r.key} fue entregado` : `Recibimos tu pedido ${r.key}`, r.catalog_item_name, 4 + k * 20, k > 0, 'request', r.id),
  );
  notifications.sort((a, b) => b.created_at.localeCompare(a.created_at));

  return {
    def,
    events: [],
    notifications,
    users,
    teams,
    ciTypes,
    cis,
    relations,
    incidents,
    comments: new Map(),
    problems,
    changes,
    catalog,
    requests,
    counters: { INC: incidents.length, PRB: problems.length, CHG: changes.length, REQ: requests.length },
    rng,
  };
}

// ------------------------------------------------------------------ Caché y persistencia
// Los cambios se guardan en localStorage para que todas las pestañas del navegador vean los mismos datos
// (p. ej. un agente crea un cambio y un administrador lo aprueba en otra pestaña).

const STORE_PREFIX = 'servidesk.mock.v3.';
const cache = new Map<string, { db: TenantDb; stamp: string | null }>();

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function load(def: TenantDef): { db: TenantDb; stamp: string | null } | null {
  const ls = storage();
  const raw = ls?.getItem(STORE_PREFIX + def.id);
  if (!raw) return null;
  try {
    const data = JSON.parse(raw) as Omit<TenantDb, 'comments' | 'rng' | 'def'> & { comments: [string, IncidentComment[]][] };
    return {
      db: { ...data, events: data.events ?? [], notifications: data.notifications ?? [], def, comments: new Map(data.comments), rng: new Rng(`servidesk:${def.id}`) },
      stamp: ls?.getItem(STORE_PREFIX + def.id + '.stamp') ?? null,
    };
  } catch {
    return null;
  }
}

export function tenantDb(tenantId: string): TenantDb | undefined {
  const def = TENANTS.find((t) => t.id === tenantId);
  if (!def) return undefined;
  const stamp = storage()?.getItem(STORE_PREFIX + def.id + '.stamp') ?? null;
  let entry = cache.get(tenantId);
  // Otra pestaña guardó cambios: recargar.
  if (entry && stamp && entry.stamp !== stamp) entry = undefined;
  if (!entry) {
    entry = load(def) ?? { db: buildTenant(def), stamp: null };
    cache.set(tenantId, entry);
  }
  return entry.db;
}

/** Guarda el estado del tenant tras una escritura. */
export function saveTenant(db: TenantDb): void {
  const ls = storage();
  if (!ls) return;
  const { rng: _r, def: _d, comments, ...rest } = db;
  const stamp = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  try {
    ls.setItem(STORE_PREFIX + db.def.id, JSON.stringify({ ...rest, comments: [...comments.entries()] }));
    ls.setItem(STORE_PREFIX + db.def.id + '.stamp', stamp);
    const entry = cache.get(db.def.id);
    if (entry) entry.stamp = stamp;
  } catch {
    /* sin espacio: los cambios quedan solo en memoria */
  }
}

/** Borra los cambios hechos en la demo y vuelve a los datos iniciales. */
export function resetDemoData(): void {
  const ls = storage();
  for (const t of TENANTS) {
    ls?.removeItem(STORE_PREFIX + t.id);
    ls?.removeItem(STORE_PREFIX + t.id + '.stamp');
  }
  cache.clear();
}

/** Comentarios generados la primera vez que se consultan. */
export function commentsOf(db: TenantDb, inc: Incident): IncidentComment[] {
  let list = db.comments.get(inc.id);
  if (!list) {
    const rng = new Rng(inc.id);
    const agents = db.users.filter((u) => u.role !== 'customer');
    const n = inc.status === 'new' ? rng.int(0, 1) : rng.int(1, 5);
    const start = Date.parse(inc.created_at);
    list = Array.from({ length: n }, (_, k) => {
      const fromReporter = rng.chance(0.3);
      return {
        id: rng.uuid(),
        incident_id: inc.id,
        author_id: fromReporter ? inc.reporter_id : (inc.assignee_id ?? rng.pick(agents).id),
        body: fill(rng.pick(COMMENT_BODIES), rng, CI_NAMES[db.def.flavor]),
        internal: !fromReporter && rng.chance(0.35),
        created_at: iso(start + (k + 1) * rng.int(1, 6) * H),
      };
    });
    db.comments.set(inc.id, list);
  }
  return list;
}

export { iso };
