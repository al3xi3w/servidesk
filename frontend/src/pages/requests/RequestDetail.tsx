import { useState } from 'react';
import { useLiveRefresh } from '../../lib/live';
import { Link, useParams } from 'react-router-dom';
import { requestService } from '../../api';
import { useMe } from '../../auth/AuthContext';
import { Icon } from '../../components/Icon';
import { AgentSelect } from '../../components/pickers';
import { Stepper } from '../../components/Stepper';
import { Avatar, Badge, ErrorBox, fieldErrors, KeyValue, Modal, PageHeader, Spinner, StatusBadge, useApiErrorToast, useToast } from '../../components/ui';
import { fmtDate, fmtDateTime, fromNow, REQUEST_STATUS } from '../../lib/format';
import { useAsync, useUsers } from '../../lib/hooks';
import type { RequestFormData, ServiceRequestDetail, ServiceRequestStatus } from '../../types/api';
import { DynamicForm } from './Catalog';

export default function RequestDetail() {
  const { id = '' } = useParams();
  const me = useMe();
  const isStaff = me.role !== 'customer';
  const toast = useToast();
  const onError = useApiErrorToast();
  const req = useAsync(() => requestService.get(id), [id]);
  const catalog = useAsync(() => requestService.catalog(), []);
  const users = useUsers([req.data?.requester_id, req.data?.assignee_id, ...(req.data?.approvals.map((a) => a.approver_id) ?? [])], isStaff);
  useLiveRefresh(me.tenant.id, req.reload);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);

  if (req.error) return <ErrorBox error={req.error} onRetry={req.reload} />;
  if (!req.data) return <Spinner />;
  const r = req.data;
  const item = catalog.data?.find((c) => c.id === r.catalog_item_id);
  const nameOf = (uid: string | null) => (!uid ? null : uid === me.id ? `${me.full_name} (tú)` : (users.get(uid)?.full_name ?? (isStaff ? '…' : 'Equipo de TI')));

  async function run(fn: () => Promise<ServiceRequestDetail>, msg: string) {
    setBusy(true);
    try {
      req.setData(await fn());
      toast(msg);
      return true;
    } catch (e) {
      onError(e);
      return false;
    } finally {
      setBusy(false);
    }
  }
  const move = (status: Extract<ServiceRequestStatus, 'approved' | 'rejected' | 'in_fulfillment' | 'fulfilled'>, msg: string) => run(() => requestService.changeStatus(r.id, { status }), msg);

  const needsApproval = r.approvals.length > 0;
  const flow: [ServiceRequestStatus, string][] = needsApproval
    ? [['pending_approval', 'Por aprobar'], ['approved', 'Aprobado'], ['in_fulfillment', 'En atención'], ['fulfilled', 'Completado']]
    : [['submitted', 'Recibido'], ['in_fulfillment', 'En atención'], ['fulfilled', 'Completado']];
  const current = r.status === 'rejected' ? (needsApproval ? 'approved' : 'in_fulfillment') : r.status;

  return (
    <>
      <PageHeader
        back={
          <Link to="/app/requests" className="back-link">
            <Icon name="back" size={14} /> Pedidos
          </Link>
        }
        title={
          <span className="row gap-sm wrap">
            <span className="mono" style={{ color: 'var(--primary)', fontSize: 18 }}>
              {r.key}
            </span>
            {r.catalog_item_name}
          </span>
        }
        subtitle={
          <span className="row gap-sm wrap">
            <StatusBadge map={REQUEST_STATUS} value={r.status} />
            <span>Pedido {fromNow(r.created_at)}</span>
          </span>
        }
        actions={
          <>
            {!isStaff && ['submitted', 'pending_approval'].includes(r.status) && item && (
              <button className="btn btn-ghost" onClick={() => setEditing(true)}>
                Editar datos
              </button>
            )}
            {r.status === 'pending_approval' && me.role === 'admin' && (
              <>
                <button className="btn btn-danger" disabled={busy} onClick={() => move('rejected', 'Pedido rechazado')}>
                  Rechazar
                </button>
                <button className="btn btn-success" disabled={busy} onClick={() => move('approved', 'Pedido aprobado')}>
                  Aprobar
                </button>
              </>
            )}
            {r.status === 'pending_approval' && me.role === 'agent' && <Badge tone="warning">Esperando aprobación de un administrador</Badge>}
            {isStaff && r.status === 'submitted' && (
              <button className="btn btn-danger" disabled={busy} onClick={() => move('rejected', 'Pedido rechazado')}>
                Rechazar
              </button>
            )}
            {isStaff && (r.status === 'submitted' || r.status === 'approved') && (
              <button className="btn btn-primary" disabled={busy} onClick={() => move('in_fulfillment', 'Pedido en atención')}>
                Iniciar atención
              </button>
            )}
            {isStaff && r.status === 'in_fulfillment' && (
              <button className="btn btn-success" disabled={busy} onClick={() => move('fulfilled', 'Pedido completado')}>
                Marcar como entregado
              </button>
            )}
          </>
        }
      />

      <section className="card card-pad">
        <Stepper steps={flow.map(([k, l]) => [k, r.status === 'rejected' && k === current ? 'Rechazado' : l])} current={current} failed={r.status === 'rejected'} />
      </section>

      <div className="grid-3-1">
        <section className="card">
          <div className="card-head">
            <h2>Datos del pedido</h2>
          </div>
          <div className="card-body" style={{ paddingTop: 6, paddingBottom: 6 }}>
            <KeyValue
              items={Object.entries(r.form_data).map(([k, v]) => {
                const f = item?.form_schema.fields.find((x) => x.name === k);
                const shown = typeof v === 'boolean' ? (v ? 'Sí' : 'No') : f?.type === 'date' && v ? fmtDate(String(v)) : v === null || v === '' ? '—' : String(v);
                return [f?.label ?? k, shown];
              })}
            />
          </div>
        </section>

        <aside className="col gap-lg">
          <section className="card">
            <div className="card-head">
              <h2>Seguimiento</h2>
            </div>
            <div className="card-body" style={{ paddingTop: 6, paddingBottom: 6 }}>
              <KeyValue
                items={[
                  ['Pedido por', nameOf(r.requester_id)],
                  [
                    'Asignado a',
                    isStaff && !['fulfilled', 'rejected'].includes(r.status) ? (
                      <AgentSelect value={r.assignee_id} onChange={(v) => run(() => requestService.update(r.id, { assignee_id: v }), 'Asignación actualizada')} />
                    ) : (
                      (nameOf(r.assignee_id) ?? <span className="muted">Sin asignar</span>)
                    ),
                  ],
                  ['Tiempo objetivo', item?.sla_hours ? `${item.sla_hours} h` : '—'],
                  ['Fecha', fmtDateTime(r.created_at)],
                  ['Entregado', fmtDateTime(r.fulfilled_at)],
                ]}
              />
            </div>
          </section>
          {needsApproval && (
            <section className="card">
              <div className="card-head">
                <h2>Aprobaciones</h2>
              </div>
              <div className="card-body timeline">
                {r.approvals.map((a) => {
                  const name = nameOf(a.approver_id) ?? 'Aprobador';
                  return (
                    <div className="comment" key={a.id}>
                      <Avatar name={name} size={30} />
                      <div className="comment-body">
                        <div className="comment-meta">
                          <strong>{name}</strong>
                          {a.decided_at && <span>{fromNow(a.decided_at)}</span>}
                        </div>
                        <Badge tone={a.decision === 'approved' ? 'success' : a.decision === 'rejected' ? 'danger' : 'warning'}>
                          {a.decision === 'approved' ? 'Aprobado' : a.decision === 'rejected' ? 'Rechazado' : 'Pendiente'}
                        </Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}
        </aside>
      </div>

      {editing && item && <EditForm request={r} fields={item.form_schema.fields} onClose={() => setEditing(false)} onSaved={(u) => (req.setData(u), setEditing(false), toast('Pedido actualizado'))} />}
    </>
  );
}

function EditForm({ request, fields, onClose, onSaved }: { request: ServiceRequestDetail; fields: Parameters<typeof DynamicForm>[0]['fields']; onClose: () => void; onSaved: (r: ServiceRequestDetail) => void }) {
  const [data, setData] = useState<RequestFormData>(request.form_data);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title={`Editar ${request.key}`}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                onSaved(await requestService.update(request.id, { form_data: data }));
              } catch (e) {
                setErrs(fieldErrors(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            Guardar
          </button>
        </>
      }
    >
      <DynamicForm fields={fields} value={data} onChange={setData} errors={errs} />
    </Modal>
  );
}
