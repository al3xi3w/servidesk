import { useEffect, useState } from 'react';
import { cmdbService, userService } from '../api';
import type { ConfigurationItem, Level, Team, User } from '../types/api';
import { LEVEL, priorityOf } from '../lib/format';
import { useDebounced } from '../lib/hooks';

// Cachés por sesión: equipos y agentes cambian poco.
let teamsCache: Promise<Team[]> | null = null;
let agentsCache: Promise<User[]> | null = null;

export function resetPickerCache() {
  teamsCache = agentsCache = null;
}

export function useTeams(enabled = true): Team[] {
  const [teams, setTeams] = useState<Team[]>([]);
  useEffect(() => {
    if (!enabled) return;
    teamsCache ??= userService.listTeams({ limit: 100 }).then((r) => r.data).catch(() => ((teamsCache = null), []));
    teamsCache.then(setTeams);
  }, [enabled]);
  return teams;
}

export function useAgents(enabled = true): User[] {
  const [users, setUsers] = useState<User[]>([]);
  useEffect(() => {
    if (!enabled) return;
    agentsCache ??= userService
      .list({ role: ['agent', 'admin'], active: true, limit: 100, sort_by: 'full_name', sort_order: 'asc' })
      .then((r) => r.data)
      .catch(() => ((agentsCache = null), []));
    agentsCache.then(setUsers);
  }, [enabled]);
  return users;
}

export function TeamSelect({ value, onChange }: { value: string | null; onChange: (v: string | null) => void }) {
  const teams = useTeams();
  return (
    <select className="select" value={value ?? ''} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">Sin área asignada</option>
      {teams.map((t) => (
        <option key={t.id} value={t.id}>
          {t.name}
        </option>
      ))}
    </select>
  );
}

export function AgentSelect({ value, onChange, placeholder = 'Sin asignar' }: { value: string | null; onChange: (v: string | null) => void; placeholder?: string }) {
  const agents = useAgents();
  return (
    <select className="select" value={value ?? ''} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{placeholder}</option>
      {agents.map((u) => (
        <option key={u.id} value={u.id}>
          {u.full_name}
        </option>
      ))}
    </select>
  );
}

/** Selector de CI con búsqueda contra GET /cis?search=. */
export function CiSelect({ value, onChange }: { value: string | null; onChange: (v: string | null) => void }) {
  const [q, setQ] = useState('');
  const dq = useDebounced(q);
  const [options, setOptions] = useState<ConfigurationItem[]>([]);
  const [selected, setSelected] = useState<ConfigurationItem | null>(null);

  useEffect(() => {
    if (value && selected?.id !== value) cmdbService.get(value).then(setSelected).catch(() => {});
    if (!value) setSelected(null);
  }, [value, selected?.id]);

  useEffect(() => {
    let alive = true;
    cmdbService
      .list({ search: dq.length >= 2 ? dq : undefined, status: ['operational', 'degraded', 'down'], limit: 15, sort_by: 'name', sort_order: 'asc' })
      .then((r) => alive && setOptions(r.data))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [dq]);

  const list = selected && !options.some((o) => o.id === selected.id) ? [selected, ...options] : options;
  return (
    <div className="col gap-xs">
      <input className="input" placeholder="Buscar equipo o sistema…" value={q} onChange={(e) => setQ(e.target.value)} />
      <select className="select" value={value ?? ''} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">Ninguno en particular</option>
        {list.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name} · {c.type_name}
          </option>
        ))}
      </select>
    </div>
  );
}

export function LevelSelect({ value, onChange }: { value: Level | ''; onChange: (v: Level) => void }) {
  return (
    <select className="select" value={value} onChange={(e) => onChange(e.target.value as Level)}>
      <option value="" disabled>
        Selecciona…
      </option>
      {(['high', 'medium', 'low'] as Level[]).map((l) => (
        <option key={l} value={l}>
          {LEVEL[l]}
        </option>
      ))}
    </select>
  );
}

const CELL_BG: Record<string, string> = { P1: 'var(--danger)', P2: '#f2994a', P3: 'var(--warning-soft)', P4: 'var(--surface-2)' };
const CELL_FG: Record<string, string> = { P1: '#fff', P2: '#fff', P3: 'var(--warning)', P4: 'var(--text-2)' };

/** Matriz impacto × urgencia (D6) resaltando la combinación elegida. */
export function PriorityMatrix({ impact, urgency }: { impact: Level | ''; urgency: Level | '' }) {
  const levels: Level[] = ['high', 'medium', 'low'];
  return (
    <div className="prio-matrix" aria-label="Tabla de prioridad">
      <span>Alcance \ Urgencia</span>
      {levels.map((u) => (
        <span key={u}>{LEVEL[u]}</span>
      ))}
      {levels.map((i) => (
        <div key={i} style={{ display: 'contents' }}>
          <span>{LEVEL[i]}</span>
          {levels.map((u) => {
            const p = priorityOf(i, u);
            return (
              <div key={u} className={`cell ${impact === i && urgency === u ? 'sel' : ''}`} style={{ background: CELL_BG[p], color: CELL_FG[p], fontWeight: 700 }}>
                {p}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
