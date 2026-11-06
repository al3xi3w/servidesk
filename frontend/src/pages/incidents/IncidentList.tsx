import { useState } from 'react';
import { useLiveRefresh } from '../../lib/live';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { incidentService } from '../../api';
import { useMe } from '../../auth/AuthContext';
import { Icon } from '../../components/Icon';
import { AgentSelect, CiSelect, LevelSelect, PriorityMatrix, TeamSelect } from '../../components/pickers';
import { Avatar, Empty, ErrorBox, Field, fieldErrors, FilterChips, Modal, PageHeader, Pagination, PriorityBadge, Spinner, StatusBadge, useToast } from '../../components/ui';
import { CHANNEL, fmtDateTime, fromNow, INCIDENT_STATUS, priorityOf } from '../../lib/format';
import { useAsync, useDebounced, useUsers } from '../../lib/hooks';
import type { AssigneeFilter, IncidentSortField, IncidentStatus, Level, Priority, SortOrder } from '../../types/api';
import { SortHeader } from '../../components/SortHeader';

type Queue = 'all' | 'none' | 'me' | 'risk' | 'breached';
const OPEN: IncidentStatus[] = ['new', 'in_progress', 'on_hold'];
const QUEUES: [Queue, string, boolean][] = [
  ['all', 'Todas', false],
  ['none', 'Sin asignar', false],
  ['me', 'Asignadas a mí', false],
  ['risk', 'Por vencer', true],
  ['breached', 'Fuera de plazo', true],
];

