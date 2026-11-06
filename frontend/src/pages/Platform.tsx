import { useEffect, useRef, useState } from 'react';
import { changeService, cmdbService, incidentService, MOCKED_SERVICES, problemService, requestService, userService } from '../api';
import { useMe } from '../auth/AuthContext';
import { EventFlow, SERVICES, type Pulse } from '../components/EventFlow';
import { Icon } from '../components/Icon';
import { CountUp } from '../components/motion';
import { PageHeader, useApiErrorToast, useToast } from '../components/ui';
import { fromNow } from '../lib/format';
import { tenantDb, type MockEvent } from '../mocks/db';
import { onMockEvents, type ServiceKey } from '../mocks/events';

const SERVICE_COLOR: Record<ServiceKey, string> = {
  identity: '#2563c9',
  cmdb: '#0e8a72',
  incidents: '#c4312b',
  problems: '#a35d00',
  changes: '#6d3fc4',
  requests: '#0369a1',
};

const DETAILS: Record<ServiceKey, { tables: string; publishes: string[]; consumes: string[] }> = {
  identity: { tables: 'users, teams, team_members, notifications', publishes: ['TenantCreated', 'UserCreated'], consumes: ['identity-notify-q'] },
  cmdb: { tables: 'ci_types, configuration_items, ci_relations, ci_history', publishes: ['CIStatusChanged'], consumes: ['cmdb-changes-q'] },
  incidents: { tables: 'sla_policies, incidents, incident_comments', publishes: ['IncidentCreated', 'IncidentUpdated', 'IncidentResolved'], consumes: ['incidents-ci-q', 'incidents-problem-q', 'incidents-kedb-q'] },
  problems: { tables: 'problems, problem_incidents, known_errors', publishes: ['ProblemCreated', 'ProblemIncidentsLinked', 'KnownErrorPublished'], consumes: ['problems-incidents-q', 'problems-changes-q'] },
  changes: { tables: 'changes, change_approvals, change_cis', publishes: ['ChangeSubmitted', 'ChangeApproved', 'ChangeRejected', 'ChangeImplemented'], consumes: [] },
  requests: { tables: 'catalog_items, service_requests, request_approvals', publishes: ['RequestSubmitted', 'RequestApproved', 'RequestRejected', 'RequestFulfilled'], consumes: ['requests-fulfillment-q'] },
};

const sourceKey = (src: string) => src.replace(/^ms-/, '') as ServiceKey;

