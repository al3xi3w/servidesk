import { useState } from 'react';
import { useLiveRefresh } from '../../lib/live';
import { Link, useParams } from 'react-router-dom';
import { changeService, cmdbService, problemService } from '../../api';
import { useMe } from '../../auth/AuthContext';
import { Icon } from '../../components/Icon';
import { Stepper } from '../../components/Stepper';
import { Avatar, Badge, ErrorBox, Field, KeyValue, Modal, PageHeader, Spinner, StatusBadge, useApiErrorToast, useToast } from '../../components/ui';
import { CHANGE_STATUS, CHANGE_TYPE, CI_STATUS, fmtDateTime, fromNow, RISK } from '../../lib/format';
import { useAsync, useUsers } from '../../lib/hooks';
import type { ChangeDetail as TChange, ChangeStatus } from '../../types/api';
import { ChangeForm } from './ChangeForm';

const FLOW: ChangeStatus[] = ['draft', 'submitted', 'approved', 'scheduled', 'implemented'];

export default function ChangeDetail() {
  const { id = '' } = useParams();
  const me = useMe();
  const toast = useToast();
  const onError = useApiErrorToast();
  const chg = useAsync(() => changeService.get(id), [id]);
  const extra = useAsync(async () => {
    const c = chg.data;
    if (!c) return null;
    const [cis, problem] = await Promise.all([
      Promise.all(c.cis.map((x) => cmdbService.get(x.ci_id).catch(() => null))),
      c.problem_id ? problemService.get(c.problem_id).catch(() => null) : null,
    ]);
    return { cis, problem };
  }, [chg.data?.id, chg.data?.cis.length]);
  const users = useUsers([chg.data?.requester_id, ...(chg.data?.approvals.map((a) => a.approver_id) ?? [])]);
  useLiveRefresh(me.tenant.id, chg.reload);
  const [editing, setEditing] = useState(false);
  const [deciding, setDeciding] = useState<'approve' | 'reject' | null>(null);
  const [busy, setBusy] = useState(false);

  if (chg.error) return <ErrorBox error={chg.error} onRetry={chg.reload} />;
  if (!chg.data) return <Spinner />;
  const c = chg.data;

  async function run(fn: () => Promise<TChange>, msg: (c: TChange) => string) {
    setBusy(true);
    try {
      const updated = await fn();
      chg.setData(updated);
      toast(msg(updated));
      setDeciding(null);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }
  const move = (status: Parameters<typeof changeService.changeStatus>[1]['status'], label: string) =>
    run(() => changeService.changeStatus(c.id, { status }), (u) => (status === 'submitted' && u.status === 'approved' ? 'Tarea de rutina: aprobada automáticamente' : label));

  const isAdmin = me.role === 'admin';
  const flowIdx = c.status === 'rejected' ? 'submitted' : c.status === 'failed' ? 'implemented' : c.status;

  return (
    <>
      <PageHeader
        back={
          <Link to="/app/changes" className="back-link">
            <Icon name="back" size={14} /> Actualizaciones
          </Link>
        }
        title={
          <span className="row gap-sm wrap">
            <span className="mono" style={{ color: 'var(--primary)', fontSize: 18 }}>
              {c.key}
            </span>
            {c.title}
          </span>
        }
        subtitle={
          <span className="row gap-sm wrap">
            <StatusBadge map={CHANGE_STATUS} value={c.status} />
            <Badge tone={c.type === 'emergency' ? 'danger' : 'info'}>{CHANGE_TYPE[c.type]}</Badge>
            <span>
              Riesgo <StatusBadge map={RISK} value={c.risk} />
            </span>
          </span>
        }
        actions={
          <>
            {c.status === 'draft' && (
              <>
                <button className="btn btn-ghost" onClick={() => setEditing(true)}>
                  Editar
                </button>
                <button className="btn btn-primary" disabled={busy} onClick={() => move('submitted', 'Enviada al comité para su aprobación')}>
                  {c.type === 'standard' ? 'Enviar (se aprueba sola)' : 'Enviar al comité'}
                </button>
              </>
            )}
            {c.status === 'submitted' && isAdmin && (
              <>
                <button className="btn btn-danger" disabled={busy} onClick={() => setDeciding('reject')}>
                  Rechazar
                </button>
                <button className="btn btn-success" disabled={busy} onClick={() => setDeciding('approve')}>
                  Aprobar
                </button>
              </>
            )}
            {c.status === 'submitted' && !isAdmin && <Badge tone="info">Esperando decisión del comité</Badge>}
            {c.status === 'rejected' && (
              <button className="btn btn-ghost" disabled={busy} onClick={() => move('draft', 'Devuelto a borrador para corregir')}>
                Volver a borrador
              </button>
            )}
            {c.status === 'approved' && (
              <button className="btn btn-primary" disabled={busy} onClick={() => move('scheduled', 'Actualización programada')}>
                Programar
              </button>
            )}
            {c.status === 'scheduled' && (
              <>
                <button className="btn btn-danger" disabled={busy} onClick={() => move('failed', 'Actualización marcada como fallida')}>
                  Salió mal
                </button>
                <button className="btn btn-success" disabled={busy} onClick={() => move('implemented', 'Actualización implementada')}>
                  Marcar como hecha
                </button>
              </>
            )}
          </>
        }
      />

      <section className="card card-pad">
        <Stepper
          steps={FLOW.map((s) => [s, s === 'submitted' && c.status === 'rejected' ? 'Rechazado' : s === 'implemented' && c.status === 'failed' ? 'Fallido' : CHANGE_STATUS[s][0]])}
          current={flowIdx}
          failed={c.status === 'rejected' || c.status === 'failed'}
        />
      </section>

      <div className="grid-3-1">
        <div className="col gap-lg">
          <section className="card">
            <div className="card-head">
              <h2>Descripción</h2>
            </div>
            <div className="card-body col gap">
              <p style={{ whiteSpace: 'pre-wrap' }}>{c.description || <span className="muted">Sin descripción.</span>}</p>
              <div>
                <h3 style={{ fontSize: 14, marginBottom: 6 }}>Plan B: cómo volver atrás</h3>
                <p style={{ whiteSpace: 'pre-wrap' }} className={c.rollback_plan ? '' : 'muted'}>
                  {c.rollback_plan || 'No definido.'}
                </p>
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Equipos y sistemas que se actualizan</h2>
            </div>
            <div className="card-body rel-list">
              {c.cis.length === 0 && <p className="muted">Ninguno registrado.</p>}
              {c.cis.map((x, n) => {
                const ci = extra.data?.cis[n];
                return (
                  <Link key={x.ci_id + n} to={`/app/cmdb/${x.ci_id}`} className="rel" style={{ color: 'inherit' }}>
                    <Icon name="server" size={16} />
                    <span className="grow">{ci?.name ?? '…'}</span>
                    {x.new_version && <Badge tone="info">→ v{x.new_version}</Badge>}
                    {ci && <StatusBadge map={CI_STATUS} value={ci.status} />}
                  </Link>
                );
              })}
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Decisión del comité</h2>
            </div>
            <div className="card-body timeline">
              {c.approvals.length === 0 && <p className="muted">{c.type === 'standard' ? 'Las tareas de rutina se aprueban solas.' : 'Aún no se envía al comité.'}</p>}
              {c.approvals.map((a) => {
                const name = users.get(a.approver_id)?.full_name ?? 'Comité';
                return (
                  <div className="comment" key={a.id}>
                    <Avatar name={name} size={32} />
                    <div className="comment-body">
                      <div className="comment-meta">
                        <strong>{name}</strong>
                        <Badge tone={a.decision === 'approved' ? 'success' : a.decision === 'rejected' ? 'danger' : 'warning'}>
                          {a.decision === 'approved' ? 'Aprobó' : a.decision === 'rejected' ? 'Rechazó' : 'Pendiente'}
                        </Badge>
                        {a.decided_at && <span>{fromNow(a.decided_at)}</span>}
                      </div>
                      {a.comment && <p>{a.comment}</p>}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </div>

        <aside className="col gap-lg">
          <section className="card">
            <div className="card-head">
              <h2>Planificación</h2>
            </div>
            <div className="card-body" style={{ paddingTop: 6, paddingBottom: 6 }}>
              <KeyValue
                items={[
                  ['Inicio', fmtDateTime(c.planned_start)],
                  ['Fin', fmtDateTime(c.planned_end)],
                  ['Creada por', users.get(c.requester_id)?.full_name ?? '…'],
                  ['Problema que corrige', extra.data?.problem ? <Link to={`/app/problems/${extra.data.problem.id}`}>{extra.data.problem.key} · {extra.data.problem.title}</Link> : '—'],
                  ['Creado', fmtDateTime(c.created_at)],
                ]}
              />
            </div>
          </section>
        </aside>
      </div>

      {editing && (
        <ChangeForm
          change={c}
          onClose={() => setEditing(false)}
          onSaved={(u) => {
            chg.setData(u);
            setEditing(false);
          }}
        />
      )}
      {deciding && (
        <DecisionModal
          kind={deciding}
          busy={busy}
          onClose={() => setDeciding(null)}
          onSubmit={(comment) =>
            deciding === 'approve'
              ? run(() => changeService.approve(c.id, comment ? { comment } : {}), () => 'Actualización aprobada')
              : run(() => changeService.reject(c.id, { comment }), () => 'Actualización rechazada')
          }
        />
      )}
    </>
  );
}

function DecisionModal({ kind, busy, onClose, onSubmit }: { kind: 'approve' | 'reject'; busy: boolean; onClose: () => void; onSubmit: (comment: string) => void }) {
  const [comment, setComment] = useState('');
  const reject = kind === 'reject';
  return (
    <Modal
      title={reject ? 'Rechazar actualización' : 'Aprobar actualización'}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className={`btn ${reject ? 'btn-danger' : 'btn-success'}`} disabled={busy || (reject && comment.trim().length < 3)} onClick={() => onSubmit(comment.trim())}>
            {reject ? 'Rechazar' : 'Aprobar'}
          </button>
        </>
      }
    >
      <Field label={reject ? 'Motivo del rechazo' : 'Comentario (opcional)'} hint={reject ? 'Obligatorio: se devolverá al solicitante.' : undefined}>
        <textarea className="textarea" autoFocus value={comment} onChange={(e) => setComment(e.target.value)} />
      </Field>
    </Modal>
  );
}
