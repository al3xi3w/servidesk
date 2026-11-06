import { useState } from 'react';
import { useLiveRefresh } from '../../lib/live';
import { Link, useParams } from 'react-router-dom';
import { cmdbService, incidentService, problemService } from '../../api';
import { useMe } from '../../auth/AuthContext';
import { Icon } from '../../components/Icon';
import { AgentSelect, LevelSelect, PriorityMatrix, TeamSelect, useTeams } from '../../components/pickers';
import { Stepper } from '../../components/Stepper';
import { Avatar, Badge, ErrorBox, Field, KeyValue, Modal, PageHeader, PriorityBadge, Spinner, StatusBadge, useApiErrorToast, useToast } from '../../components/ui';
import { CHANNEL, CI_STATUS, fmtDateTime, fromNow, INCIDENT_STATUS, LEVEL } from '../../lib/format';
import { useAsync, useUsers } from '../../lib/hooks';
import type { Incident, IncidentStatus, Level } from '../../types/api';

const FLOW: IncidentStatus[] = ['new', 'in_progress', 'resolved', 'closed'];

/** Transiciones permitidas por el contrato (sección 7). */
const NEXT: Record<IncidentStatus, IncidentStatus[]> = {
  new: ['in_progress', 'on_hold', 'resolved'],
  in_progress: ['on_hold', 'resolved'],
  on_hold: ['in_progress', 'resolved'],
  resolved: ['closed', 'in_progress'],
  closed: [],
};

const ACTION_LABEL: Partial<Record<IncidentStatus, string>> = {
  in_progress: 'Iniciar trabajo',
  on_hold: 'Poner en espera',
  resolved: 'Resolver',
  closed: 'Cerrar',
};