export default function Platform() {
  const me = useMe();
  const toast = useToast();
  const onError = useApiErrorToast();
  const live = MOCKED_SERVICES.length > 0;
  const [counts, setCounts] = useState<Partial<Record<ServiceKey, number>>>({});
  const [events, setEvents] = useState<MockEvent[]>([]);
  const [pulses, setPulses] = useState<Pulse[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const lastId = useRef<string | null>(null);
  const clearTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Registros por microservicio en el schema del tenant (funciona igual con el backend real).
  const loadCounts = () => {
    const t = (p: Promise<{ meta: { total: number } }>) => p.then((r) => r.meta.total).catch(() => undefined);
    Promise.all([
      t(userService.list({ limit: 1 })),
      t(cmdbService.list({ limit: 1 })),
      t(incidentService.list({ limit: 1 })),
      t(problemService.list({ limit: 1 })),
      t(changeService.list({ limit: 1 })),
      t(requestService.list({ limit: 1 })),
    ]).then(([identity, cmdb, incidents, problems, changes, requests]) => setCounts({ identity, cmdb, incidents, problems, changes, requests }));
  };

  useEffect(() => {
    loadCounts();
    if (!live) return;
    const sync = () => {
      const list = tenantDb(me.tenant.id)?.events ?? [];
      setEvents(list.map((e) => ({ envelope: e.envelope, deliveries: e.deliveries.map((d) => ({ ...d })) })));
      const top = list[0];
      if (top && top.envelope.eventId !== lastId.current) {
        const first = lastId.current === null;
        lastId.current = top.envelope.eventId;
        if (!first) {
          setPulses([{ id: top.envelope.eventId, source: sourceKey(top.envelope.source), queues: top.deliveries.map((d) => d.queue), label: top.envelope.eventType }]);
          clearTimeout(clearTimer.current);
          clearTimer.current = setTimeout(() => setPulses([]), 3200);
          loadCounts();
        }
      }
    };
    sync();
    const off = onMockEvents((tenant) => tenant === me.tenant.id && sync());
    return () => {
      off();
      clearTimeout(clearTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me.tenant.id, live]);

  async function ciDown() {
    setBusy('ci');
    try {
      const list = await cmdbService.list({ status: 'operational', environment: 'prod', limit: 30 });
      const ci = list.data[Math.floor(Math.random() * list.data.length)];
      if (!ci) return toast('No hay CIs operativos en producción', 'danger');
      await cmdbService.changeStatus(ci.id, { status: 'down' });
      toast(`${ci.name} marcado como caído → CIStatusChanged`, 'info');
    } catch (e) {
      onError(e);
    } finally {
      setBusy(null);
    }
  }

  async function recurring() {
    setBusy('rec');
    try {
      const list = await cmdbService.list({ status: ['operational', 'degraded'], environment: 'prod', limit: 30 });
      // Elegir un CI sin problema abierto, para que ms-problems cree uno nuevo (si no, solo vincula).
      const candidates = [...list.data].sort(() => Math.random() - 0.5);
      let ci = candidates[0];
      for (const c of candidates.slice(0, 10)) {
        const open = await problemService.list({ ci_id: c.id, status: ['new', 'investigating', 'known_error'], limit: 1 });
        if (open.meta.total === 0) {
          ci = c;
          break;
        }
      }
      if (!ci) return;
      for (let i = 1; i <= 3; i++) {
        await incidentService.create({ title: `Error intermitente en ${ci.name} (#${i})`, description: 'Generado desde la vista de plataforma para la demo.', impact: 'medium', urgency: 'high', ci_id: ci.id });
      }
      toast(`3 incidentes sobre ${ci.name}: ms-problems debería crear un problema`, 'info');
    } catch (e) {
      onError(e);
    } finally {
      setBusy(null);
    }
  }

  const processed = events.reduce((n, e) => n + e.deliveries.filter((d) => d.status === 'processed').length, 0);
  const queued = events.reduce((n, e) => n + e.deliveries.filter((d) => d.status === 'queued').length, 0);

  return (
    <>
      <PageHeader
        title="Vista técnica: plataforma y eventos"
        subtitle={`6 microservicios serverless · un schema por tenant (tenant_${me.tenant.id}) · integrados por eventos SNS → SQS`}
        actions={
          <>
            <button className="btn btn-ghost" disabled={!!busy} onClick={recurring}>
              <Icon name="problem" /> {busy === 'rec' ? 'Creando…' : '3 incidentes en un CI'}
            </button>
            <button className="btn btn-primary" disabled={!!busy} onClick={ciDown}>
              <Icon name="bolt" /> {busy === 'ci' ? 'Publicando…' : 'Simular CI caído'}
            </button>
          </>
        }
      />

      <section className="card flow-card">
        <div className="card-head">
          <h2>Flujo de eventos</h2>
          <span className="row gap-sm" style={{ fontSize: 13 }}>
            <span className={`live-dot ${live ? '' : 'off'}`} />
            {live ? 'En vivo (modo demo)' : 'Diagrama de referencia'}
          </span>
        </div>
        <div className="card-body" style={{ paddingTop: 8 }}>
          <EventFlow mode={live ? 'live' : 'loop'} pulses={pulses} counts={counts} />
        </div>
      </section>

      <div className="svc-grid stagger">
        {SERVICES.map((s) => (
          <article key={s.key} className={`card svc ${pulses[0]?.source === s.key ? 'flash' : ''}`} style={{ ['--svc' as string]: SERVICE_COLOR[s.key] }}>
            <header className="row between">
              <strong>{s.name}</strong>
              <span className="svc-db mono">{s.db}</span>
            </header>
            <div className="svc-count">{counts[s.key] !== undefined ? <CountUp value={counts[s.key]!} /> : '—'}</div>
            <small className="muted">registros en tenant_{me.tenant.id}</small>
            <p className="svc-tables mono">{DETAILS[s.key].tables}</p>
            <div className="svc-chips">
              {DETAILS[s.key].publishes.map((e) => (
                <span key={e} className="chip-xs pub">
                  ↑ {e}
                </span>
              ))}
              {DETAILS[s.key].consumes.map((q) => (
                <span key={q} className="chip-xs sub">
                  ↓ {q}
                </span>
              ))}
            </div>
          </article>
        ))}
      </div>

      <section className="card">
        <div className="card-head">
          <h2>Bitácora de eventos</h2>
          {live && (
            <span className="muted" style={{ fontSize: 13 }}>
              {events.length} eventos · {processed} entregas procesadas · {queued} en cola · DLQ 0
            </span>
          )}
        </div>
        {!live ? (
          <div className="empty">
            <Icon name="cloud" size={28} />
            <strong>Conectado al backend real</strong>
            <p>Los mensajes de SNS y SQS se revisan en la consola de AWS y en los logs de CloudWatch de cada consumidor.</p>
          </div>
        ) : events.length === 0 ? (
          <div className="empty">
            <Icon name="bolt" size={28} />
            <strong>Aún no hay eventos en esta sesión</strong>
            <p>Usa “Simular CI caído” o trabaja en otra pestaña (crear, resolver, aprobar…) y mira cómo llegan aquí.</p>
          </div>
        ) : (
          <div className="event-list">
            {events.map((e) => {
              const src = sourceKey(e.envelope.source);
              return (
                <details key={e.envelope.eventId} className="event-item" style={{ ['--svc' as string]: SERVICE_COLOR[src] }}>
                  <summary>
                    <span className="ev-type">{e.envelope.eventType}</span>
                    <span className="ev-src mono">{e.envelope.source}</span>
                    <span className="muted ev-time">{fromNow(e.envelope.occurredAt)}</span>
                    <span className="ev-deliveries">
                      {e.deliveries.length === 0 && <span className="dl skipped">sin suscriptores</span>}
                      {e.deliveries.map((d) => (
                        <span key={d.queue} className={`dl ${d.status}`} title={d.note}>
                          {d.status === 'queued' ? <span className="mini-spin" /> : d.status === 'processed' ? '✓' : '–'} {d.queue}
                        </span>
                      ))}
                    </span>
                  </summary>
                  <div className="ev-body">
                    {e.deliveries.map((d) => (
                      <p key={d.queue}>
                        <b className="mono">{d.queue}</b> → {d.note ?? 'En cola…'}
                      </p>
                    ))}
                    <pre>{JSON.stringify(e.envelope, null, 2)}</pre>
                  </div>
                </details>
              );
            })}
          </div>
        )}
      </section>
    </>
  );
}
