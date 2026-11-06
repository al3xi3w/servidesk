import { useState } from 'react';
import { useLiveRefresh } from '../../lib/live';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { cmdbService, incidentService } from '../../api';
import { useMe } from '../../auth/AuthContext';
import { Icon } from '../../components/Icon';
import { useTeams } from '../../components/pickers';
import { Badge, Empty, ErrorBox, KeyValue, Modal, PageHeader, PriorityBadge, Spinner, StatusBadge, useApiErrorToast, useToast } from '../../components/ui';
import { CI_STATUS, ENV, fmtDateTime, fromNow, INCIDENT_STATUS } from '../../lib/format';
import { useAsync } from '../../lib/hooks';
import type { CIRelationType, CIStatus } from '../../types/api';
import { CiForm } from './CiList';

const REL: Record<CIRelationType, [string, string]> = {
  depends_on: ['Depende de', 'Es requerido por'],
  runs_on: ['Se ejecuta en', 'Ejecuta a'],
  connects_to: ['Se conecta a', 'Recibe conexión de'],
};

export default function CiDetail() {
  const { id = '' } = useParams();
  const me = useMe();
  const nav = useNavigate();
  const toast = useToast();
  const onError = useApiErrorToast();
  const ci = useAsync(() => cmdbService.get(id), [id]);
  const relations = useAsync(() => cmdbService.relations(id), [id]);
  const incidents = useAsync(() => incidentService.list({ ci_id: id, limit: 8, sort_by: 'created_at' }), [id, ci.data?.status]);
  useLiveRefresh(me.tenant.id, ci.reload, incidents.reload);
  const teams = useTeams();
  const [editing, setEditing] = useState(false);
  const [confirmRetire, setConfirmRetire] = useState(false);
  const [busy, setBusy] = useState(false);

  if (ci.error) return <ErrorBox error={ci.error} onRetry={ci.reload} />;
  if (!ci.data) return <Spinner />;
  const c = ci.data;

  async function setStatus(status: CIStatus) {
    setBusy(true);
    try {
      ci.setData(await cmdbService.changeStatus(c.id, { status }));
      toast(status === 'down' ? 'Marcado como caído: ServiDesk abrirá un reporte de falla automáticamente' : `Estado: ${CI_STATUS[status][0]}`, status === 'down' ? 'info' : 'success');
      if (status === 'down') setTimeout(incidents.reload, 600);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  async function retire() {
    setBusy(true);
    try {
      await cmdbService.remove(c.id);
      toast('Dado de baja');
      setConfirmRetire(false);
      ci.reload();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        back={
          <Link to="/app/cmdb" className="back-link">
            <Icon name="back" size={14} /> Equipos y sistemas
          </Link>
        }
        title={<span className="mono">{c.name}</span>}
        subtitle={
          <span className="row gap-sm wrap">
            <StatusBadge map={CI_STATUS} value={c.status} />
            <Badge>{c.type_name}</Badge>
            <Badge tone={c.environment === 'prod' ? 'accent' : 'neutral'}>{ENV[c.environment]}</Badge>
          </span>
        }
        actions={
          <>
            {c.status !== 'retired' && (
              <select className="select" style={{ width: 'auto' }} value={c.status} disabled={busy} onChange={(e) => setStatus(e.target.value as CIStatus)} aria-label="Cambiar estado">
                {(['operational', 'degraded', 'down'] as CIStatus[]).map((s) => (
                  <option key={s} value={s}>
                    {CI_STATUS[s][0]}
                  </option>
                ))}
              </select>
            )}
            <button className="btn btn-ghost" onClick={() => setEditing(true)}>
              Editar
            </button>
            {me.role === 'admin' && c.status !== 'retired' && (
              <button className="btn btn-danger" onClick={() => setConfirmRetire(true)}>
                Dar de baja
              </button>
            )}
          </>
        }
      />

      <div className="grid-3-1">
        <div className="col gap-lg">
          <section className="card">
            <div className="card-head">
              <h2>Relaciones</h2>
            </div>
            <div className="card-body rel-list">
              {relations.loading && !relations.data && <Spinner />}
              {relations.data?.length === 0 && <p className="muted">Sin relaciones registradas.</p>}
              {relations.data?.map((r) => (
                <Link key={r.id} to={`/app/cmdb/${r.ci.id}`} className="rel" style={{ color: 'inherit' }}>
                  <span className="dir">{REL[r.relation][r.direction === 'outgoing' ? 0 : 1]}</span>
                  <Icon name={r.direction === 'outgoing' ? 'arrow' : 'back'} size={14} />
                  <span className="mono grow">{r.ci.name}</span>
                  <span className="muted">{r.ci.type_name}</span>
                  <StatusBadge map={CI_STATUS} value={r.ci.status} />
                </Link>
              ))}
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Fallas recientes</h2>
              <span className="muted" style={{ fontSize: 13 }}>
                {incidents.data?.meta.total ?? 0} en total
              </span>
            </div>
            {incidents.data?.data.length === 0 ? (
              <Empty title="Sin fallas registradas" icon="check" />
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <tbody>
                    {incidents.data?.data.map((i) => (
                      <tr key={i.id} onClick={() => nav(`/app/incidents/${i.id}`)}>
                        <td className="key">{i.key}</td>
                        <td className="title-cell">
                          <strong>{i.title}</strong>
                          <span className="muted">{fromNow(i.created_at)}</span>
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
          <section className="card">
            <div className="card-head">
              <h2>Detalles</h2>
            </div>
            <div className="card-body" style={{ paddingTop: 6, paddingBottom: 6 }}>
              <KeyValue
                items={[
                  ['Versión', <span className="mono">{c.version ?? '—'}</span>],
                  ['Área responsable', teams.find((t) => t.id === c.owner_team_id)?.name ?? '—'],
                  ...Object.entries(c.attributes).map(([k, v]) => [k, <span className="mono">{String(v)}</span>] as [string, React.ReactNode]),
                  ['Registrado', fmtDateTime(c.created_at)],
                  ['Actualizado', fmtDateTime(c.updated_at)],
                ]}
              />
            </div>
          </section>
        </aside>
      </div>

      {editing && (
        <CiForm
          ci={c}
          onClose={() => setEditing(false)}
          onSaved={(u) => {
            ci.setData(u);
            setEditing(false);
          }}
        />
      )}
      {confirmRetire && (
        <Modal
          title="Dar de baja"
          onClose={() => setConfirmRetire(false)}
          footer={
            <>
              <button className="btn btn-ghost" onClick={() => setConfirmRetire(false)}>
                Cancelar
              </button>
              <button className="btn btn-danger" disabled={busy} onClick={retire}>
                Dar de baja
              </button>
            </>
          }
        >
          <p>
            <b className="mono">{c.name}</b> pasará a <b>Dado de baja</b>. Se conserva su historial.
          </p>
        </Modal>
      )}
    </>
  );
}
