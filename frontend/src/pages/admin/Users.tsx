import { useState } from 'react';
import { userService } from '../../api';
import { useMe } from '../../auth/AuthContext';
import { Icon } from '../../components/Icon';
import { resetPickerCache } from '../../components/pickers';
import { SortHeader } from '../../components/SortHeader';
import { Avatar, Badge, Empty, ErrorBox, Field, fieldErrors, FilterChips, Modal, PageHeader, Pagination, Spinner, useToast } from '../../components/ui';
import { fmtDate, ROLE } from '../../lib/format';
import { useAsync, useDebounced } from '../../lib/hooks';
import type { Role, SortOrder, User, UserSortField } from '../../types/api';

export default function Users() {
  const me = useMe();
  const isAdmin = me.role === 'admin';
  const [tab, setTab] = useState<'users' | 'teams'>('users');
  const [search, setSearch] = useState('');
  const [roles, setRoles] = useState<Role[]>([]);
  const [sort, setSort] = useState<[UserSortField, SortOrder]>(['full_name', 'asc']);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<User | 'new' | null>(null);
  const dSearch = useDebounced(search);

  const users = useAsync(
    () => userService.list({ page, limit: 20, search: dSearch.length >= 2 ? dSearch : undefined, role: roles, sort_by: sort[0], sort_order: sort[1] }),
    [page, dSearch, roles.join(), sort.join()],
  );
  const teams = useAsync(() => userService.listTeams({ limit: 100 }), []);

  return (
    <>
      <PageHeader
        title="Personas y áreas"
        subtitle={`Quiénes usan ServiDesk en ${me.tenant.name}.`}
        actions={
          isAdmin &&
          tab === 'users' && (
            <button className="btn btn-primary" onClick={() => setEditing('new')}>
              <Icon name="plus" /> Agregar persona
            </button>
          )
        }
      />
      <div className="seg" style={{ alignSelf: 'flex-start' }}>
        <button className={tab === 'users' ? 'on' : ''} onClick={() => setTab('users')}>
          Usuarios
        </button>
        <button className={tab === 'teams' ? 'on' : ''} onClick={() => setTab('teams')}>
          Áreas de TI
        </button>
      </div>

      {tab === 'teams' ? (
        <section className="card">
          {teams.error ? (
            <ErrorBox error={teams.error} />
          ) : !teams.data ? (
            <Spinner />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Área</th>
                  <th>Descripción</th>
                </tr>
              </thead>
              <tbody>
                {teams.data.data.map((t) => (
                  <tr key={t.id} style={{ cursor: 'default' }}>
                    <td style={{ fontWeight: 600 }}>{t.name}</td>
                    <td className="muted">{t.description ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ) : (
        <section className="card">
          <div className="toolbar">
            <div className="search">
              <Icon name="search" size={16} />
              <input
                className="input"
                placeholder="Buscar por nombre o email…"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
            </div>
            <FilterChips
              options={(Object.keys(ROLE) as Role[]).map((r) => [r, ROLE[r]])}
              value={roles}
              onChange={(v) => {
                setRoles(v);
                setPage(1);
              }}
            />
          </div>
          {users.error ? (
            <ErrorBox error={users.error} onRetry={users.reload} />
          ) : !users.data ? (
            <Spinner />
          ) : users.data.data.length === 0 ? (
            <Empty title="Sin resultados" />
          ) : (
            <>
              <div className="table-wrap" style={{ opacity: users.loading ? 0.6 : 1 }}>
                <table className="table">
                  <thead>
                    <tr>
                      <SortHeader field="full_name" label="Nombre" sort={sort} onSort={setSort} />
                      <SortHeader field="email" label="Email" sort={sort} onSort={setSort} />
                      <th>Rol</th>
                      <th>Estado</th>
                      <SortHeader field="created_at" label="Alta" sort={sort} onSort={setSort} />
                    </tr>
                  </thead>
                  <tbody>
                    {users.data.data.map((u) => (
                      <tr key={u.id} onClick={() => isAdmin && setEditing(u)} style={{ cursor: isAdmin ? 'pointer' : 'default' }}>
                        <td>
                          <span className="row gap-sm">
                            <Avatar name={u.full_name} />
                            <strong style={{ fontWeight: 600 }}>{u.full_name}</strong>
                          </span>
                        </td>
                        <td className="muted">{u.email}</td>
                        <td>
                          <Badge tone={u.role === 'admin' ? 'accent' : u.role === 'agent' ? 'info' : 'neutral'}>{ROLE[u.role]}</Badge>
                        </td>
                        <td>{u.active ? <Badge tone="success">Activo</Badge> : <Badge tone="muted">Inactivo</Badge>}</td>
                        <td className="muted nowrap">{fmtDate(u.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination meta={users.data.meta} onPage={setPage} />
            </>
          )}
        </section>
      )}

      {editing && (
        <UserForm
          user={editing === 'new' ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            resetPickerCache();
            users.reload();
          }}
        />
      )}
    </>
  );
}

function UserForm({ user, onClose, onSaved }: { user?: User; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [email, setEmail] = useState(user?.email ?? '');
  const [fullName, setFullName] = useState(user?.full_name ?? '');
  const [role, setRole] = useState<Role>(user?.role ?? 'customer');
  const [active, setActive] = useState(user?.active ?? true);
  const [password, setPassword] = useState('');
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setErrs({});
    try {
      if (user) await userService.update(user.id, { full_name: fullName, role, active, ...(password ? { password } : {}) });
      else await userService.create({ email, full_name: fullName, role, active, password });
      toast(user ? 'Usuario actualizado' : 'Usuario creado');
      onSaved();
    } catch (e) {
      const fe = fieldErrors(e);
      setErrs(Object.keys(fe).length ? fe : { _: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={user ? 'Editar persona' : 'Agregar persona'}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={busy || fullName.trim().length < 3 || (!user && (!email || password.length < 8))} onClick={submit}>
            Guardar
          </button>
        </>
      }
    >
      {errs._ && <div className="form-error">{errs._}</div>}
      <Field label="Email" error={errs.email} hint={user ? 'El email no se puede cambiar' : undefined}>
        <input className="input" type="email" value={email} disabled={!!user} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field label="Nombre completo" error={errs.full_name}>
        <input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} />
      </Field>
      <Field label="Rol" error={errs.role}>
        <select className="select" value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {(Object.keys(ROLE) as Role[]).map((r) => (
            <option key={r} value={r}>
              {ROLE[r]}
            </option>
          ))}
        </select>
      </Field>
      <Field label={user ? 'Nueva contraseña (opcional)' : 'Contraseña'} error={errs.password} hint="Entre 8 y 128 caracteres">
        <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
      </Field>
      <label className="check">
        <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Usuario activo
      </label>
    </Modal>
  );
}
