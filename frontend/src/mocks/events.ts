/**
 * Bus de eventos simulado: imita SNS `itsm-events` → una cola SQS por consumidor → Lambda.
 * Enrutamiento y cargas según docs/EVENT_CONTRACTS.md (sección 3 y 4).
 * Los consumidores corren con un pequeño retraso, como en AWS, y luego se guarda el estado.
 */
import type { EventEnvelope, EventType } from '../types/api';
import { saveTenant, type MockDelivery, type MockEvent, type TenantDb } from './db';

export type ServiceKey = 'identity' | 'cmdb' | 'incidents' | 'problems' | 'changes' | 'requests';

/** Suscripciones SNS → SQS con su FilterPolicy por eventType. */
export const SUBSCRIPTIONS: Partial<Record<EventType, { queue: string; service: ServiceKey }[]>> = {
  CIStatusChanged: [{ queue: 'incidents-ci-q', service: 'incidents' }],
  IncidentCreated: [
    { queue: 'problems-incidents-q', service: 'problems' },
    { queue: 'identity-notify-q', service: 'identity' },
  ],
  IncidentUpdated: [{ queue: 'identity-notify-q', service: 'identity' }],
  IncidentResolved: [{ queue: 'identity-notify-q', service: 'identity' }],
  IncidentSlaBreached: [{ queue: 'identity-notify-q', service: 'identity' }],
  ProblemCreated: [{ queue: 'identity-notify-q', service: 'identity' }],
  ProblemIncidentsLinked: [{ queue: 'incidents-problem-q', service: 'incidents' }],
  KnownErrorPublished: [
    { queue: 'incidents-kedb-q', service: 'incidents' },
    { queue: 'identity-notify-q', service: 'identity' },
  ],
  ChangeSubmitted: [{ queue: 'identity-notify-q', service: 'identity' }],
  ChangeApproved: [{ queue: 'identity-notify-q', service: 'identity' }],
  ChangeRejected: [{ queue: 'identity-notify-q', service: 'identity' }],
  ChangeImplemented: [
    { queue: 'cmdb-changes-q', service: 'cmdb' },
    { queue: 'problems-changes-q', service: 'problems' },
  ],
  RequestSubmitted: [{ queue: 'identity-notify-q', service: 'identity' }],
  RequestApproved: [
    { queue: 'requests-fulfillment-q', service: 'requests' },
    { queue: 'identity-notify-q', service: 'identity' },
  ],
  RequestRejected: [{ queue: 'identity-notify-q', service: 'identity' }],
  RequestFulfilled: [{ queue: 'identity-notify-q', service: 'identity' }],
  UserCreated: [],
};

export const SOURCE: Record<ServiceKey, string> = {
  identity: 'ms-identity',
  cmdb: 'ms-cmdb',
  incidents: 'ms-incidents',
  problems: 'ms-problems',
  changes: 'ms-changes',
  requests: 'ms-requests',
};

/** Efecto de un consumidor; devuelve una nota corta para la bitácora o `null` si descartó el mensaje. */
export type Consumer = (db: TenantDb, env: EventEnvelope) => string | null;
const consumers = new Map<string, Consumer>();

export function registerConsumer(queue: string, fn: Consumer) {
  consumers.set(queue, fn);
}

// ------------------------------------------------------------------ Suscriptores de la UI

type Listener = (tenantId: string) => void;
const listeners = new Set<Listener>();

export function onMockEvents(fn: Listener): () => void {
  listeners.add(fn);
  // Otra pestaña guardó cambios (p. ej. el admin aprobó algo): avisar también.
  const onStorage = (e: StorageEvent) => {
    const m = e.key?.match(/^servidesk\.mock\.v\d+\.([a-z0-9_]+)\.stamp$/);
    if (m) fn(m[1]);
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(fn);
    window.removeEventListener('storage', onStorage);
  };
}

function emit(tenantId: string) {
  listeners.forEach((l) => l(tenantId));
}

const MAX_EVENTS = 150;

/** Publica un evento (después del "COMMIT") y programa a sus consumidores. */
export function publish(db: TenantDb, eventType: EventType, service: ServiceKey, data: Record<string, unknown>): EventEnvelope {
  const envelope: EventEnvelope = {
    eventId: crypto.randomUUID(),
    eventType,
    tenantId: db.def.id,
    occurredAt: new Date().toISOString(),
    source: SOURCE[service],
    data,
  };
  const deliveries: MockDelivery[] = (SUBSCRIPTIONS[eventType] ?? []).map((s) => ({ ...s, status: 'queued' }));
  const record: MockEvent = { envelope, deliveries };
  db.events.unshift(record);
  if (db.events.length > MAX_EVENTS) db.events.length = MAX_EVENTS;
  emit(db.def.id);

  deliveries.forEach((d, i) => {
    setTimeout(() => {
      const fn = consumers.get(d.queue);
      try {
        const note = fn ? fn(db, envelope) : null;
        d.status = note === null ? 'skipped' : 'processed';
        d.note = note ?? 'Sin efecto para este mensaje';
      } catch (e) {
        d.status = 'skipped';
        d.note = `Error: ${(e as Error).message}`;
      }
      saveTenant(db);
      emit(db.def.id);
    }, 900 + i * 600 + Math.random() * 400);
  });
  return envelope;
}