export default function IncidentDetail() {
  const { id = '' } = useParams();
  const me = useMe();
  const isStaff = me.role !== 'customer';
  const toast = useToast();
  const onError = useApiErrorToast();

  const inc = useAsync(() => incidentService.get(id), [id]);
  const comments = useAsync(() => incidentService.listComments(id, { limit: 100 }), [id]);
  const related = useAsync(async () => {
    const i = inc.data;
    if (!i || !isStaff) return null;
    const [ci, problem] = await Promise.all([
      i.ci_id ? cmdbService.get(i.ci_id).catch(() => null) : null,
      i.problem_id ? problemService.get(i.problem_id).catch(() => null) : null,
    ]);
    return { ci, problem };
  }, [inc.data?.ci_id, inc.data?.problem_id]);
  useLiveRefresh(me.tenant.id, inc.reload, comments.reload);
  const teams = useTeams(isStaff);
  const users = useUsers([inc.data?.reporter_id, inc.data?.assignee_id, ...(comments.data?.data.map((c) => c.author_id) ?? [])], isStaff);

  const [resolving, setResolving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState('');
  const [internal, setInternal] = useState(false);
  const [busy, setBusy] = useState(false);

  if (inc.error) return <ErrorBox error={inc.error} onRetry={inc.reload} />;
  if (!inc.data) return <Spinner />;
  const i = inc.data;

  const nameOf = (uid: string | null) => {
    if (!uid) return null;
    if (uid === me.id) return `${me.full_name} (tú)`;
    return users.get(uid)?.full_name ?? (isStaff ? '…' : 'Equipo de soporte');
  };

  async function move(to: IncidentStatus, comment?: string) {
    setBusy(true);
    try {
      const updated = await incidentService.changeStatus(i.id, { status: to, ...(comment ? { comment } : {}) });
      inc.setData(updated);
      comments.reload();
      toast(`Estado actualizado: ${INCIDENT_STATUS[to][0]}`);
      setResolving(false);
    } catch (e) {
      onError(e);
      inc.reload();
    } finally {
      setBusy(false);
    }
  }

  async function patch(body: Parameters<typeof incidentService.update>[1], msg: string) {
    setBusy(true);
    try {
      inc.setData(await incidentService.update(i.id, body));
      toast(msg);
      setEditing(false);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  async function addComment() {
    setBusy(true);
    try {
      await incidentService.addComment(i.id, isStaff ? { body, internal } : { body });
      setBody('');
      setInternal(false);
      comments.reload();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  const actions = isStaff ? NEXT[i.status] : i.status === 'resolved' ? (['closed', 'in_progress'] as IncidentStatus[]) : [];
  const open = i.status !== 'resolved' && i.status !== 'closed';
  const flowCurrent = i.status === 'on_hold' ? 'in_progress' : i.status;

  return (
    <>
      <PageHeader
        back={
          <Link to="/app/incidents" className="back-link">
            <Icon name="back" size={14} /> Fallas
          </Link>
        }
        title={
          <span className="row gap-sm wrap">
            <span className="mono" style={{ color: 'var(--primary)', fontSize: 18 }}>
              {i.key}
            </span>
            {i.title}
          </span>
        }
        subtitle={
          <span className="row gap-sm wrap">
            <PriorityBadge value={i.priority} />
            <StatusBadge map={INCIDENT_STATUS} value={i.status} />
            {i.channel === 'auto' && <Badge tone="accent">Detectada automáticamente</Badge>}
            <span>
              Reportado {fromNow(i.created_at)} vía {CHANNEL[i.channel].toLowerCase()}
            </span>
          </span>
        }
        actions={
          <>
            {isStaff && open && i.assignee_id !== me.id && (
              <button className="btn btn-ghost" disabled={busy} onClick={() => patch({ assignee_id: me.id }, 'Falla asignada a ti')}>
                Asignarme
              </button>
            )}
            {actions.map((to) => (
              <button
                key={to}
                className={`btn ${to === 'resolved' ? 'btn-success' : to === 'closed' ? 'btn-primary' : 'btn-ghost'}`}
                disabled={busy}
                onClick={() => (to === 'resolved' ? setResolving(true) : move(to))}
              >
                {!isStaff && to === 'in_progress' ? 'Reabrir: no se solucionó' : !isStaff && to === 'closed' ? 'Confirmar solución' : i.status === 'resolved' && to === 'in_progress' ? 'Reabrir' : ACTION_LABEL[to]}
              </button>
            ))}
          </>
        }
      />

      <section className="card card-pad">
        <Stepper steps={FLOW.map((s) => [s, INCIDENT_STATUS[s][0]])} current={flowCurrent} />
        {i.status === 'on_hold' && (
          <p className="muted" style={{ marginTop: 10, fontSize: 13 }}>
            En espera: el plazo sigue corriendo hasta que se retome.
          </p>
        )}
      </section>

      <div className="grid-3-1">
        <div className="col gap-lg">
          <section className="card">
            <div className="card-head">
              <h2>Descripción</h2>
            </div>
            <div className="card-body">
              <p style={{ whiteSpace: 'pre-wrap' }}>{i.description || <span className="muted">Sin descripción.</span>}</p>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Actividad</h2>
              <span className="muted" style={{ fontSize: 13 }}>
                {comments.data?.meta.total ?? 0} comentarios
              </span>
            </div>
            <div className="card-body timeline">
              {comments.loading && !comments.data && <Spinner />}
              {comments.data?.data.length === 0 && <p className="muted">Todavía no hay comentarios.</p>}
              {comments.data?.data.map((c) => {
                const name = nameOf(c.author_id) ?? '—';
                return (
                  <div className="comment" key={c.id}>
                    <Avatar name={name} size={32} />
                    <div className={`comment-body ${c.internal ? 'internal' : ''}`}>
                      <div className="comment-meta">
                        <strong>{name}</strong>
                        <span title={fmtDateTime(c.created_at)}>{fromNow(c.created_at)}</span>
                        {c.internal && <Badge tone="warning">Nota interna</Badge>}
                      </div>
                      <p style={{ whiteSpace: 'pre-wrap' }}>{c.body}</p>
                    </div>
                  </div>
                );
              })}
              {i.status !== 'closed' && (
                <div className="composer">
                  <textarea className="textarea" placeholder={isStaff ? 'Escribe una actualización o nota…' : 'Agrega información para el equipo de soporte…'} value={body} onChange={(e) => setBody(e.target.value)} />
                  <div className="row between gap-sm wrap">
                    {isStaff ? (
                      <label className="check">
                        <input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /> Nota interna (no la ve el usuario)
                      </label>
                    ) : (
                      <span />
                    )}
                    <button className="btn btn-primary btn-sm" disabled={busy || !body.trim()} onClick={addComment}>
                      Comentar
                    </button>
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>

        <aside className="col gap-lg">
          <SlaBox incident={i} />
          <section className="card">
            <div className="card-head">
              <h2>Detalles</h2>
              {isStaff && i.status !== 'closed' && (
                <button className="link-btn" onClick={() => setEditing(true)}>
                  Editar
                </button>
              )}
            </div>
            <div className="card-body" style={{ paddingTop: 6, paddingBottom: 6 }}>
              <KeyValue
                items={[
                  ['Alcance', LEVEL[i.impact]],
                  ['Urgencia', LEVEL[i.urgency]],
                  ['Reportado por', nameOf(i.reporter_id)],
                  ['Asignado a', nameOf(i.assignee_id) ?? <span className="muted">Sin asignar</span>],
                  ...(isStaff
                    ? ([
                        ['Área de TI', teams.find((t) => t.id === i.team_id)?.name ?? <span className="muted">—</span>],
                        [
                          'Equipo o sistema',
                          related.data?.ci ? (
                            <Link to={`/app/cmdb/${related.data.ci.id}`} className="row gap-xs">
                              {related.data.ci.name} <StatusBadge map={CI_STATUS} value={related.data.ci.status} />
                            </Link>
                          ) : (
                            <span className="muted">—</span>
                          ),
                        ],
                        [
                          'Problema recurrente',
                          related.data?.problem ? (
                            <Link to={`/app/problems/${related.data.problem.id}`}>
                              {related.data.problem.key} · {related.data.problem.title}
                            </Link>
                          ) : (
                            <span className="muted">—</span>
                          ),
                        ],
                      ] as [string, React.ReactNode][])
                    : []),
                  ['Creado', fmtDateTime(i.created_at)],
                  ['Resuelto', fmtDateTime(i.resolved_at)],
                ]}
              />
            </div>
          </section>
          {related.data?.problem?.known_error && (
            <section className="card card-pad col gap-sm" style={{ borderColor: '#edc98a', background: 'var(--warning-soft)' }}>
              <strong className="row gap-sm" style={{ color: 'var(--warning)' }}>
                <Icon name="book" size={16} /> Solución temporal conocida
              </strong>
              <p style={{ fontSize: 14 }}>
                <b>Mientras se corrige:</b> {related.data.problem.known_error.workaround}
              </p>
            </section>
          )}
        </aside>
      </div>

      {resolving && <ResolveModal busy={busy} onClose={() => setResolving(false)} onResolve={(c) => move('resolved', c)} />}
      {editing && <EditModal incident={i} busy={busy} onClose={() => setEditing(false)} onSave={(b) => patch(b, 'Falla actualizada')} />}
    </>
  );
}

function SlaBox({ incident: i }: { incident: Incident }) {
  const open = i.status !== 'resolved' && i.status !== 'closed';
  const cls = !open ? (i.sla_breached ? 'late' : 'done') : i.sla_breached ? 'late' : '';
  return (
    <div className={`sla-box ${cls}`}>
      <Icon name="clock" size={22} />
      <div>
        <strong>{open ? (i.sla_breached ? 'Plazo vencido' : `Plazo: vence ${fromNow(i.sla_due_at)}`) : i.sla_breached ? 'Resuelta fuera de plazo' : 'Resuelta a tiempo'}</strong>
        <small>
          Prioridad {i.priority}: atender antes del {fmtDateTime(i.sla_due_at)}
        </small>
      </div>
    </div>
  );
}

function ResolveModal({ busy, onClose, onResolve }: { busy: boolean; onClose: () => void; onResolve: (comment: string) => void }) {
  const [comment, setComment] = useState('');
  return (
    <Modal
      title="Resolver falla"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-success" disabled={busy || !comment.trim()} onClick={() => onResolve(comment.trim())}>
            Marcar como resuelto
          </button>
        </>
      }
    >
      <Field label="Nota de resolución" hint="Es obligatoria y la verá el usuario.">
        <textarea className="textarea" autoFocus value={comment} onChange={(e) => setComment(e.target.value)} placeholder="¿Qué se hizo para restablecer el servicio?" />
      </Field>
    </Modal>
  );
}

function EditModal({ incident: i, busy, onClose, onSave }: { incident: Incident; busy: boolean; onClose: () => void; onSave: (b: Parameters<typeof incidentService.update>[1]) => void }) {
  const [impact, setImpact] = useState<Level>(i.impact);
  const [urgency, setUrgency] = useState<Level>(i.urgency);
  const [team, setTeam] = useState(i.team_id);
  const [assignee, setAssignee] = useState(i.assignee_id);
  return (
    <Modal
      title={`Editar ${i.key}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={busy} onClick={() => onSave({ impact, urgency, team_id: team, assignee_id: assignee })}>
            Guardar
          </button>
        </>
      }
    >
      <div className="form-grid">
        <Field label="Alcance">
          <LevelSelect value={impact} onChange={setImpact} />
        </Field>
        <Field label="Urgencia">
          <LevelSelect value={urgency} onChange={setUrgency} />
        </Field>
        <Field label="Área de TI">
          <TeamSelect value={team} onChange={setTeam} />
        </Field>
        <Field label="Asignado a">
          <AgentSelect value={assignee} onChange={setAssignee} />
        </Field>
      </div>
      <PriorityMatrix impact={impact} urgency={urgency} />
    </Modal>
  );
}
