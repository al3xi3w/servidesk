import { useEffect, useState } from 'react';
import { useLiveRefresh } from '../lib/live';
import { Link, useNavigate } from 'react-router-dom';
import { CountUp } from '../components/motion';
import { changeService, cmdbService, incidentService, problemService, requestService } from '../api';
import { useMe } from '../auth/AuthContext';
import { Icon, type IconName } from '../components/Icon';
import { Empty, ErrorBox, PageHeader, PriorityBadge, Spinner, StatusBadge } from '../components/ui';
import { CHANGE_STATUS, fmtDateTime, fromNow, INCIDENT_STATUS, REQUEST_STATUS, RISK } from '../lib/format';
import { useAsync } from '../lib/hooks';
import type { IncidentStatus, Priority } from '../types/api';

const OPEN: IncidentStatus[] = ['new', 'in_progress', 'on_hold'];
const total = (p: Promise<{ meta: { total: number } }>) => p.then((r) => r.meta.total);

export default function Dashboard() {
  const me = useMe();
  return me.role === 'customer' ? <PortalHome /> : <AgentDashboard />;
}

function AgentDashboard() {
  const me = useMe();
  const nav = useNavigate();

  const stats = useAsync(async () => {
    const now = new Date();
    const week = new Date(now.getTime() + 7 * 86400000);
    const [open, p1, breached, mine, cab, approvals, down, investigating, byPrio, byStatus, recent, upcoming, done, doneLate] = await Promise.all([
      total(incidentService.list({ status: OPEN, limit: 1 })),
      total(incidentService.list({ status: OPEN, priority: 'P1', limit: 1 })),
      total(incidentService.list({ status: OPEN, sla_breached: true, limit: 1 })),
      total(incidentService.list({ status: OPEN, assignee_id: 'me', limit: 1 })),
      total(changeService.list({ status: 'submitted', limit: 1 })),
      total(requestService.list({ status: 'pending_approval', limit: 1 })),
      total(cmdbService.list({ status: 'down', limit: 1 })),
      total(problemService.list({ status: ['investigating', 'known_error'], limit: 1 })),
      Promise.all((['P1', 'P2', 'P3', 'P4'] as Priority[]).map((p) => total(incidentService.list({ status: OPEN, priority: p, limit: 1 })))),
      Promise.all(OPEN.map((s) => total(incidentService.list({ status: s, limit: 1 })))),
      incidentService.list({ status: OPEN, sort_by: 'created_at', limit: 6 }),
      changeService.list({ planned_from: now.toISOString(), planned_to: week.toISOString(), status: ['approved', 'scheduled', 'submitted'], sort_by: 'planned_start', sort_order: 'asc', limit: 6 }),
      total(incidentService.list({ status: ['resolved', 'closed'], limit: 1 })),
      total(incidentService.list({ status: ['resolved', 'closed'], sla_breached: true, limit: 1 })),
    ]);
    const slaMet = done ? Math.round(((done - doneLate) / done) * 100) : 100;
    return { open, p1, breached, mine, cab, approvals, down, investigating, byPrio, byStatus, recent: recent.data, upcoming: upcoming.data, slaMet, done };
  }, []);

  useLiveRefresh(me.tenant.id, stats.reload);
  const hour = new Date().getHours();
  const greet = hour < 12 ? 'Buenos días' : hour < 19 ? 'Buenas tardes' : 'Buenas noches';

  return (
    <>
      <PageHeader
        title={`${greet}, ${me.full_name.split(' ')[0]}`}
        subtitle={`Así está hoy la atención de TI en ${me.tenant.name}`}
        actions={
          <>
            <Link to="/app/incidents?new=1" className="btn btn-primary">
              <Icon name="plus" /> Reportar falla
            </Link>
            <Link to="/app/changes?new=1" className="btn btn-ghost">
              <Icon name="change" /> Planificar actualización
            </Link>
          </>
        }
      />

      {stats.error && <ErrorBox error={stats.error} onRetry={stats.reload} />}
      {stats.loading && !stats.data && <Spinner />}
      {stats.data && (
        <>
          <div className="kpis stagger">
            <Kpi to="/app/incidents" icon="incident" tone="info" label="Fallas abiertas" value={stats.data.open} sub="Nuevas, en curso y en espera" />
            <Kpi to="/app/incidents?priority=P1" icon="bolt" tone="danger" label="Fallas urgentes" value={stats.data.p1} alert={stats.data.p1 > 0} sub="Prioridad P1, atender ya" />
            <Kpi to="/app/incidents?sla=1" icon="clock" tone="warning" label="Fuera de plazo" value={stats.data.breached} alert={stats.data.breached > 0} sub="Abiertas que superaron su plazo" />
            <Kpi to="/app/incidents?mine=1" icon="users" tone="accent" label="Asignadas a mí" value={stats.data.mine} sub="Tu cola personal" />
          </div>
          <div className="kpis stagger">
            <Kpi to="/app/incidents" icon="check" tone="success" label="Atendidas a tiempo" value={stats.data.slaMet} suffix="%" sub={`de ${stats.data.done.toLocaleString('es-PE')} fallas resueltas`} />
            <Kpi to="/app/changes?status=submitted" icon="change" tone="info" label="Actualizaciones por aprobar" value={stats.data.cab} />
            <Kpi to="/app/requests?status=pending_approval" icon="request" tone="warning" label="Pedidos por aprobar" value={stats.data.approvals} />
            <Kpi to="/app/problems" icon="problem" tone="accent" label="Problemas recurrentes abiertos" value={stats.data.investigating} />
            <Kpi to="/app/cmdb?status=down" icon="cmdb" tone="danger" label="Equipos o sistemas caídos" value={stats.data.down} alert={stats.data.down > 0} />
          </div>

          <div className="grid-2">
            <section className="card">
              <div className="card-head">
                <h2>Fallas abiertas por prioridad</h2>
              </div>
              <div className="card-body">
                <Bars
                  rows={(['P1', 'P2', 'P3', 'P4'] as Priority[]).map((p, i) => [<PriorityBadge value={p} key={p} />, stats.data!.byPrio[i], ['#c4312b', '#f2994a', '#e0b341', '#9aa8ab'][i]])}
                />
              </div>
            </section>
            <section className="card">
              <div className="card-head">
                <h2>Fallas abiertas por estado</h2>
              </div>
              <div className="card-body">
                <Bars rows={OPEN.map((s, i) => [<StatusBadge map={INCIDENT_STATUS} value={s} key={s} />, stats.data!.byStatus[i], ['#2563c9', '#6d3fc4', '#a35d00'][i]])} />
              </div>
            </section>
          </div>

          <div className="grid-3-1">
            <section className="card">
              <div className="card-head">
                <h2>Últimas fallas reportadas</h2>
                <Link to="/app/incidents">Ver todos</Link>
              </div>
              <div className="table-wrap">
                <table className="table">
                  <tbody>
                    {stats.data.recent.map((i) => (
                      <tr key={i.id} onClick={() => nav(`/app/incidents/${i.id}`)}>
                        <td style={{ width: 50 }}>
                          <PriorityBadge value={i.priority} />
                        </td>
                        <td className="title-cell">
                          <strong>{i.title}</strong>
                          <span className="key">{i.key}</span> <span className="muted">· {fromNow(i.created_at)}</span>
                        </td>
                        <td className="right">
                          <StatusBadge map={INCIDENT_STATUS} value={i.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="card">
              <div className="card-head">
                <h2>Actualizaciones de los próximos 7 días</h2>
                <Link to="/app/changes/calendar">Calendario</Link>
              </div>
              <div className="card-body col gap">
                {stats.data.upcoming.length === 0 && <Empty title="Sin actualizaciones programadas" icon="calendar" />}
                {stats.data.upcoming.map((c) => (
                  <Link key={c.id} to={`/app/changes/${c.id}`} className="col gap-xs" style={{ color: 'inherit' }}>
                    <div className="row between gap-sm">
                      <span className="key mono" style={{ color: 'var(--primary)', fontWeight: 600, fontSize: 12.5 }}>
                        {c.key}
                      </span>
                      <StatusBadge map={CHANGE_STATUS} value={c.status} />
                    </div>
                    <strong style={{ fontSize: 14 }}>{c.title}</strong>
                    <span className="muted" style={{ fontSize: 12.5 }}>
                      {fmtDateTime(c.planned_start)} · Riesgo <StatusBadge map={RISK} value={c.risk} />
                    </span>
                  </Link>
                ))}
              </div>
            </section>
          </div>
        </>
      )}
    </>
  );
}

function Kpi({ to, icon, tone, label, value, sub, alert, suffix = '' }: { to: string; icon: IconName; tone: string; label: string; value: number; sub?: string; alert?: boolean; suffix?: string }) {
  return (
    <Link to={to} className={`card kpi ${alert ? 'alert' : ''}`}>
      <span className="label">
        <span className={`ic tone-${tone}`}>
          <Icon name={icon} size={16} />
        </span>
        {label}
      </span>
      <span className="value">
        <CountUp value={value} format={(n) => n.toLocaleString('es-PE') + suffix} />
      </span>
      {sub && <span className="sub">{sub}</span>}
    </Link>
  );
}

function Bars({ rows }: { rows: [React.ReactNode, number, string][] }) {
  const max = Math.max(1, ...rows.map((r) => r[1]));
  // Montar en 0 y crecer en el siguiente frame.
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(id);
  }, []);
  return (
    <div className="bars">
      {rows.map(([label, v, color], i) => (
        <div className="bar-row" key={i}>
          <span>{label}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: ready ? `${(v / max) * 100}%` : '0%', background: color, display: 'block', transitionDelay: `${i * 90}ms` }} />
          </span>
          <strong className="right">
            <CountUp value={v} />
          </strong>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ Portal del usuario final

function PortalHome() {
  const me = useMe();
  const nav = useNavigate();
  const data = useAsync(
    () =>
      Promise.all([
        incidentService.list({ sort_by: 'created_at', limit: 5 }),
        requestService.list({ sort_by: 'created_at', limit: 5 }),
      ]),
    [],
  );

  return (
    <>
      <section className="portal-hero">
        <span className="eyebrow">Mesa de ayuda de TI · {me.tenant.name}</span>
        <h1>Hola, {me.full_name.split(' ')[0]}. ¿En qué podemos ayudarte?</h1>
        <p>Cuéntanos qué no funciona o pide lo que necesitas. Te avisaremos de cada avance.</p>
      </section>

      <div className="quick-actions stagger">
        <Link to="/app/incidents?new=1" className="card quick">
          <span className="ic tone-danger">
            <Icon name="incident" size={22} />
          </span>
          <div>
            <strong>Algo no funciona</strong>
            <small>Correo, impresora, sistema, internet…</small>
          </div>
        </Link>
        <Link to="/app/catalog" className="card quick">
          <span className="ic">
            <Icon name="catalog" size={22} />
          </span>
          <div>
            <strong>Necesito algo</strong>
            <small>Un programa, un acceso, un equipo…</small>
          </div>
        </Link>
        <Link to="/app/requests" className="card quick">
          <span className="ic tone-accent">
            <Icon name="request" size={22} />
          </span>
          <div>
            <strong>Ver mis pedidos</strong>
            <small>En qué va cada uno</small>
          </div>
        </Link>
      </div>

      {data.error && <ErrorBox error={data.error} onRetry={data.reload} />}
      {data.loading && !data.data && <Spinner />}
      {data.data && (
        <div className="grid-2">
          <section className="card">
            <div className="card-head">
              <h2>Fallas que reporté</h2>
              <Link to="/app/incidents">Ver todos</Link>
            </div>
            {data.data[0].data.length === 0 ? (
              <Empty title="No has reportado fallas" icon="check" />
            ) : (
              <table className="table">
                <tbody>
                  {data.data[0].data.map((i) => (
                    <tr key={i.id} onClick={() => nav(`/app/incidents/${i.id}`)}>
                      <td className="title-cell">
                        <strong>{i.title}</strong>
                        <span className="key">{i.key}</span> <span className="muted">· {fromNow(i.created_at)}</span>
                      </td>
                      <td className="right">
                        <StatusBadge map={INCIDENT_STATUS} value={i.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          <section className="card">
            <div className="card-head">
              <h2>Mis pedidos</h2>
              <Link to="/app/requests">Ver todas</Link>
            </div>
            {data.data[1].data.length === 0 ? (
              <Empty title="Aún no tienes pedidos" icon="request" />
            ) : (
              <table className="table">
                <tbody>
                  {data.data[1].data.map((r) => (
                    <tr key={r.id} onClick={() => nav(`/app/requests/${r.id}`)}>
                      <td className="title-cell">
                        <strong>{r.catalog_item_name}</strong>
                        <span className="key">{r.key}</span> <span className="muted">· {fromNow(r.created_at)}</span>
                      </td>
                      <td className="right">
                        <StatusBadge map={REQUEST_STATUS} value={r.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      )}
    </>
  );
}
