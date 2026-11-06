import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { changeService } from '../../api';
import { Icon } from '../../components/Icon';
import { SortHeader } from '../../components/SortHeader';
import { Badge, Empty, ErrorBox, FilterChips, PageHeader, Pagination, Spinner, StatusBadge } from '../../components/ui';
import { CHANGE_STATUS, CHANGE_TYPE, fmtDateTime, RISK } from '../../lib/format';
import { useAsync, useDebounced } from '../../lib/hooks';
import type { ChangeRisk, ChangeSortField, ChangeStatus, ChangeType, SortOrder } from '../../types/api';
import { ChangeForm } from './ChangeForm';

export default function ChangeList() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<ChangeStatus[]>(params.get('status') ? [params.get('status') as ChangeStatus] : []);
  const [type, setType] = useState<ChangeType[]>([]);
  const [risk, setRisk] = useState<ChangeRisk[]>([]);
  const [mine, setMine] = useState(false);
  const [sort, setSort] = useState<[ChangeSortField, SortOrder]>(['created_at', 'desc']);
  const [page, setPage] = useState(1);
  const dSearch = useDebounced(search);

  const list = useAsync(
    () =>
      changeService.list({ page, limit: 20, search: dSearch.length >= 2 ? dSearch : undefined, status, type, risk, requester_id: mine ? 'me' : undefined, sort_by: sort[0], sort_order: sort[1] }),
    [page, dSearch, status.join(), type.join(), risk.join(), mine, sort.join()],
  );
  const reset = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v);
    setPage(1);
  };

  return (
    <>
      <PageHeader
        title="Mejoras y actualizaciones"
        subtitle="Cambios planificados a los sistemas: qué se hace, cuándo, con qué riesgo y quién lo aprueba."
        actions={
          <>
            <Link to="/app/changes/calendar" className="btn btn-ghost">
              <Icon name="calendar" /> Calendario
            </Link>
            <button className="btn btn-primary" onClick={() => setParams({ new: '1' })}>
              <Icon name="plus" /> Planificar actualización
            </button>
          </>
        }
      />
      <section className="card">
        <div className="toolbar">
          <div className="search">
            <Icon name="search" size={16} />
            <input className="input" placeholder="Buscar por número o título…" value={search} onChange={(e) => reset(setSearch)(e.target.value)} />
          </div>
          <FilterChips options={(Object.keys(CHANGE_TYPE) as ChangeType[]).map((t) => [t, CHANGE_TYPE[t]])} value={type} onChange={reset(setType)} />
          <FilterChips options={(Object.keys(RISK) as ChangeRisk[]).map((r) => [r, `Riesgo ${RISK[r][0].toLowerCase()}`])} value={risk} onChange={reset(setRisk)} />
          <label className="check">
            <input type="checkbox" checked={mine} onChange={(e) => reset(setMine)(e.target.checked)} /> Creadas por mí
          </label>
        </div>
        <div className="toolbar">
          <FilterChips options={Object.entries(CHANGE_STATUS).map(([k, [l]]) => [k as ChangeStatus, l])} value={status} onChange={reset(setStatus)} />
        </div>
        {list.error ? (
          <ErrorBox error={list.error} onRetry={list.reload} />
        ) : !list.data ? (
          <Spinner />
        ) : list.data.data.length === 0 ? (
          <Empty title="No hay actualizaciones con estos filtros" />
        ) : (
          <>
            <div className="table-wrap" style={{ opacity: list.loading ? 0.6 : 1 }}>
              <table className="table">
                <thead>
                  <tr>
                    <SortHeader field="key" label="Número" sort={sort} onSort={setSort} />
                    <th>Título</th>
                    <th>Tipo</th>
                    <SortHeader field="risk" label="Riesgo" sort={sort} onSort={setSort} />
                    <SortHeader field="status" label="Estado" sort={sort} onSort={setSort} />
                    <SortHeader field="planned_start" label="Fecha planificada" sort={sort} onSort={setSort} />
                  </tr>
                </thead>
                <tbody>
                  {list.data.data.map((c) => (
                    <tr key={c.id} onClick={() => nav(`/app/changes/${c.id}`)}>
                      <td className="key">{c.key}</td>
                      <td className="title-cell">
                        <strong>{c.title}</strong>
                      </td>
                      <td>
                        <Badge tone={c.type === 'emergency' ? 'danger' : c.type === 'standard' ? 'neutral' : 'info'}>{CHANGE_TYPE[c.type]}</Badge>
                      </td>
                      <td>
                        <StatusBadge map={RISK} value={c.risk} />
                      </td>
                      <td>
                        <StatusBadge map={CHANGE_STATUS} value={c.status} />
                      </td>
                      <td className="nowrap muted">{fmtDateTime(c.planned_start)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination meta={list.data.meta} onPage={setPage} />
          </>
        )}
      </section>
      {params.get('new') === '1' && <ChangeForm problemId={params.get('problem')} onClose={() => setParams({}, { replace: true })} onSaved={(c) => nav(`/app/changes/${c.id}`)} />}
    </>
  );
}