export default function IncidentList() {
  const me = useMe();
  const isStaff = me.role !== 'customer';
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();

  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<IncidentStatus[]>(isStaff && !params.get('priority') && !params.get('sla') && !params.get('mine') ? OPEN : []);
  const [priority, setPriority] = useState<Priority[]>(params.get('priority') ? [params.get('priority') as Priority] : []);
  const [queue, setQueue] = useState<Queue>(params.get('mine') ? 'me' : params.get('sla') ? 'breached' : 'all');
  const [sort, setSort] = useState<[IncidentSortField, SortOrder]>(['created_at', 'desc']);
  const [page, setPage] = useState(1);
  const dSearch = useDebounced(search);
  const creating = params.get('new') === '1';

  const list = useAsync(
    () =>
      incidentService.list({
        page,
        limit: 20,
        search: dSearch.length >= 2 ? dSearch : undefined,
        // "Por vencer": abiertos aún dentro del plazo, los que vencen antes primero.
        status: queue === 'risk' && !status.length ? OPEN : status,
        priority,
        assignee_id: queue === 'me' || queue === 'none' ? (queue as AssigneeFilter) : undefined,
        sla_breached: queue === 'breached' ? true : queue === 'risk' ? false : undefined,
        sort_by: queue === 'risk' ? 'sla_due_at' : sort[0],
        sort_order: queue === 'risk' ? 'asc' : sort[1],
      }),
    [page, dSearch, status.join(), priority.join(), queue, sort.join()],
  );
  useLiveRefresh(me.tenant.id, list.reload);
  const users = useUsers(list.data?.data.map((i) => i.assignee_id) ?? [], isStaff);

  const reset = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v);
    setPage(1);
  };
  const closeCreate = () => {
    params.delete('new');
    setParams(params, { replace: true });
  };

  return (
    <>
      <PageHeader
        title={isStaff ? 'Fallas reportadas' : 'Mis fallas reportadas'}
        subtitle={isStaff ? 'Todo lo que dejó de funcionar, ordenado por urgencia: correo, impresoras, servidores, sistemas…' : 'Lo que reportaste y en qué va cada caso.'}
        actions={
          <button className="btn btn-primary" onClick={() => setParams({ new: '1' })}>
            <Icon name="plus" /> {isStaff ? 'Reportar falla' : 'Algo no funciona'}
          </button>
        }
      />

      <section className="card">
        <div className="toolbar">
          <div className="search">
            <Icon name="search" size={16} />
            <input className="input" placeholder="Buscar por número o título…" value={search} onChange={(e) => reset(setSearch)(e.target.value)} />
          </div>
          {isStaff && (
            <div className="seg" role="group" aria-label="Colas">
              {QUEUES.map(([v, l, n]) => (
                <button key={v} className={queue === v ? 'on' : ''} onClick={() => reset(setQueue)(v)}>
                  {n && <span className={`q-dot q-${v}`} />}
                  {l}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="toolbar">
          <FilterChips options={Object.entries(INCIDENT_STATUS).map(([k, [l]]) => [k as IncidentStatus, l])} value={status} onChange={reset(setStatus)} />
          <span className="grow" />
          <FilterChips options={(['P1', 'P2', 'P3', 'P4'] as Priority[]).map((p) => [p, p])} value={priority} onChange={reset(setPriority)} />
        </div>

        {list.error ? (
          <ErrorBox error={list.error} onRetry={list.reload} />
        ) : !list.data ? (
          <Spinner />
        ) : list.data.data.length === 0 ? (
          <Empty title="No hay fallas con estos filtros" />
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
                    {isStaff && <th>Asignado</th>}
                    <SortHeader field="sla_due_at" label="Plazo" sort={sort} onSort={setSort} />
                    <SortHeader field="created_at" label="Creado" sort={sort} onSort={setSort} />
                  </tr>
                </thead>
                <tbody>
                  {list.data.data.map((i) => {
                    const assigneeUser = i.assignee_id ? users.get(i.assignee_id) : null;
                    const open = i.status !== 'resolved' && i.status !== 'closed';
                    return (
                      <tr key={i.id} onClick={() => nav(`/app/incidents/${i.id}`)}>
                        <td className="key">{i.key}</td>
                        <td className="title-cell">
                          <strong>{i.title}</strong>
                          <span className="muted" style={{ fontSize: 12.5 }}>
                            {CHANNEL[i.channel]}
                          </span>
                        </td>
                        <td>
                          <PriorityBadge value={i.priority} />
                        </td>
                        <td>
                          <StatusBadge map={INCIDENT_STATUS} value={i.status} />
                        </td>
                        {isStaff && (
                          <td className="nowrap">
                            {assigneeUser ? (
                              <span className="row gap-sm">
                                <Avatar name={assigneeUser.full_name} size={24} />
                                {assigneeUser.full_name.split(' ').slice(0, 2).join(' ')}
                              </span>
                            ) : i.assignee_id ? (
                              '…'
                            ) : (
                              <span className="muted">Sin asignar</span>
                            )}
                          </td>
                        )}
                        <td className={`nowrap ${open && i.sla_breached ? 'sla-late' : ''}`} title={fmtDateTime(i.sla_due_at)}>
                          {open ? fromNow(i.sla_due_at) : i.sla_breached ? <span className="badge tone-danger">Fuera de plazo</span> : <span className="badge tone-success">A tiempo</span>}
                        </td>
                        <td className="nowrap muted" title={fmtDateTime(i.created_at)}>
                          {fromNow(i.created_at)}
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

      {creating && (
        <CreateIncident
          onClose={closeCreate}
          onCreated={(id) => {
            closeCreate();
            nav(`/app/incidents/${id}`);
          }}
        />
      )}
    </>
  );
}

function CreateIncident({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const me = useMe();
  const isStaff = me.role !== 'customer';
  const toast = useToast();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [impact, setImpact] = useState<Level | ''>('');
  const [urgency, setUrgency] = useState<Level | ''>('');
  const [ci, setCi] = useState<string | null>(null);
  const [team, setTeam] = useState<string | null>(null);
  const [assignee, setAssignee] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState('');

  async function submit() {
    setBusy(true);
    setErrs({});
    setFormError('');
    try {
      const inc = await incidentService.create({
        title,
        description: description || null,
        impact: impact as Level,
        urgency: urgency as Level,
        ...(isStaff ? { ci_id: ci, team_id: team, assignee_id: assignee } : {}),
      });
      toast(`Falla ${inc.key} registrada con prioridad ${inc.priority}`);
      onCreated(inc.id);
    } catch (e) {
      setErrs(fieldErrors(e));
      setFormError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={isStaff ? 'Reportar falla' : 'Algo no funciona'}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={busy || title.trim().length < 5 || !impact || !urgency} onClick={submit}>
            {busy ? 'Registrando…' : 'Registrar'}
          </button>
        </>
      }
    >
      {formError && !Object.keys(errs).length && <div className="form-error">{formError}</div>}
      <div className="form-grid">
        <Field label="¿Qué pasa?" error={errs.title} hint="Una frase corta, mínimo 5 caracteres" full>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ej.: No puedo acceder al sistema de facturación" autoFocus />
        </Field>
        <Field label="Descripción" error={errs.description} full>
          <textarea className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="¿Qué estabas haciendo? ¿Qué mensaje aparece? ¿Desde cuándo?" />
        </Field>
        <Field label={isStaff ? 'Alcance (a cuántos afecta)' : '¿A cuántas personas afecta?'} error={errs.impact} hint={isStaff ? undefined : 'Alto: a toda el área · Bajo: solo a ti'}>
          <LevelSelect value={impact} onChange={setImpact} />
        </Field>
        <Field label={isStaff ? 'Urgencia' : '¿Qué tan urgente es?'} error={errs.urgency} hint={isStaff ? undefined : 'Alto: no puedes trabajar'}>
          <LevelSelect value={urgency} onChange={setUrgency} />
        </Field>
        {isStaff && (
          <>
            <Field label="Equipo o sistema afectado" error={errs.ci_id} full>
              <CiSelect value={ci} onChange={setCi} />
            </Field>
            <Field label="Área de TI" error={errs.team_id}>
              <TeamSelect value={team} onChange={setTeam} />
            </Field>
            <Field label="Asignado a" error={errs.assignee_id}>
              <AgentSelect value={assignee} onChange={setAssignee} />
            </Field>
          </>
        )}
      </div>
      <div className="row gap-lg wrap" style={{ alignItems: 'flex-start' }}>
        <div className="col gap-xs">
          <span className="field-label">Prioridad calculada</span>
          {impact && urgency ? <PriorityBadge value={priorityOf(impact, urgency)} /> : <span className="muted">Elige impacto y urgencia</span>}
          <span className="field-hint">La calcula ServiDesk y define el plazo de atención.</span>
        </div>
        <div className="grow" style={{ maxWidth: 320 }}>
          <PriorityMatrix impact={impact} urgency={urgency} />
        </div>
      </div>
    </Modal>
  );
}
