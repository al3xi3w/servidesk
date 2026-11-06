import { useState } from 'react';
import { useMe } from '../../auth/AuthContext';
import { useLiveRefresh } from '../../lib/live';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { changeService, cmdbService, incidentService, problemService } from '../../api';
import { Icon } from '../../components/Icon';
import { Stepper } from '../../components/Stepper';
import { Empty, ErrorBox, Field, KeyValue, Modal, PageHeader, PriorityBadge, Spinner, StatusBadge, useApiErrorToast, useToast } from '../../components/ui';
import { CHANGE_STATUS, CI_STATUS, fmtDateTime, fromNow, INCIDENT_STATUS, PROBLEM_STATUS } from '../../lib/format';
import { useAsync, useDebounced, useUsers } from '../../lib/hooks';
import type { ProblemDetail as TProblem, ProblemStatus } from '../../types/api';

const FLOW: ProblemStatus[] = ['new', 'investigating', 'known_error', 'resolved', 'closed'];

export default function ProblemDetail() {
  const { id = '' } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const onError = useApiErrorToast();
  const prb = useAsync(() => problemService.get(id), [id]);
  const incidents = useAsync(() => incidentService.list({ problem_id: id, limit: 50, sort_by: 'created_at' }), [id, prb.data?.incident_ids.length]);
  const related = useAsync(async () => {
    const p = prb.data;
    if (!p) return null;
    const [ci, change] = await Promise.all([
      p.ci_id ? cmdbService.get(p.ci_id).catch(() => null) : null,
      p.fix_change_id ? changeService.get(p.fix_change_id).catch(() => null) : null,
    ]);
    return { ci, change };
  }, [prb.data?.ci_id, prb.data?.fix_change_id]);
  const me = useMe();
  useLiveRefresh(me.tenant.id, prb.reload, incidents.reload);
  const users = useUsers([prb.data?.owner_id]);

  const [rootCause, setRootCause] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [linking, setLinking] = useState(false);
  const [busy, setBusy] = useState(false);

  if (prb.error) return <ErrorBox error={prb.error} onRetry={prb.reload} />;
  if (!prb.data) return <Spinner />;
  const p = prb.data;
  const rc = rootCause ?? p.root_cause ?? '';

  async function run(fn: () => Promise<TProblem>, msg: string) {
    setBusy(true);
    try {
      prb.setData(await fn());
      toast(msg);
      return true;
    } catch (e) {
      onError(e);
      return false;
    } finally {
      setBusy(false);
    }
  }

  const actions: [string, () => void, string][] = [];
  if (p.status === 'new') actions.push(['Buscar la causa', () => run(() => problemService.changeStatus(p.id, { status: 'investigating' }), 'Búsqueda de la causa iniciada'), 'btn-primary']);
  if (p.status === 'investigating') actions.push(['Publicar solución temporal', () => setPublishing(true), 'btn-ghost']);
  if (p.status === 'investigating' || p.status === 'known_error')
    actions.push(['Resolver', () => run(() => problemService.changeStatus(p.id, { status: 'resolved' }), 'Problema resuelto'), 'btn-success']);
  if (p.status === 'resolved') {
    actions.push(['Volver a analizar', () => run(() => problemService.changeStatus(p.id, { status: 'investigating' }), 'Se volvió a analizar'), 'btn-ghost']);
    actions.push(['Cerrar', () => run(() => problemService.changeStatus(p.id, { status: 'closed' }), 'Problema cerrado'), 'btn-primary']);
  }

  return (
    <>
      <PageHeader
        back={
          <Link to="/app/problems" className="back-link">
            <Icon name="back" size={14} /> Problemas recurrentes
          </Link>
        }
        title={
          <span className="row gap-sm wrap">
            <span className="mono" style={{ color: 'var(--primary)', fontSize: 18 }}>
              {p.key}
            </span>
            {p.title}
          </span>
        }
        subtitle={
          <span className="row gap-sm wrap">
            <PriorityBadge value={p.priority} />
            <StatusBadge map={PROBLEM_STATUS} value={p.status} />
            <span>Abierto {fromNow(p.created_at)}</span>
          </span>
        }
        actions={actions.map(([label, fn, cls]) => (
          <button key={label} className={`btn ${cls}`} disabled={busy} onClick={fn}>
            {label}
          </button>
        ))}
      />

      <section className="card card-pad">
        <Stepper steps={FLOW.map((s) => [s, PROBLEM_STATUS[s][0]])} current={p.status} />
      </section>

      <div className="grid-3-1">
        <div className="col gap-lg">
          <section className="card">
            <div className="card-head">
              <h2>Descripción</h2>
            </div>
            <div className="card-body">
              <p style={{ whiteSpace: 'pre-wrap' }}>{p.description || <span className="muted">Sin descripción.</span>}</p>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Causa de fondo</h2>
            </div>
            <div className="card-body col gap-sm">
              <textarea
                className="textarea"
                value={rc}
                disabled={p.status === 'closed'}
                onChange={(e) => setRootCause(e.target.value)}
                placeholder="¿Por qué se repite la falla? Es necesario para marcar el problema como resuelto."
              />
              {rootCause !== null && rootCause !== (p.root_cause ?? '') && (
                <div className="row gap-sm">
                  <button className="btn btn-primary btn-sm" disabled={busy} onClick={async () => (await run(() => problemService.update(p.id, { root_cause: rootCause || null }), 'Causa guardada')) && setRootCause(null)}>
                    Guardar causa
                  </button>
                  <button className="btn btn-ghost btn-sm" onClick={() => setRootCause(null)}>
                    Descartar
                  </button>
                </div>
              )}
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Fallas relacionadas ({incidents.data?.meta.total ?? p.incident_ids.length})</h2>
              {p.status !== 'closed' && (
                <button className="link-btn" onClick={() => setLinking(true)}>
                  Relacionar fallas
                </button>
              )}
            </div>
            {incidents.data?.data.length === 0 ? (
              <Empty title="Sin fallas relacionadas" icon="link" />
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <tbody>
                    {incidents.data?.data.map((i) => (
                      <tr key={i.id} onClick={() => nav(`/app/incidents/${i.id}`)}>
                        <td className="key">{i.key}</td>
                        <td className="title-cell">
                          <strong>{i.title}</strong>
                        </td>
                        <td>
                          <PriorityBadge value={i.priority} />
                        </td>
                        <td className="right">
                          <StatusBadge map={INCIDENT_STATUS} value={i.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>

        <aside className="col gap-lg">
          {p.known_error && (
            <section className="card card-pad col gap-sm" style={{ borderColor: '#edc98a', background: 'var(--warning-soft)' }}>
              <strong className="row gap-sm" style={{ color: 'var(--warning)' }}>
                <Icon name="book" size={16} /> Solución temporal publicada
              </strong>
              <p style={{ fontSize: 14 }}>
                <b>Qué se ve:</b> {p.known_error.symptom}
              </p>
              <p style={{ fontSize: 14 }}>
                <b>Qué hacer mientras tanto:</b> {p.known_error.workaround}
              </p>
              <small className="muted">{fmtDateTime(p.known_error.published_at)}</small>
            </section>
          )}
          <section className="card">
            <div className="card-head">
              <h2>Detalles</h2>
            </div>
            <div className="card-body" style={{ paddingTop: 6, paddingBottom: 6 }}>
              <KeyValue
                items={[
                  ['Responsable', p.owner_id ? (users.get(p.owner_id)?.full_name ?? '…') : '—'],
                  [
                    'Equipo o sistema',
                    related.data?.ci ? (
                      <Link to={`/app/cmdb/${related.data.ci.id}`} className="row gap-xs">
                        {related.data.ci.name} <StatusBadge map={CI_STATUS} value={related.data.ci.status} />
                      </Link>
                    ) : (
                      '—'
                    ),
                  ],
                  [
                    'Actualización que lo corrige',
                    related.data?.change ? (
                      <Link to={`/app/changes/${related.data.change.id}`} className="col">
                        <span>
                          {related.data.change.key} <StatusBadge map={CHANGE_STATUS} value={related.data.change.status} />
                        </span>
                      </Link>
                    ) : p.status !== 'closed' ? (
                      <Link to={`/app/changes?new=1&problem=${p.id}`}>Planificar actualización</Link>
                    ) : (
                      '—'
                    ),
                  ],
                  ['Creado', fmtDateTime(p.created_at)],
                ]}
              />
            </div>
          </section>
        </aside>
      </div>

      {publishing && (
        <PublishKnownError
          busy={busy}
          onClose={() => setPublishing(false)}
          onSubmit={async (symptom, workaround) => (await run(() => problemService.publishKnownError(p.id, { symptom, workaround }), 'Solución temporal publicada')) && setPublishing(false)}
        />
      )}
      {linking && (
        <LinkIncidents
          exclude={p.incident_ids}
          busy={busy}
          onClose={() => setLinking(false)}
          onSubmit={async (ids) => (await run(() => problemService.linkIncidents(p.id, { incident_ids: ids }), `${ids.length} falla(s) relacionadas`)) && setLinking(false)}
        />
      )}
    </>
  );
}

function PublishKnownError({ busy, onClose, onSubmit }: { busy: boolean; onClose: () => void; onSubmit: (s: string, w: string) => void }) {
  const [symptom, setSymptom] = useState('');
  const [workaround, setWorkaround] = useState('');
  return (
    <Modal
      title="Publicar solución temporal"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={busy || symptom.trim().length < 5 || workaround.trim().length < 5} onClick={() => onSubmit(symptom.trim(), workaround.trim())}>
            Publicar
          </button>
        </>
      }
    >
      <p className="muted">Los técnicos la verán en las fallas relacionadas y se agregará como comentario para los afectados.</p>
      <Field label="¿Qué ve la persona afectada?">
        <textarea className="textarea" value={symptom} onChange={(e) => setSymptom(e.target.value)} />
      </Field>
      <Field label="¿Qué hacer mientras se corrige?">
        <textarea className="textarea" value={workaround} onChange={(e) => setWorkaround(e.target.value)} />
      </Field>
    </Modal>
  );
}

function LinkIncidents({ exclude, busy, onClose, onSubmit }: { exclude: string[]; busy: boolean; onClose: () => void; onSubmit: (ids: string[]) => void }) {
  const [q, setQ] = useState('');
  const dq = useDebounced(q);
  const [sel, setSel] = useState<string[]>([]);
  const list = useAsync(() => incidentService.list({ search: dq.length >= 2 ? dq : undefined, status: ['new', 'in_progress', 'on_hold', 'resolved'], limit: 15 }), [dq]);
  return (
    <Modal
      title="Relacionar fallas"
      onClose={onClose}
      wide
      footer={
        <>
          <span className="muted grow">{sel.length} seleccionados</span>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={busy || !sel.length} onClick={() => onSubmit(sel)}>
            Relacionar
          </button>
        </>
      }
    >
      <div className="search">
        <Icon name="search" size={16} />
        <input className="input" autoFocus placeholder="Buscar por número o título…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {list.loading && !list.data ? (
        <Spinner />
      ) : (
        <div className="col gap-xs">
          {list.data?.data
            .filter((i) => !exclude.includes(i.id))
            .map((i) => (
              <label key={i.id} className="check rel">
                <input type="checkbox" checked={sel.includes(i.id)} onChange={(e) => setSel(e.target.checked ? [...sel, i.id] : sel.filter((x) => x !== i.id))} />
                <span className="key mono" style={{ color: 'var(--primary)', fontWeight: 600 }}>
                  {i.key}
                </span>
                <span className="grow">{i.title}</span>
                <PriorityBadge value={i.priority} />
              </label>
            ))}
        </div>
      )}
    </Modal>
  );
}
