import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { changeService } from '../../api';
import { Icon } from '../../components/Icon';
import { ErrorBox, PageHeader, Spinner } from '../../components/ui';
import { CHANGE_STATUS } from '../../lib/format';
import { useAsync } from '../../lib/hooks';
import type { Change } from '../../types/api';

const DAYS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
const COLORS: Record<string, [string, string]> = {
  approved: ['var(--success-soft)', 'var(--success)'],
  scheduled: ['var(--accent-soft)', 'var(--accent)'],
  implemented: ['var(--surface-2)', 'var(--text-2)'],
};

function dayKey(d: Date) {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

export default function ChangeCalendar() {
  const nav = useNavigate();
  const [cursor, setCursor] = useState(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1);
  });

  // Rejilla de 6 semanas empezando el lunes.
  const days = useMemo(() => {
    const first = new Date(cursor);
    const offset = (first.getDay() + 6) % 7;
    first.setDate(first.getDate() - offset);
    return Array.from({ length: 42 }, (_, i) => new Date(first.getFullYear(), first.getMonth(), first.getDate() + i));
  }, [cursor]);

  const changes = useAsync(() => {
    const end = new Date(days[41]);
    end.setHours(23, 59, 59);
    return changeService.calendar(days[0].toISOString(), end.toISOString());
  }, [days[0].getTime()]);

  const byDay = useMemo(() => {
    const m = new Map<string, Change[]>();
    for (const c of changes.data ?? []) {
      if (!c.planned_start) continue;
      const k = dayKey(new Date(c.planned_start));
      m.set(k, [...(m.get(k) ?? []), c]);
    }
    return m;
  }, [changes.data]);

  const month = cursor.toLocaleDateString('es-PE', { month: 'long', year: 'numeric' });
  const today = dayKey(new Date());
  const shift = (n: number) => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + n, 1));

  return (
    <>
      <PageHeader
        back={
          <Link to="/app/changes" className="back-link">
            <Icon name="back" size={14} /> Actualizaciones
          </Link>
        }
        title="Calendario de actualizaciones"
        subtitle="Cuándo se hará cada actualización, para no interrumpir el trabajo de la empresa."
        actions={
          <div className="row gap-sm">
            <button className="btn btn-ghost btn-sm" onClick={() => shift(-1)} aria-label="Mes anterior">
              ‹
            </button>
            <strong style={{ minWidth: 150, textAlign: 'center', textTransform: 'capitalize' }}>{month}</strong>
            <button className="btn btn-ghost btn-sm" onClick={() => shift(1)} aria-label="Mes siguiente">
              ›
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setCursor(new Date(new Date().getFullYear(), new Date().getMonth(), 1))}>
              Hoy
            </button>
          </div>
        }
      />
      <div className="row gap wrap" style={{ fontSize: 13 }}>
        {Object.entries(COLORS).map(([k, [bg, fg]]) => (
          <span key={k} className="row gap-xs">
            <span style={{ width: 12, height: 12, borderRadius: 3, background: bg, border: `1px solid ${fg}` }} />
            {CHANGE_STATUS[k as keyof typeof CHANGE_STATUS][0]}
          </span>
        ))}
        {changes.loading && <span className="muted">Cargando…</span>}
      </div>
      {changes.error ? (
        <ErrorBox error={changes.error} onRetry={changes.reload} />
      ) : !changes.data ? (
        <Spinner />
      ) : (
        <section className="card" style={{ overflow: 'hidden' }}>
          <div className="table-wrap">
            <div className="cal" style={{ minWidth: 640 }}>
              {DAYS.map((d) => (
                <div className="cal-h" key={d}>
                  {d}
                </div>
              ))}
              {days.map((d) => {
                const k = dayKey(d);
                const list = byDay.get(k) ?? [];
                return (
                  <div key={k} className={`cal-d ${d.getMonth() !== cursor.getMonth() ? 'out' : ''} ${k === today ? 'today' : ''}`}>
                    <span className="n">{d.getDate()}</span>
                    {list.slice(0, 3).map((c) => {
                      const [bg, fg] = COLORS[c.status] ?? COLORS.implemented;
                      return (
                        <button
                          key={c.id}
                          className="cal-ev"
                          style={{ background: bg, color: fg, borderLeft: `3px solid ${c.risk === 'high' ? 'var(--danger)' : fg}` }}
                          title={`${c.key} · ${c.title}`}
                          onClick={() => nav(`/app/changes/${c.id}`)}
                        >
                          {new Date(c.planned_start!).toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit' })} {c.title}
                        </button>
                      );
                    })}
                    {list.length > 3 && <span className="cal-more">+{list.length - 3} más</span>}
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}
    </>
  );
}
