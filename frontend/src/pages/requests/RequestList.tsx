import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { requestService } from '../../api';
import { useMe } from '../../auth/AuthContext';
import { Icon } from '../../components/Icon';
import { SortHeader } from '../../components/SortHeader';
import { Avatar, Empty, ErrorBox, FilterChips, PageHeader, Pagination, Spinner, StatusBadge } from '../../components/ui';
import { fmtDateTime, fromNow, REQUEST_STATUS } from '../../lib/format';
import { useAsync, useDebounced, useUsers } from '../../lib/hooks';
import type { AssigneeFilter, ServiceRequestSortField, ServiceRequestStatus, SortOrder } from '../../types/api';

export default function RequestList() {
  const me = useMe();
  const isStaff = me.role !== 'customer';
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<ServiceRequestStatus[]>(
    params.get('status') ? [params.get('status') as ServiceRequestStatus] : isStaff ? ['submitted', 'pending_approval', 'approved', 'in_fulfillment'] : [],
  );
  const [assignee, setAssignee] = useState<AssigneeFilter | ''>('');
  const [sort, setSort] = useState<[ServiceRequestSortField, SortOrder]>(['created_at', 'desc']);
  const [page, setPage] = useState(1);
  const dSearch = useDebounced(search);

  const list = useAsync(
    () => requestService.list({ page, limit: 20, search: dSearch.length >= 2 ? dSearch : undefined, status, assignee_id: assignee || undefined, sort_by: sort[0], sort_order: sort[1] }),
    [page, dSearch, status.join(), assignee, sort.join()],
  );
  const users = useUsers(list.data?.data.flatMap((r) => [r.requester_id, r.assignee_id]) ?? [], isStaff);
  const reset = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v);
    setPage(1);
  };

  return (
    <>
      <PageHeader
        title={isStaff ? 'Pedidos' : 'Mis pedidos'}
        subtitle={isStaff ? 'Lo que los trabajadores necesitan: programas, accesos, equipos. Aprobar, asignar y atender.' : 'Lo que pediste al área de TI y en qué va.'}
        actions={
          <Link to="/app/catalog" className="btn btn-primary">
            <Icon name="plus" /> Hacer un pedido
          </Link>
        }
      />
      <section className="card">
        <div className="toolbar">
          <div className="search">
            <Icon name="search" size={16} />
            <input className="input" placeholder="Buscar por número o servicio…" value={search} onChange={(e) => reset(setSearch)(e.target.value)} />
          </div>
          {isStaff && (
            <div className="seg" role="group" aria-label="Asignación">
              {([['', 'Todos'], ['me', 'Asignados a mí'], ['none', 'Sin asignar']] as const).map(([v, l]) => (
                <button key={v} className={assignee === v ? 'on' : ''} onClick={() => reset(setAssignee)(v)}>
                  {l}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="toolbar">
          <FilterChips options={Object.entries(REQUEST_STATUS).map(([k, [l]]) => [k as ServiceRequestStatus, l])} value={status} onChange={reset(setStatus)} />
        </div>
        {list.error ? (
          <ErrorBox error={list.error} onRetry={list.reload} />
        ) : !list.data ? (
          <Spinner />
        ) : list.data.data.length === 0 ? (
          <Empty title="No hay pedidos con estos filtros" icon="request">
            {!isStaff && <Link to="/app/catalog">Ir al catálogo</Link>}
          </Empty>
        ) : (
          <>
            <div className="table-wrap" style={{ opacity: list.loading ? 0.6 : 1 }}>
              <table className="table">
                <thead>
                  <tr>
                    <SortHeader field="key" label="Número" sort={sort} onSort={setSort} />
                    <th>Servicio</th>
                    <SortHeader field="status" label="Estado" sort={sort} onSort={setSort} />
                    {isStaff && <th>Pedido por</th>}
                    {isStaff && <th>Asignado</th>}
                    <SortHeader field="created_at" label="Fecha" sort={sort} onSort={setSort} />
                  </tr>
                </thead>
                <tbody>
                  {list.data.data.map((r) => {
                    const req = users.get(r.requester_id);
                    const asg = r.assignee_id ? users.get(r.assignee_id) : null;
                    return (
                      <tr key={r.id} onClick={() => nav(`/app/requests/${r.id}`)}>
                        <td className="key">{r.key}</td>
                        <td className="title-cell">
                          <strong>{r.catalog_item_name}</strong>
                        </td>
                        <td>
                          <StatusBadge map={REQUEST_STATUS} value={r.status} />
                        </td>
                        {isStaff && <td className="nowrap">{req ? req.full_name.split(' ').slice(0, 2).join(' ') : '…'}</td>}
                        {isStaff && (
                          <td className="nowrap">
                            {asg ? (
                              <span className="row gap-sm">
                                <Avatar name={asg.full_name} size={24} />
                                {asg.full_name.split(' ').slice(0, 2).join(' ')}
                              </span>
                            ) : (
                              <span className="muted">—</span>
                            )}
                          </td>
                        )}
                        <td className="nowrap muted" title={fmtDateTime(r.created_at)}>
                          {fromNow(r.created_at)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Pagination meta={list.data.meta} onPage={setPage} />
          </>
        )}
      </section>
    </>
  );
}
