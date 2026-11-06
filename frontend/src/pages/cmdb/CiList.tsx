import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { cmdbService } from '../../api';
import { Icon } from '../../components/Icon';
import { TeamSelect, useTeams } from '../../components/pickers';
import { SortHeader } from '../../components/SortHeader';
import { Badge, Empty, ErrorBox, Field, fieldErrors, FilterChips, Modal, PageHeader, Pagination, Spinner, StatusBadge, useToast } from '../../components/ui';
import { CI_STATUS, ENV, fromNow } from '../../lib/format';
import { useAsync, useDebounced } from '../../lib/hooks';
import type { CIEnvironment, CISortField, CIStatus, ConfigurationItem, SortOrder } from '../../types/api';

export default function CiList() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<CIStatus[]>(params.get('status') ? [params.get('status') as CIStatus] : ['operational', 'degraded', 'down']);
  const [env, setEnv] = useState<CIEnvironment[]>([]);
  const [typeId, setTypeId] = useState<number | ''>('');
  const [sort, setSort] = useState<[CISortField, SortOrder]>(['name', 'asc']);
  const [page, setPage] = useState(1);
  const dSearch = useDebounced(search);
  const types = useAsync(() => cmdbService.types(), []);
  const teams = useTeams();

  const list = useAsync(
    () => cmdbService.list({ page, limit: 20, search: dSearch.length >= 2 ? dSearch : undefined, status, environment: env, type_id: typeId || undefined, sort_by: sort[0], sort_order: sort[1] }),
    [page, dSearch, status.join(), env.join(), typeId, sort.join()],
  );
  const reset = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v);
    setPage(1);
  };

  return (
    <>
      <PageHeader
        title="Equipos y sistemas"
        subtitle="Inventario de servidores, bases de datos, redes, computadoras y aplicaciones de la empresa."
        actions={
          <button className="btn btn-primary" onClick={() => setParams({ new: '1' })}>
            <Icon name="plus" /> Registrar equipo o sistema
          </button>
        }
      />
      <section className="card">
        <div className="toolbar">
          <div className="search">
            <Icon name="search" size={16} />
            <input className="input" placeholder="Buscar por nombre…" value={search} onChange={(e) => reset(setSearch)(e.target.value)} />
          </div>
          <select className="select" value={typeId} onChange={(e) => reset(setTypeId)(e.target.value ? Number(e.target.value) : '')}>
            <option value="">Todos los tipos</option>
            {types.data?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <FilterChips options={(Object.keys(ENV) as CIEnvironment[]).map((e) => [e, ENV[e]])} value={env} onChange={reset(setEnv)} />
        </div>
        <div className="toolbar">
          <FilterChips options={Object.entries(CI_STATUS).map(([k, [l]]) => [k as CIStatus, l])} value={status} onChange={reset(setStatus)} />
        </div>
        {list.error ? (
          <ErrorBox error={list.error} onRetry={list.reload} />
        ) : !list.data ? (
          <Spinner />
        ) : list.data.data.length === 0 ? (
          <Empty title="No hay equipos o sistemas con estos filtros" />
        ) : (
          <>
            <div className="table-wrap" style={{ opacity: list.loading ? 0.6 : 1 }}>
              <table className="table">
                <thead>
                  <tr>
                    <SortHeader field="name" label="Nombre" sort={sort} onSort={setSort} />
                    <th>Tipo</th>
                    <th>Entorno</th>
                    <SortHeader field="status" label="Estado" sort={sort} onSort={setSort} />
                    <th>Versión</th>
                    <th>Área responsable</th>
                    <SortHeader field="updated_at" label="Actualizado" sort={sort} onSort={setSort} />
                  </tr>
                </thead>
                <tbody>
                  {list.data.data.map((c) => (
                    <tr key={c.id} onClick={() => nav(`/app/cmdb/${c.id}`)}>
                      <td className="mono" style={{ fontWeight: 600 }}>
                        {c.name}
                      </td>
                      <td>{c.type_name}</td>
                      <td>
                        <Badge tone={c.environment === 'prod' ? 'accent' : 'neutral'}>{ENV[c.environment]}</Badge>
                      </td>
                      <td>
                        <StatusBadge map={CI_STATUS} value={c.status} />
                      </td>
                      <td className="mono muted">{c.version ?? '—'}</td>
                      <td className="nowrap">{teams.find((t) => t.id === c.owner_team_id)?.name ?? '—'}</td>
                      <td className="nowrap muted">{fromNow(c.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination meta={list.data.meta} onPage={setPage} />
          </>
        )}
      </section>
      {params.get('new') === '1' && <CiForm onClose={() => setParams({}, { replace: true })} onSaved={(c) => nav(`/app/cmdb/${c.id}`)} />}
    </>
  );
}

export function CiForm({ ci, onClose, onSaved }: { ci?: ConfigurationItem; onClose: () => void; onSaved: (c: ConfigurationItem) => void }) {
  const toast = useToast();
  const types = useAsync(() => cmdbService.types(), []);
  const [name, setName] = useState(ci?.name ?? '');
  const [typeId, setTypeId] = useState<number | ''>(ci?.type_id ?? '');
  const [env, setEnv] = useState<CIEnvironment>(ci?.environment ?? 'prod');
  const [version, setVersion] = useState(ci?.version ?? '');
  const [team, setTeam] = useState<string | null>(ci?.owner_team_id ?? null);
  const [attrs, setAttrs] = useState(JSON.stringify(ci?.attributes ?? {}, null, 2));
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function submit() {
    let attributes: Record<string, unknown>;
    try {
      attributes = JSON.parse(attrs || '{}');
    } catch {
      setErrs({ attributes: 'JSON inválido' });
      return;
    }
    setBusy(true);
    try {
      const body = { name, type_id: Number(typeId), environment: env, version: version || null, owner_team_id: team, attributes };
      const saved = ci ? await cmdbService.update(ci.id, body) : await cmdbService.create(body);
      toast(ci ? 'Datos actualizados' : 'Equipo o sistema registrado');
      onSaved(saved);
    } catch (e) {
      setErrs(fieldErrors(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={ci ? `Editar ${ci.name}` : 'Registrar equipo o sistema'}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={busy || name.trim().length < 2 || !typeId} onClick={submit}>
            Guardar
          </button>
        </>
      }
    >
      <div className="form-grid">
        <Field label="Nombre" error={errs.name}>
          <input className="input mono" value={name} onChange={(e) => setName(e.target.value)} placeholder="erp-app-prod-01" autoFocus />
        </Field>
        <Field label="Tipo" error={errs.type_id}>
          <select className="select" value={typeId} onChange={(e) => setTypeId(e.target.value ? Number(e.target.value) : '')}>
            <option value="">Selecciona…</option>
            {types.data?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Entorno" error={errs.environment}>
          <select className="select" value={env} onChange={(e) => setEnv(e.target.value as CIEnvironment)}>
            {(Object.keys(ENV) as CIEnvironment[]).map((k) => (
              <option key={k} value={k}>
                {ENV[k]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Versión" error={errs.version}>
          <input className="input mono" value={version} onChange={(e) => setVersion(e.target.value)} placeholder="1.0.0" />
        </Field>
        <Field label="Área responsable" error={errs.owner_team_id} full>
          <TeamSelect value={team} onChange={setTeam} />
        </Field>
        <Field label="Detalles técnicos (opcional, formato JSON)" error={errs.attributes} full>
          <textarea className="textarea mono" value={attrs} onChange={(e) => setAttrs(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}
