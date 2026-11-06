import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { problemService } from '../../api';
import { Icon } from '../../components/Icon';
import { AgentSelect, CiSelect } from '../../components/pickers';
import { SortHeader } from '../../components/SortHeader';
import { Avatar, Empty, ErrorBox, Field, fieldErrors, FilterChips, Modal, PageHeader, Pagination, PriorityBadge, Spinner, StatusBadge, useToast } from '../../components/ui';
import { fmtDateTime, fromNow, PROBLEM_STATUS } from '../../lib/format';
import { useAsync, useDebounced, useUsers } from '../../lib/hooks';
import type { Priority, ProblemSortField, ProblemStatus, SortOrder } from '../../types/api';

export default function ProblemList() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<ProblemStatus[]>(['new', 'investigating', 'known_error']);
  const [priority, setPriority] = useState<Priority[]>([]);
  const [mine, setMine] = useState(false);
  const [sort, setSort] = useState<[ProblemSortField, SortOrder]>(['created_at', 'desc']);
  const [page, setPage] = useState(1);
  const dSearch = useDebounced(search);

  const list = useAsync(
    () =>
      problemService.list({ page, limit: 20, search: dSearch.length >= 2 ? dSearch : undefined, status, priority, owner_id: mine ? 'me' : undefined, sort_by: sort[0], sort_order: sort[1] }),
    [page, dSearch, status.join(), priority.join(), mine, sort.join()],
  );
  const users = useUsers(list.data?.data.map((p) => p.owner_id) ?? []);
  const reset = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v);
    setPage(1);
  };

  return (
    <>
      <PageHeader
        title="Problemas recurrentes"
        subtitle="Fallas que se repiten: se busca la causa de fondo para que dejen de pasar."
        actions={
          <button className="btn btn-primary" onClick={() => setParams({ new: '1' })}>
            <Icon name="plus" /> Registrar problema
          </button>
        }
      />
      <section className="card">
        <div className="toolbar">
          <div className="search">
            <Icon name="search" size={16} />
            <input className="input" placeholder="Buscar por número o título…" value={search} onChange={(e) => reset(setSearch)(e.target.value)} />
          </div>
          <label className="check">
            <input type="checkbox" checked={mine} onChange={(e) => reset(setMine)(e.target.checked)} /> Solo los míos
          </label>
        </div>
        <div className="toolbar">
          <FilterChips options={Object.entries(PROBLEM_STATUS).map(([k, [l]]) => [k as ProblemStatus, l])} value={status} onChange={reset(setStatus)} />
          <span className="grow" />
          <FilterChips options={(['P1', 'P2', 'P3', 'P4'] as Priority[]).map((p) => [p, p])} value={priority} onChange={reset(setPriority)} />
        </div>
        {list.error ? (
          <ErrorBox error={list.error} onRetry={list.reload} />
        ) : !list.data ? (
          <Spinner />
        ) : list.data.data.length === 0 ? (
          <Empty title="No hay problemas con estos filtros" />
        ) : (
          <>
            <div className="table-wrap" style={{ opacity: list.loading ? 0.6 : 1 }}>
              <table className="table">
                <thead>
                  <tr>
                    <SortHeader field="key" label="Número" sort={sort} onSort={setSort} />
                    <th>Título</th>
                    <SortHeader field="priority" label="Prioridad" sort={sort} onSort={setSort} />
                    <SortHeader field="status" label="Estado" sort={sort} onSort={setSort} />
                    <th>Responsable</th>
                    <SortHeader field="created_at" label="Creado" sort={sort} onSort={setSort} />
                  </tr>
                </thead>
                <tbody>
                  {list.data.data.map((p) => {
                    const owner = p.owner_id ? users.get(p.owner_id) : null;
                    return (
                      <tr key={p.id} onClick={() => nav(`/app/problems/${p.id}`)}>
                        <td className="key">{p.key}</td>
                        <td className="title-cell">
                          <strong>{p.title}</strong>
                          {p.root_cause && (
                            <span className="muted" style={{ fontSize: 12.5 }}>
                              Causa de fondo encontrada
                            </span>
                          )}
                        </td>
                        <td>
                          <PriorityBadge value={p.priority} />
                        </td>
                        <td>
                          <StatusBadge map={PROBLEM_STATUS} value={p.status} />
                        </td>
                        <td className="nowrap">
                          {owner ? (
                            <span className="row gap-sm">
                              <Avatar name={owner.full_name} size={24} />
                              {owner.full_name.split(' ').slice(0, 2).join(' ')}
                            </span>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td className="nowrap muted" title={fmtDateTime(p.created_at)}>
                          {fromNow(p.created_at)}
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
      {params.get('new') === '1' && <CreateProblem onClose={() => setParams({}, { replace: true })} onCreated={(id) => nav(`/app/problems/${id}`)} />}
    </>
  );
}

function CreateProblem({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const toast = useToast();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<Priority>('P3');
  const [ci, setCi] = useState<string | null>(null);
  const [owner, setOwner] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});

  async function submit() {
    setBusy(true);
    try {
      const p = await problemService.create({ title, description: description || null, priority, ci_id: ci, owner_id: owner });
      toast(`Problema ${p.key} registrado`);
      onCreated(p.id);
    } catch (e) {
      setErrs(fieldErrors(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Registrar problema recurrente"
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={busy || title.trim().length < 5} onClick={submit}>
            Crear
          </button>
        </>
      }
    >
      <div className="form-grid">
        <Field label="Título" error={errs.title} full>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus placeholder="Ej.: La impresora de contabilidad falla todas las semanas" />
        </Field>
        <Field label="Descripción" error={errs.description} full>
          <textarea className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <Field label="Prioridad" error={errs.priority}>
          <select className="select" value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
            {(['P1', 'P2', 'P3', 'P4'] as Priority[]).map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </Field>
        <Field label="Responsable" error={errs.owner_id} hint="Si lo dejas vacío, serás tú">
          <AgentSelect value={owner} onChange={setOwner} placeholder="Yo" />
        </Field>
        <Field label="Equipo o sistema relacionado" error={errs.ci_id} full>
          <CiSelect value={ci} onChange={setCi} />
        </Field>
      </div>
    </Modal>
  );
}
